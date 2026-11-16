'use strict';
const $ = id => document.getElementById(id);
function node(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}
function clock(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], {hour12:false}) : '尚未采集';
}
function metric(label, value, kind) {
  const box = node('div');
  const known = typeof value === 'number' && Number.isFinite(value);
  const title = node('div', 'metric-label');
  title.append(node('span', '', label), node('strong', '', known ? `${value} / 20` : '—'));
  box.append(title);
  if (known) {
    const bar = node('progress', kind);
    bar.max = 20;
    bar.value = Math.max(0, Math.min(20, value));
    bar.setAttribute('aria-label', label);
    box.append(bar);
  }
  return box;
}
function renderAgent(agent, snapshotStale) {
  const mc = agent.minecraft || {};
  const stale = snapshotStale || mc.stale || !mc.observed_at || Date.now() - Date.parse(mc.observed_at) > 20000;
  const connected = mc.connected === true;
  const card = node('article', 'agent');
  const head = node('div', 'agent-head');
  const identity = node('div', 'identity');
  const name = String(agent.name || agent.service || 'Agent');
  identity.append(node('span', 'avatar', name[0].toUpperCase()));
  const names = node('div');
  names.append(node('h2', '', name), node('p', 'username', mc.username || agent.service));
  identity.append(names);
  head.append(identity, node('span', `badge ${stale || !connected ? 'offline' : 'online'}`, stale ? '状态不可用' : connected ? '游戏在线' : '游戏离线'));
  const body = node('div', 'body');
  if (stale || !connected) body.append(node('p', 'notice', [stale ? '当前状态不可用，已有数值仅为上次记录。' : '尚未连接或角色尚未出生。', mc.error || ''].filter(Boolean).join(' ')));
  const vitals = node('div', 'vitals');
  vitals.append(metric('生命值 · Health', mc.health, 'health'), metric('饱食度 · Hunger', mc.food, 'food'));
  body.append(vitals);
  const details = node('dl', 'details');
  const position = mc.position;
  const coords = position && ['x','y','z'].every(k => Number.isFinite(position[k]))
    ? ['x','y','z'].map(k => `${k.toUpperCase()} ${position[k].toFixed(1)}`).join('  ') : '—';
  const action = mc.active_action;
  for (const [label, value] of [
    ['位置', coords], ['维度', mc.dimension || '—'],
    ['手持物品', mc.held_item ? `${mc.held_item.name} × ${mc.held_item.count}` : connected ? '空手' : '—'],
    ['当前动作', action ? `${action.kind} · ${action.status}${Array.isArray(action.completed_blocks) ? ` · 已挖 ${action.completed_blocks.length} 块` : ''}` : connected ? '无执行中的游戏动作' : '—'],
  ]) details.append(node('dt', '', label), node('dd', '', value));
  body.append(details);
  // Group identical stacks. Registry names remain exact, rather than guessed translations.
  const counts = new Map();
  if (Array.isArray(mc.inventory)) for (const item of mc.inventory) {
    if (typeof item.name === 'string' && Number.isFinite(item.count) && item.count > 0) counts.set(item.name, (counts.get(item.name) || 0) + item.count);
  }
  body.append(node('h3', '', `背包物品${Array.isArray(mc.inventory) ? ` · ${counts.size} 种 / ${[...counts.values()].reduce((a,b) => a+b,0)} 件` : ''}`));
  const inventory = node('div', 'inventory');
  for (const [name, count] of [...counts].sort(([a],[b]) => a.localeCompare(b))) {
    const item = node('div', 'item');
    item.append(node('span', 'item-name', name), node('span', 'item-count', `× ${count}`));
    inventory.append(item);
  }
  if (!counts.size) body.append(node('p', 'placeholder', Array.isArray(mc.inventory) ? '背包为空' : '暂无背包数据'));
  else body.append(inventory);
  card.append(head, body, node('div', 'observed', `${stale ? '上次采集' : '采集时间'} · ${clock(mc.observed_at)}`));
  return card;
}
let lastState = null;
function render(state, transportError = null) {
  const stale = Boolean(transportError || state.error || !state.updated || Date.now() - Date.parse(state.updated) > 20000);
  $('connection').textContent = stale ? '采集不可用 / 已延迟' : '监控已连接';
  $('updated').textContent = `更新于 ${clock(state.updated)}`;
  $('error').textContent = transportError || state.error || '';
  $('error').hidden = !transportError && !state.error;
  const cards = (state.agents || []).map(agent => renderAgent(agent, stale));
  $('agents').replaceChildren(...(cards.length ? cards : [node('p', 'placeholder', '未发现 agent，请先生成 E16 部署配置。')]));
}
async function refresh() {
  try {
    const response = await fetch('/api/state', {signal: AbortSignal.timeout(12000), cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    if (!Array.isArray(state.agents)) throw new Error('无效的监控数据');
    lastState = state;
    render(state);
  } catch (error) {
    render(lastState || {agents:[]}, `无法连接 monitor：${error.message}`);
  } finally {
    setTimeout(refresh, 2000);
  }
}
refresh();
