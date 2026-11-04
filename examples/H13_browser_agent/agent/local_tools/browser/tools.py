"""Browser tool execution and conversation session management."""

import asyncio
import uuid

from browser_runtime.control import ensure_running, rpc

# Allocate the shared desktop to one active conversation to prevent concurrent agent control.
start_lock = asyncio.Lock()
current_owner = None


# Manage the browser connection, heartbeat, and display connection owned by a conversation.
class BrowserSession:
    def __init__(self):
        self.owner = uuid.uuid4().hex
        self.connected = False
        self.action_lock = asyncio.Lock()
        self.viewers = set()
        self.heartbeat = None

    async def connect(self):
        global current_owner
        async with start_lock:
            if current_owner and current_owner != self.owner:
                raise RuntimeError("浏览器正在被另一个对话使用，请先关闭其浏览器")
            if self.connected:
                return self.status()
            await asyncio.to_thread(ensure_running)
            await rpc({"owner": self.owner, "action": "acquire"})
            self.connected = True
            current_owner = self.owner
            self.heartbeat = asyncio.create_task(self.keep_alive())
            return self.status()

    # Renew the lease periodically so it does not expire while the model is thinking.
    async def keep_alive(self):
        while True:
            await asyncio.sleep(10)
            try:
                await rpc({"owner": self.owner, "action": "heartbeat"})
            except Exception:
                # An action will surface the connection error to the user.
                pass

    def status(self):
        return {
            "type": "browser",
            "connected": self.connected,
            "token": self.owner,
        }

    async def invoke(self, **arguments):
        async with self.action_lock:
            if not self.connected:
                await self.connect()
            return await rpc({"owner": self.owner, **arguments})

    async def disconnect_viewers(self):
        for viewer in tuple(self.viewers):
            try:
                await viewer.close(code=1000)
            except Exception:
                pass
        self.viewers.clear()

    async def close(self):
        global current_owner
        if self.heartbeat:
            self.heartbeat.cancel()
            self.heartbeat = None
        await self.disconnect_viewers()
        async with self.action_lock:
            try:
                if self.connected:
                    await rpc({"owner": self.owner, "action": "release"})
            finally:
                if current_owner == self.owner:
                    current_owner = None
                self.connected = False
