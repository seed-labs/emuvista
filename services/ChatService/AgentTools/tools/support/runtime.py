"""Standard-library Tinode session worker and local IPC client.

The launcher sends this source with each tool script. Login starts a detached
worker inside the Linux client container; subsequent tools use its Unix socket.
Only the worker talks to Tinode. One active account is supported per container.
Reference implementation: seed-emulator/chat-service/agent_chat/chat_transport.py
and agent_chat_service.py (session reuse, sub-before-pub, reply matching, noecho,
uncertain publish outcomes). Token reconnect and durable inbox are added here.
Protocol reference: https://github.com/tinode/chat/blob/v0.25.3/docs/API.md
"""

import base64
import json
import os
from pathlib import Path
import re
import select
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


STATE_DIR = Path("/root/.emuvista/chat/runtime")
SOCKET_PATH = str(STATE_DIR / "client.sock")
MAX_PACKET = 8 * 1024 * 1024
TOPIC_PATTERN = re.compile(r"^(?:usr|grp)[A-Za-z0-9_-]+$")
PROTOCOL_VERSION = 2


class ChatError(Exception):
    def __init__(self, message, unknown=False):
        self.message = message
        self.unknown = unknown
        super().__init__(message)


class Rejected(ChatError):
    def __init__(self, code):
        self.code = code
        super().__init__(
            "认证已失效，请重新登录。" if code == 401 else
            "没有权限执行此操作，请检查账号或会话权限。" if code == 403 else
            "目标用户或聊天会话不存在。" if code == 404 else
            "聊天服务拒绝了本次操作。"
        )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as output:
            temporary = output.name
            json.dump(value, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class Session:
    """Single-owner connection, durable inbox and automatic token reconnect."""

    def __init__(self, directory=STATE_DIR):
        self.directory = directory
        self.state_file = directory / "account.json"
        self.account = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.db = sqlite3.connect(str(directory / "inbox.sqlite3"))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inbox (
                owner TEXT, topic TEXT, seq INTEGER, payload TEXT,
                delivered INTEGER DEFAULT 0, batch TEXT,
                PRIMARY KEY(owner, topic, seq));
            CREATE TABLE IF NOT EXISTS checkpoints (
                owner TEXT, topic TEXT, seq INTEGER, PRIMARY KEY(owner, topic));
            CREATE TABLE IF NOT EXISTS history_scans (
                owner TEXT, topic TEXT, base INTEGER, high INTEGER, before_seq INTEGER,
                PRIMARY KEY(owner, topic));
        """)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.sid = None
        self.user = None
        self.attached = set()
        self.topics = set()
        self.responses = {}
        self.waiting = set()
        self.history_capture = None
        self.next_reconnect = 0
        self.next_discover = 0
        self.status = "请先登录聊天服务。"
        self.timeout = 15
        self.endpoint = None
        self.api_key = None

    def read_config(self):
        config = {}
        for line in Path("/root/chat.env").read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                config[key.strip()] = value.strip()
        host = config["TINODE_HOST"]
        port = int(config["TINODE_HTTP_PORT"])
        if not host or not 1 <= port <= 65535:
            raise ChatError("聊天服务地址配置不正确。")
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        self.endpoint = "http://{}:{}/v0/channels/lp".format(host, port)
        self.api_key = config["TINODE_API_KEY"]

    def request(self, payload, timeout):
        query = {"apikey": self.api_key}
        if self.sid:
            query["sid"] = self.sid
        request = urllib.request.Request(
            self.endpoint + "?" + urllib.parse.urlencode(query),
            data=b"" if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with self.opener.open(request, timeout=max(timeout, 0.05)) as response:
                raw = response.read(MAX_PACKET + 1)
        except urllib.error.HTTPError as error:
            error.close()
            self.disconnected()
            raise ChatError("聊天连接已中断，正在尝试恢复。") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError() from None
            self.disconnected()
            raise ChatError("无法连接聊天服务，正在尝试恢复。") from None
        except OSError as error:
            if isinstance(error, TimeoutError):
                raise
            self.disconnected()
            raise ChatError("聊天连接已中断，正在尝试恢复。") from None
        if len(raw) > MAX_PACKET:
            raise ChatError("聊天服务返回的信息过大。")
        value = json.loads(raw) if raw else []
        packets = [value] if isinstance(value, dict) else value
        if not isinstance(packets, list) or any(not isinstance(x, dict) for x in packets):
            raise ChatError("聊天服务返回了无法识别的信息。")
        return packets

    def disconnected(self):
        self.sid = None
        self.attached.clear()
        self.status = "聊天连接已中断，正在尝试恢复。"
        self.next_reconnect = time.monotonic() + 3

    def ingest(self, packets):
        for packet in packets:
            ctrl = packet.get("ctrl")
            meta = packet.get("meta")
            if isinstance(ctrl, dict) and ctrl.get("id") in self.waiting:
                self.responses.setdefault(ctrl["id"], []).append(("ctrl", ctrl))
            if isinstance(meta, dict):
                if meta.get("id") in self.waiting:
                    self.responses.setdefault(meta["id"], []).append(("meta", meta))
                if meta.get("topic") == "me":
                    for entry in meta.get("sub", []):
                        topic = entry.get("topic", "")
                        if TOPIC_PATTERN.fullmatch(topic) and not entry.get("deleted"):
                            self.topics.add(topic)
            presence = packet.get("pres", {})
            if isinstance(presence, dict) and presence.get("topic") == "me":
                topic = presence.get("src", "")
                if TOPIC_PATTERN.fullmatch(topic):
                    if presence.get("what") in ("gone", "term"):
                        self.attached.discard(topic)
                        self.topics.discard(topic)
                    elif presence.get("what") in ("msg", "on", "acs", "upd"):
                        self.topics.add(topic)
            data = packet.get("data")
            if isinstance(data, dict) and self.user:
                topic, seq = data.get("topic"), data.get("seq")
                sender = data.get("from") or "system"
                if not isinstance(topic, str) or type(seq) is not int or seq < 1:
                    raise ChatError("收到的消息缺少有效标识。")
                if self.history_capture is not None:
                    capture_topic, since, before, sequences = self.history_capture
                    if topic == capture_topic and since <= seq < before:
                        sequences.add(seq)
                if not isinstance(sender, str) or "content" not in data:
                    raise ChatError("收到的消息格式不完整。")
                content = data["content"]
                if isinstance(content, dict) and isinstance(content.get("txt"), str):
                    content = content["txt"]
                message = {
                    "message_id": topic + ":" + str(seq), "sender": sender,
                    "target": topic, "content": content if isinstance(content, str)
                    else json.dumps(content, ensure_ascii=False), "timestamp": data.get("ts"),
                }
                # Own messages are stored for history progress but never returned as inbox mail.
                self.db.execute(
                    "INSERT OR IGNORE INTO inbox(owner,topic,seq,payload,delivered) VALUES(?,?,?,?,?)",
                    (self.user, topic, seq, json.dumps(message, ensure_ascii=False), int(sender == self.user)),
                )
        self.db.commit()

    def poll(self, duration):
        try:
            self.ingest(self.request(None, duration))
        except TimeoutError:
            pass  # An idle long-poll timeout does not mean the session expired.

    def command(self, name, body, deadline, expect="ctrl"):
        if not self.sid:
            raise ChatError(self.status)
        if time.monotonic() >= deadline:
            raise TimeoutError()
        request_id = uuid.uuid4().hex
        self.waiting.add(request_id)
        try:
            self.ingest(self.request({name: dict(body, id=request_id)}, deadline - time.monotonic()))
            while True:
                for kind, packet in self.responses.pop(request_id, []):
                    if kind == "ctrl":
                        code = packet.get("code")
                        if type(code) is not int:
                            raise ChatError("聊天服务返回了无效状态。")
                        if not 200 <= code < 300:
                            raise Rejected(code)
                        # Empty metadata may be signalled by 204 rather than a meta packet.
                        if expect == "ctrl" or code == 204:
                            return packet
                    elif expect == "meta":
                        return packet
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.poll(min(remaining, 2))
        finally:
            self.waiting.discard(request_id)
            self.responses.pop(request_id, None)

    def connect(self, scheme, secret, deadline, username=None):
        self.read_config()
        self.sid = None
        self.user = None
        self.attached.clear()
        self.topics.clear()
        try:
            packets = self.request(None, deadline - time.monotonic())
            for packet in packets:
                self.sid = packet.get("ctrl", {}).get("params", {}).get("sid")
                if self.sid:
                    break
            if not isinstance(self.sid, str) or not self.sid:
                raise ChatError("未能建立聊天连接。")
            self.command("hi", {"ver": "0.25", "ua": "EmuVista persistent client"}, deadline)
            params = self.command("login", {"scheme": scheme, "secret": secret}, deadline).get("params", {})
            user = params.get("user")
            if not isinstance(user, str) or not user:
                raise ChatError("登录未返回有效身份。")
            if scheme == "token" and user != self.account.get("user_id"):
                raise ChatError("恢复的账号身份不一致，请重新登录。")
            self.user = user
            self.command("sub", {"topic": "me"}, deadline)
            self.attached.add("me")
            account = dict(
                username=username or self.account.get("username"), user_id=user,
                token=params.get("token") or (secret if scheme == "token" else None),
                expires=params.get("expires"),
                binding=uuid.uuid4().hex if scheme == "basic" else self.account["binding"],
            )
            atomic_json(self.state_file, account)
            self.account = account
            self.status = "已登录。"
            self.next_discover = 0
        except Exception:
            self.disconnected()
            raise

    def ensure_connected(self, deadline):
        if self.account.get("login_required"):
            raise ChatError("上次登录未完成，请重新登录后再操作。")
        if self.sid and self.user:
            return
        token = self.account.get("token")
        if not token:
            raise ChatError("请先登录聊天服务。")
        try:
            self.connect("token", token, deadline)
        except Rejected:
            # Do not retain a rejected token for repeated background login attempts.
            self.account["token"] = None
            atomic_json(self.state_file, self.account)
            self.status = "登录状态已失效，请重新登录。"
            raise ChatError(self.status) from None

    def attach(self, topic, deadline):
        if topic not in self.attached:
            reply = self.command("sub", {"topic": topic}, deadline)
            canonical = reply.get("topic", topic)
            self.attached.update((topic, canonical))
        self.topics.add(topic)

    def discover(self, deadline):
        self.command("get", {"topic": "me", "what": "sub"}, deadline, expect="meta")
        self.next_discover = time.monotonic() + 30

    def fetch_history(self, topic, deadline):
        """Walk backwards through bounded pages; advance only after complete catch-up.

        Live messages do not advance the history checkpoint, so a newer live
        message cannot hide older messages arriving while the client was offline.
        """
        self.attach(topic, deadline)
        row = self.db.execute("SELECT seq FROM checkpoints WHERE owner=? AND topic=?",
                              (self.user, topic)).fetchone()
        checkpoint = row[0] if row else 0
        scan = self.db.execute(
            "SELECT base,high,before_seq FROM history_scans WHERE owner=? AND topic=?",
            (self.user, topic),
        ).fetchone()
        if scan:
            checkpoint, high, before = scan
        else:
            description = self.command("get", {"topic": topic, "what": "desc"}, deadline, expect="meta")
            high = description.get("desc", {}).get("seq", 0)
            if type(high) is not int or high < 0:
                raise ChatError("无法确认聊天记录范围。")
            high = max(high, checkpoint)
            before = high + 1
            self.db.execute("INSERT OR REPLACE INTO history_scans VALUES(?,?,?,?,?)",
                            (self.user, topic, checkpoint, high, before))
            self.db.commit()
        for _ in range(100):
            if before <= checkpoint + 1:
                self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)",
                                (self.user, topic, high))
                self.db.execute("DELETE FROM history_scans WHERE owner=? AND topic=?", (self.user, topic))
                self.db.commit()
                return
            options = {"since": checkpoint + 1, "before": before, "limit": 100}
            sequences = set()
            # Tinode v0.25.3 history data has no request id. One serialized command
            # plus a fixed sequence snapshot separates it from newer live traffic.
            self.history_capture = (topic, checkpoint + 1, before, sequences)
            try:
                self.command("get", {"topic": topic, "what": "data", "data": options}, deadline)
            finally:
                self.history_capture = None
            if not sequences:
                self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)",
                                (self.user, topic, high))
                self.db.execute("DELETE FROM history_scans WHERE owner=? AND topic=?", (self.user, topic))
                self.db.commit()
                return
            before = min(sequences)
            self.db.execute("UPDATE history_scans SET before_seq=? WHERE owner=? AND topic=?",
                            (before, self.user, topic))
            self.db.commit()
            if time.monotonic() >= deadline:
                break
        raise ChatError("历史消息仍在同步，请稍后再次收取。")

    def inbox(self, arguments):
        receipt = arguments.get("_ack")
        if receipt:
            self.db.execute("UPDATE inbox SET delivered=1,batch=NULL WHERE owner=? AND batch=?",
                            (self.user, receipt))
            self.db.commit()
        # Unacknowledged messages remain eligible after a lost response/restart.
        # Issue a new receipt only for this exact selection, respecting target/limit.
        target = arguments.get("target")
        rows = self.db.execute(
            "SELECT rowid,payload FROM inbox WHERE owner=? AND delivered=0 "
            + ("AND topic=? " if target else "") + "ORDER BY topic,seq LIMIT ?",
            (self.user,) + ((target,) if target else ()) + (arguments.get("limit", 50),),
        ).fetchall()
        receipt = uuid.uuid4().hex if rows else None
        for row_id, _ in rows:
            self.db.execute("UPDATE inbox SET batch=? WHERE rowid=?", (receipt, row_id))
        self.db.commit()
        messages = [json.loads(payload) for _, payload in rows]
        return dict(successful=True, message="已收取消息。" if messages else "暂无新消息。",
                    messages=messages, _receipt=receipt)

    def handle(self, operation, arguments):
        self.timeout = max(1, min(int(arguments.get("_timeout", 15)), 120))
        deadline = min(time.monotonic() + self.timeout, arguments.get("_deadline", float("inf")))
        if time.monotonic() >= deadline:
            raise ChatError("请求已超时，本次操作未执行。")
        if operation == "login":
            return login(self, arguments, deadline)
        if operation not in ("send_message", "receive_messages", "_context"):
            raise ChatError("不支持的聊天操作。")
        expected = arguments.get("_binding")
        if expected and expected != self.account.get("binding"):
            raise ChatError("当前客户端账号已变更，请重新登录后再操作。")
        self.ensure_connected(deadline)
        if operation == "_context":
            return dict(successful=True, message="已恢复聊天身份。")
        target = arguments.get("target")
        if target is not None and (not isinstance(target, str) or not TOPIC_PATTERN.fullmatch(target)):
            raise ChatError("请提供有效的用户 ID 或群 ID。")
        if operation == "send_message":
            return send_message(self, arguments, deadline)
        return receive_messages(self, arguments, deadline)

    def maintain(self):
        now = time.monotonic()
        if not self.sid:
            if self.account.get("token") and now >= self.next_reconnect:
                self.next_reconnect = now + 5
                try:
                    self.ensure_connected(now + 5)
                except (ChatError, TimeoutError, OSError, ValueError):
                    pass
            return
        try:
            # Regular polling keeps the authenticated session alive even between tool calls.
            self.poll(0.5)
            if now >= self.next_discover:
                self.discover(time.monotonic() + 3)
            for topic in sorted(self.topics - self.attached)[:1]:
                try:
                    self.attach(topic, time.monotonic() + 3)
                except Rejected:
                    self.topics.discard(topic)
        except (ChatError, TimeoutError, OSError, ValueError):
            self.next_discover = time.monotonic() + 5


def read_packet(connection):
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(65536)
        if not chunk:
            raise ChatError("聊天客户端连接中断。")
        data.extend(chunk)
        if len(data) > MAX_PACKET:
            raise ChatError("聊天请求或结果过大。")
    return json.loads(bytes(data).split(b"\n", 1)[0])


def failure(operation, message, unknown=False):
    result = dict(successful=False, message=message)
    if operation == "send_message":
        result.update(status="unknown" if unknown else "failed", message_id=None)
    elif operation == "receive_messages":
        result["messages"] = []
    return result


def serve():
    import fcntl

    os.umask(0o077)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE_DIR / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        Path(SOCKET_PATH).unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(SOCKET_PATH)
        listener.listen(16)
        session = Session()
        try:
            while True:
                ready, _, _ = select.select([listener], [], [], 0.1)
                if not ready:
                    session.maintain()
                    continue
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    operation = ""
                    try:
                        request = read_packet(connection)
                        operation = request["operation"]
                        if operation == "_ping":
                            reply = {"version": PROTOCOL_VERSION}
                        else:
                            reply = session.handle(operation, request.get("arguments", {}))
                            reply["_binding"] = session.account.get("binding")
                            reply["_identity"] = {
                                "server": session.endpoint,
                                "username": session.account.get("username"),
                                "user_id": session.account.get("user_id"),
                            }
                    except ChatError as error:
                        reply = failure(operation, error.message, error.unknown)
                    except TimeoutError:
                        reply = failure(operation, "操作超时，请稍后重试。")
                    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
                        reply = failure(operation, "聊天客户端暂时无法完成操作。")
                    try:
                        connection.sendall(json.dumps(reply, ensure_ascii=False).encode() + b"\n")
                    except OSError:
                        pass  # Inbox batches remain pending until the caller acknowledges them.
        finally:
            listener.close()
            session.db.close()
            Path(SOCKET_PATH).unlink(missing_ok=True)


def rpc(operation, arguments, timeout):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(SOCKET_PATH)
        connection.sendall(json.dumps({"operation": operation, "arguments": arguments}).encode() + b"\n")
        return read_packet(connection)


def ensure_worker():
    import fcntl

    os.umask(0o077)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE_DIR / "start.lock").open("a") as lock:
        # Non-blocking lock avoids killing a waiting caller while another worker starts.
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ChatError("聊天客户端正在启动，请稍后重试。")
                time.sleep(0.1)
        try:
            # Connecting successfully means a worker exists; it may currently be busy.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(1)
                probe.connect(SOCKET_PATH)
            return
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; exec(sys.stdin.read())"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
        process.stdin.write((_RUNTIME_SOURCE + "\nserve()\n").encode())
        process.stdin.close()
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ChatError("聊天客户端启动失败，请检查运行环境。")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.connect(SOCKET_PATH)
                return
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        raise ChatError("聊天客户端启动超时，请稍后重试。")


def tool_main(operation):
    try:
        arguments = json.loads(sys.argv[1])
        ensure_worker()
        arguments["_deadline"] = time.monotonic() + arguments.get("_timeout", 15)
        result = rpc(operation, arguments, arguments.get("_timeout", 15) + 12)
    except (TimeoutError, socket.timeout):
        result = failure(operation, "尚未确认发送结果，请先检查聊天记录，避免重复发送。"
                         if operation == "send_message" else "操作超时，请稍后重试。",
                         unknown=operation == "send_message")
    except ChatError as error:
        result = failure(operation, error.message, unknown=operation == "send_message")
    except (OSError, ValueError, TypeError):
        result = failure(operation, "聊天客户端暂时不可用，请稍后重试。",
                         unknown=operation == "send_message")
    print(json.dumps(result, ensure_ascii=False))
