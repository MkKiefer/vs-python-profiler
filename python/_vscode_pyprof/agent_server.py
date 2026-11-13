"""Collector side of the agent connection (localhost TCP + shared token)."""

from __future__ import annotations

import itertools
import json
import secrets
import socket
import threading
import traceback


class AgentConnection:
    def __init__(self, sock: socket.socket, hello: dict, on_message, on_close, initial: bytes = b""):
        self.sock = sock
        self.hello = hello
        self.pid = hello.get("pid")
        self._on_message = on_message
        self._on_close = on_close
        self._ids = itertools.count(1)
        self._pending: dict = {}
        self._wlock = threading.Lock()
        self.alive = True
        self._initial = initial
        threading.Thread(target=self._reader, name="pyprof-agent-reader", daemon=True).start()

    def request(self, method: str, params=None, timeout: float = 60.0):
        if not self.alive:
            raise RuntimeError("agent is not connected")
        mid = next(self._ids)
        ev = threading.Event()
        slot: dict = {}
        self._pending[mid] = (ev, slot)
        data = (json.dumps({"id": mid, "method": method, "params": params or {}}) + "\n").encode()
        with self._wlock:
            self.sock.sendall(data)
        if not ev.wait(timeout):
            self._pending.pop(mid, None)
            raise TimeoutError(f"agent did not answer {method!r} within {timeout:.0f}s")
        if "error" in slot:
            raise RuntimeError(slot["error"])
        return slot.get("result")

    def close(self):
        try:
            self.request("shutdown", timeout=2)
        except Exception:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _reader(self):
        buf = self._initial
        self._initial = b""
        try:
            while True:
                chunk = self.sock.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if msg.get("type") == "result":
                        pend = self._pending.pop(msg.get("id"), None)
                        if pend:
                            ev, slot = pend
                            slot.update(msg)
                            ev.set()
                    else:
                        try:
                            self._on_message(self, msg)
                        except Exception:
                            traceback.print_exc()
        except OSError:
            pass
        except ValueError:
            traceback.print_exc()
        finally:
            self.alive = False
            for ev, slot in list(self._pending.values()):
                slot["error"] = "agent disconnected"
                ev.set()
            self._pending.clear()
            self._on_close(self)


class AgentServer:
    def __init__(self, on_hello, on_message, on_close):
        self.token = secrets.token_hex(16)
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self.host, self.port = self._srv.getsockname()
        self._on_hello = on_hello
        self._on_message = on_message
        self._on_close = on_close
        threading.Thread(target=self._accept, name="pyprof-agent-server", daemon=True).start()

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}:{self.token}"

    def _accept(self):
        while True:
            try:
                sock, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handshake, args=(sock,), daemon=True).start()

    def _handshake(self, sock):
        sock.settimeout(10)
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    raise OSError("closed during handshake")
                buf += chunk
            line, rest = buf.split(b"\n", 1)
            hello = json.loads(line)
            if hello.get("type") != "hello" or not secrets.compare_digest(str(hello.get("token")), self.token):
                raise OSError("bad agent token")
        except (OSError, ValueError):
            sock.close()
            return
        sock.settimeout(None)
        conn = AgentConnection(sock, hello, self._on_message, self._on_close, initial=rest)
        self._on_hello(conn)

    def close(self):
        try:
            self._srv.close()
        except OSError:
            pass
