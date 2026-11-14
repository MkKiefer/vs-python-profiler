"""The collector's side of the in-process agent.

``AgentInjector`` starts the agent inside an already running program (attach
mode, ``sys.remote_exec``); ``AgentServer`` accepts the agent's connection
(localhost TCP + shared token) and exchanges messages with it. The agent
itself lives in ``_vscode_pyprof.target.agent``.
"""

import itertools
import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass

from _vscode_pyprof import PACKAGE_DIR
from _vscode_pyprof.wire import JsonObject, WireReader


class AgentError(RuntimeError):
    """The in-process agent failed, timed out or disconnected."""


@dataclass(frozen=True, slots=True)
class AgentHello:
    """What the agent tells us about its process when it connects."""

    pid: int
    executable: str | None
    argv: list[str]
    cwd: str | None
    threads: list[object]

    @classmethod
    def from_wire(cls, message: WireReader) -> AgentHello:
        return cls(
            pid=message.get_int("pid"),
            executable=message.get_optional_str("executable"),
            argv=message.get_str_list("argv"),
            cwd=message.get_optional_str("cwd"),
            threads=message.get_list("threads"),
        )


class AgentListener(ABC):
    """Receives the life-cycle of agent connections."""

    @abstractmethod
    def on_agent_hello(self, connection: AgentConnection) -> None: ...

    @abstractmethod
    def on_agent_message(self, connection: AgentConnection, message: WireReader) -> None: ...

    @abstractmethod
    def on_agent_close(self, connection: AgentConnection) -> None: ...


class _PendingRequest:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.reply: WireReader | None = None


class AgentConnection:
    """One authenticated agent: request/response plus unsolicited messages."""

    def __init__(self, sock: socket.socket, hello: AgentHello, listener: AgentListener, buffered: bytes = b"") -> None:
        self._sock = sock
        self._hello = hello
        self._listener = listener
        self._buffered = buffered
        self._ids = itertools.count(1)
        self._pending: dict[int, _PendingRequest] = {}
        self._write_lock = threading.Lock()
        self._alive = True

    @property
    def hello(self) -> AgentHello:
        return self._hello

    @property
    def alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        threading.Thread(target=self._read_loop, name="pyprof-agent-reader", daemon=True).start()

    def request(self, method: str, params: JsonObject | None = None, timeout: float = 60.0) -> WireReader:
        """Call a command in the target process and wait for its result."""
        if not self._alive:
            raise AgentError("agent is not connected")
        request_id = next(self._ids)
        pending = _PendingRequest()
        self._pending[request_id] = pending
        data = (json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n").encode()
        try:
            with self._write_lock:
                self._sock.sendall(data)
            if not pending.done.wait(timeout):
                raise AgentError(f"agent did not answer {method!r} within {timeout:.0f}s")
        except OSError as error:
            raise AgentError(f"agent connection lost: {error}") from error
        finally:
            self._pending.pop(request_id, None)
        reply = pending.reply
        if reply is None:
            raise AgentError("agent disconnected")
        if reply.has("error"):
            raise AgentError(str(reply.get_raw("error")))
        return reply.get_object("result")

    def close(self) -> None:
        """Ask the agent to stop, then drop the connection."""
        try:
            self.request("shutdown", timeout=2)
        except AgentError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def _read_loop(self) -> None:
        buffer = self._buffered
        self._buffered = b""
        try:
            while True:
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self._dispatch(WireReader.of(json.loads(line)))
                chunk = self._sock.recv(1 << 20)
                if not chunk:
                    break
                buffer += chunk
        except OSError:
            pass
        except ValueError:
            traceback.print_exc(file=sys.stderr)
        finally:
            self._alive = False
            for pending in list(self._pending.values()):
                pending.done.set()  # reply stays None: "agent disconnected"
            self._listener.on_agent_close(self)

    def _dispatch(self, message: WireReader) -> None:
        if message.get_optional_str("type") == "result":
            pending = self._pending.get(message.get_int("id", -1))
            if pending is not None:
                pending.reply = message
                pending.done.set()
            return
        try:
            self._listener.on_agent_message(self, message)
        except Exception:  # a bad message must not kill the reader
            traceback.print_exc(file=sys.stderr)


class AgentServer:
    """Listens on localhost for agents that present our one-time token."""

    _HANDSHAKE_TIMEOUT = 10.0

    def __init__(self) -> None:
        self._token = secrets.token_hex(16)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        self._host, self._port = self._socket.getsockname()
        self._listener: AgentListener | None = None

    @property
    def address(self) -> str:
        """``host:port:token`` - what the agent needs to connect back."""
        return f"{self._host}:{self._port}:{self._token}"

    def start(self, listener: AgentListener) -> None:
        self._listener = listener
        threading.Thread(target=self._accept_loop, name="pyprof-agent-server", daemon=True).start()

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while True:
            try:
                sock, _ = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._handshake, args=(sock,), daemon=True).start()

    def _handshake(self, sock: socket.socket) -> None:
        listener = self._listener
        if listener is None:
            sock.close()
            return
        sock.settimeout(self._HANDSHAKE_TIMEOUT)
        buffer = b""
        try:
            while b"\n" not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    raise OSError("closed during handshake")
                buffer += chunk
            line, rest = buffer.split(b"\n", 1)
            message = WireReader.of(json.loads(line))
            token = (message.get_optional_str("token") or "").encode()
            if message.get_optional_str("type") != "hello" or not secrets.compare_digest(token, self._token.encode()):
                raise OSError("bad agent token")
            hello = AgentHello.from_wire(message)
        except OSError, ValueError:
            sock.close()
            return
        sock.settimeout(None)
        connection = AgentConnection(sock, hello, listener, buffered=rest)
        listener.on_agent_hello(connection)
        connection.start()


class AgentInjectionError(RuntimeError):
    """The agent could not be injected into the target."""


class AgentInjector:
    """Uses ``sys.remote_exec`` (PEP 768) to run a bootstrap script in the target."""

    _SCRIPT_LIFETIME = 60.0  # the target runs the script at its next safe point

    def __init__(self) -> None:
        self._script_path: str | None = None

    @staticmethod
    def is_supported() -> bool:
        return hasattr(sys, "remote_exec")

    def inject(self, pid: int, agent_address: str, options: JsonObject) -> None:
        if not self.is_supported():
            raise AgentInjectionError("sys.remote_exec is not available in this interpreter")
        path = self._write_script(agent_address, options)
        self._script_path = path
        try:
            sys.remote_exec(pid, path)
        except Exception as error:  # remote_exec raises a wide range of OS and runtime errors
            self.cleanup()
            message = str(error)
            if "disable" in message.lower():
                message += (
                    " (the target disabled remote debugging via PYTHON_DISABLE_REMOTE_DEBUG / -X disable_remote_debug)"
                )
            raise AgentInjectionError(message) from error
        timer = threading.Timer(self._SCRIPT_LIFETIME, self.cleanup)
        timer.daemon = True
        timer.start()

    def cleanup(self) -> None:
        """Delete the bootstrap script (called once the agent has connected)."""
        path, self._script_path = self._script_path, None
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _write_script(agent_address: str, options: JsonObject) -> str:
        host, port, token = agent_address.rsplit(":", 2)
        package_parent = os.path.dirname(PACKAGE_DIR)
        # The package is put on sys.path only for the import, so it can never
        # shadow or leak into the user's own imports.
        script = (
            "def _pyprof_boot():\n"
            "    import sys\n"
            f"    p = {package_parent!r}\n"
            "    added = p not in sys.path\n"
            "    if added:\n"
            "        sys.path.insert(0, p)\n"
            "    try:\n"
            "        from _vscode_pyprof.target import agent\n"
            "    finally:\n"
            "        if added and p in sys.path:\n"
            "            sys.path.remove(p)\n"
            f"    agent.start({host!r}, {int(port)}, {token!r}, {options!r})\n"
            "_pyprof_boot()\n"
            "del _pyprof_boot\n"
        )
        fd, path = tempfile.mkstemp(prefix="pyprof_inject_", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        return path
