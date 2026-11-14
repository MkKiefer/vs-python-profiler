"""The collector's end of the connection to one in-process agent."""

import itertools
import socket
import sys
import threading
import traceback

from _vscode_pyprof.agent_protocol import AgentCommand, AgentMessageType
from _vscode_pyprof.collector.agent.hello import AgentHello
from _vscode_pyprof.collector.agent.listener import AgentListener
from _vscode_pyprof.wire import JsonLines, JsonObject, WireReader


class AgentError(RuntimeError):
    """The in-process agent failed, timed out or disconnected."""


class _PendingRequest:
    """A request waiting for its reply; ``reply`` stays ``None`` if the agent disconnects first."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.reply: WireReader | None = None


class AgentConnection:
    """One authenticated agent: request/response plus unsolicited messages."""

    DEFAULT_TIMEOUT = 60.0
    _SHUTDOWN_TIMEOUT = 2.0
    _RECEIVE_SIZE = 1 << 20

    def __init__(self, sock: socket.socket, hello: AgentHello, listener: AgentListener, lines: JsonLines) -> None:
        """``lines`` may already hold what the agent sent right after its hello."""
        self._sock = sock
        self._hello = hello
        self._listener = listener
        self._lines = lines
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

    def request(self, method: str, params: JsonObject | None = None, timeout: float = DEFAULT_TIMEOUT) -> WireReader:
        """Run a command in the target process and return its result.

        Raises ``AgentError`` if the agent reports a failure, does not answer
        within ``timeout`` seconds or is not connected (any more).
        """
        if not self._alive:
            raise AgentError("agent is not connected")
        request_id = next(self._ids)
        pending = _PendingRequest()
        self._pending[request_id] = pending
        data = JsonLines.encode({"id": request_id, "method": method, "params": params or {}})
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
            self.request(AgentCommand.SHUTDOWN, timeout=self._SHUTDOWN_TIMEOUT)
        except AgentError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def _read_loop(self) -> None:
        try:
            while True:
                while (message := self._lines.next_message()) is not None:
                    self._dispatch(message)
                chunk = self._sock.recv(self._RECEIVE_SIZE)
                if not chunk:
                    break
                self._lines.feed(chunk)
        except OSError:
            pass  # the connection was closed
        except ValueError:  # the agent sent something that is not JSON
            traceback.print_exc(file=sys.stderr)
        finally:
            self._alive = False
            for pending in list(self._pending.values()):
                pending.done.set()  # reply stays None: "agent disconnected"
            self._listener.on_agent_close(self)

    def _dispatch(self, message: WireReader) -> None:
        if message.get_optional_str("type") == AgentMessageType.RESULT:
            pending = self._pending.get(message.get_int("id", -1))
            if pending is not None:
                pending.reply = message
                pending.done.set()
            return
        try:
            self._listener.on_agent_message(self, message)
        except Exception:  # a bad message must not kill the reader
            traceback.print_exc(file=sys.stderr)
