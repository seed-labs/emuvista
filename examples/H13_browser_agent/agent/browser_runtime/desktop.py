"""Agent-owned page observation, actions and conversation isolation."""

import asyncio
import logging
import time
import uuid
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field


# Restrict model-callable browser actions and parameters; reject arbitrary scripts.
class Command(BaseModel):
    owner: str = Field(min_length=16, max_length=100)
    action: Literal['acquire', 'release', 'heartbeat', 'observe', 'open', 'click', 'fill', 'select',
                    'press', 'check', 'scroll', 'back', 'switch_tab']
    url: str | None = Field(default=None, max_length=2048)
    ref: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=8000)
    checked: bool = True
    delta: int = Field(default=600, ge=-2000, le=2000)
    tab: int = Field(default=0, ge=0, le=30)


# Connect to the colocated browser through Playwright and perform page actions.
class Desktop:
    def __init__(self):
        self.last_seen = 0.0
        self.owner = None
        self.context = None
        self.browser = None
        self.page = None
        self.refs = {}
        self.lock = asyncio.Lock()
        self.playwright = None

    # Allow one conversation per desktop; reclaim expired leases on the next connection.
    async def acquire(self, owner):
        if self.owner and time.monotonic() - self.last_seen > 60:
            await self.context.close()
            self.owner, self.context, self.page, self.refs = None, None, None, {}
        if self.owner and self.owner != owner:
            raise HTTPException(409, '浏览器正在被另一个对话使用，请先关闭该对话的浏览器')
        if not self.owner:
            if self.browser is None or not self.browser.is_connected():
                from .control import connection_config
                config = connection_config()
                if self.playwright is None:
                    self.playwright = await async_playwright().start()
                try:
                    self.browser = await self.playwright.chromium.connect(config['ws_endpoint'], timeout=20000)
                except Exception:
                    await self.playwright.stop()
                    self.playwright = None
                    raise RuntimeError('无法连接 本容器 Playwright 服务，请检查场景和连接配置') from None
            self.context = await self.browser.new_context(no_viewport=True, accept_downloads=False)
            self.context.set_default_timeout(12000)
            self.context.on('page', self.new_page)
            self.page = await self.context.new_page()
            self.owner = owner
        self.last_seen = time.monotonic()
        return {'connected': True}

    def new_page(self, page):
        self.page = page
        page.on('dialog', lambda dialog: dialog.dismiss())

    # Assign fresh element references on every observation to avoid targeting an outdated page.
    async def observe(self):
        if self.page is None or self.page.is_closed():
            self.page = next((p for p in self.context.pages if not p.is_closed()), None)
            if self.page is None:
                self.page = await self.context.new_page()
        await self.page.bring_to_front()
        self.refs = {}
        frames = []
        prefix = uuid.uuid4().hex[:12]
        for frame_index, frame in enumerate(self.page.frames[:6]):
            try:
                data = await frame.evaluate('''(prefix) => {
                    const visible = e => {
                      const style = getComputedStyle(e);
                      return e.getClientRects().length && style.visibility !== 'hidden' &&
                        style.visibility !== 'collapse' && style.opacity !== '0';
                    };
                    // Styled radio/checkbox inputs may be clipped and ignore pointer events.
                    // Their visible label is the actual click target (and can own onclick).
                    const candidates = [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],label[for],label[onclick]')]
                      .map(e => e.matches('input[type=radio],input[type=checkbox]')
                        ? ([...(e.labels || [])].find(label => visible(label) &&
                            getComputedStyle(label).pointerEvents !== 'none') || e) : e);
                    const nodes = [...new Set(candidates)]
                      .filter(e => visible(e) && getComputedStyle(e).pointerEvents !== 'none').slice(0,100);
                    const name = e => [e.getAttribute('aria-label'),
                      e.getAttribute('data-bs-title'), e.getAttribute('data-bs-original-title'),
                      e.getAttribute('title'), e.labels?.[0]?.innerText, e.innerText,
                      e.querySelector('img[alt]')?.getAttribute('alt'),
                      e.getAttribute('placeholder'), e.getAttribute('name')]
                      .find(value => value?.trim())?.trim() || '';
                    const elements = nodes.map((e,i) => {
                      const ref = prefix + '-' + i; e.setAttribute('data-agent-ref',ref);
                      const control = e.tagName === 'LABEL' ? e.control : e;
                      return {ref,tag:e.tagName.toLowerCase(),type:control?.getAttribute('type'),
                        label:name(e).slice(0,200),
                        href:e.tagName==='A'?e.href:undefined,disabled:!!control?.disabled,
                        options:e.tagName==='SELECT'?[...e.options].map(o=>({label:o.text,value:o.value})).slice(0,40):undefined};
                    });
                    return {text:(document.body?.innerText||'').slice(0,14000),elements};
                }''', f'{prefix}-{frame_index}')
                for item in data['elements']:
                    self.refs[item['ref']] = frame.locator(f'[data-agent-ref="{item["ref"]}"]')
                frames.append({'url': frame.url, **data})
            except Exception:
                frames.append({'url': frame.url, 'error': 'Frame unavailable; observe again'})
        return {'url': self.page.url, 'title': await self.page.title(), 'frames': frames,
                'tabs': [{'index': i, 'url': p.url} for i, p in enumerate(self.context.pages)],
                'observation': prefix}

    # Serialize actions and return a fresh observation afterward; never retry failed payments automatically.
    async def command(self, cmd):
        async with self.lock:
            if cmd.action == 'acquire':
                return await self.acquire(cmd.owner)
            if not self.owner or self.owner != cmd.owner:
                raise HTTPException(409, '请先连接此对话的浏览器')
            self.last_seen = time.monotonic()
            if cmd.action == 'heartbeat':
                return {'alive': True}
            if cmd.action == 'release':
                try:
                    await self.context.close()
                finally:
                    self.owner, self.context, self.page, self.refs = None, None, None, {}
                    if self.browser:
                        await self.browser.close()
                    if self.playwright:
                        await self.playwright.stop()
                    self.browser, self.playwright = None, None
                return {'closed': True}
            if cmd.action == 'observe':
                return await self.observe()
            if cmd.action == 'open':
                parsed = urlsplit(cmd.url or '')
                if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                    raise HTTPException(400, '只能打开 HTTP(S) 地址')
                await self.page.goto(cmd.url, wait_until='domcontentloaded', timeout=20000)
            elif cmd.action == 'back':
                await self.page.go_back(wait_until='domcontentloaded', timeout=20000)
            elif cmd.action == 'switch_tab':
                if cmd.tab >= len(self.context.pages):
                    raise HTTPException(400, '标签页不存在，请重新观察')
                self.page = self.context.pages[cmd.tab]
            elif cmd.action == 'scroll':
                await self.page.mouse.wheel(0, cmd.delta)
            else:
                locator = self.refs.get(cmd.ref)
                if locator is None:
                    return {'action_performed': False, 'reason': '元素引用过期，请使用新观察中的 ref',
                            **await self.observe()}
                if cmd.action == 'click':
                    await locator.click()
                elif cmd.action == 'fill':
                    if cmd.value is None:
                        raise HTTPException(400, 'fill 需要 value')
                    await locator.fill(cmd.value)
                elif cmd.action == 'select':
                    await locator.select_option(value=cmd.value)
                elif cmd.action == 'press':
                    if cmd.value not in {'Enter', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp'}:
                        raise HTTPException(400, '不支持此按键')
                    await locator.press(cmd.value)
                elif cmd.action == 'check':
                    await locator.set_checked(cmd.checked)
            return {'action_performed': True, **await self.observe()}


desktop = Desktop()


async def execute(payload):
    cmd = Command(**payload)
    try:
        return await asyncio.wait_for(desktop.command(cmd), timeout=35)
    except HTTPException:
        raise
    except Exception as error:
        # Do not echo filled credentials or automatically repeat a click/payment.
        error_type = type(error).__name__
        message = str(error).lower()
        reason = 'browser_error'
        if 'strict mode violation' in message:
            reason = 'ambiguous_element'
        elif 'execution context was destroyed' in message:
            reason = 'page_navigating'
        elif 'target page, context or browser has been closed' in message:
            reason = 'page_closed'
        elif 'intercepts pointer events' in message:
            reason = 'element_covered'
        elif 'not visible' in message:
            reason = 'element_not_visible'
        elif 'net::err_' in message:
            reason = 'navigation_network_error'
        elif isinstance(error, TimeoutError) or error_type == 'TimeoutError':
            reason = 'timeout'
        logging.getLogger(__name__).warning(
            'Browser command failed: action=%s error_type=%s reason=%s',
            cmd.action, error_type, reason,
        )
        if cmd.action in {'acquire', 'release', 'heartbeat'}:
            raise RuntimeError('浏览器会话操作失败，请关闭后重新启动浏览器会话') from None
        return {'action_performed': 'unknown', 'failed_action': cmd.action,
                'error_type': error_type, 'reason': reason,
                'error': '浏览器操作失败或超时；请先 observe 确认页面和账单状态，勿重复提交付款'}
