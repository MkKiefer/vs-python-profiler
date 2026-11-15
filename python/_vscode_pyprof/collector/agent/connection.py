"""The collector's end of the connection to one in-process agent."""

import itertools
import socket
import sys
import threading
import traceback

from _vscode_pyprof.agent_protocol.commands import AgentRequest, CommandCall, CommandResult, Shutdown
from _vscode_pyprof.agent_protocol.hello import AgentHello
from _vscode_pyprof.agent_protocol.metrics import AgentMetrics
from _vscode_pyprof.agent_protocol.names import AgentMessageType
from _vscode_pyprof.agent_protocol.replies import Acknowledgement
from _vscode_pyprof.collector.agent.listener import AgentListener
from _vscode_pyprof.wire import JsonLines, JsonObject, WireError, WireParser, WireReadable


class AgentError(RuntimeError):
    """The in-process agent failed, timed out or disconnected."""


class _PendingRequest:
    """A request waiting for its reply; ``reply`` stays ``None`` if the agent disconnects first."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.reply: CommandResult | None = None


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
        self._parser = WireParser(
            {AgentMessageType.RESULT: CommandResult.from_wire, AgentMessageType.METRICS: AgentMetrics.from_wire}
        )

    @property
    def hello(self) -> AgentHello:
        return self._hello

    @property
    def alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        threading.Thread(target=self._read_loop, name="pyprof-agent-reader", daemon=True).start()

    def request[R: WireReadable](
        self, request: AgentRequest, reply_type: type[R], timeout: float = DEFAULT_TIMEOUT
    ) -> R:
        """Run a command in the target process and return its result, read as ``reply_type``.

        Raises ``AgentError`` if the agent reports a failure, answers something
        else, does not answer within ``timeout`` seconds or is not connected (any more).
        """
        method = str(request.command)
        if not self._alive:
            raise AgentError("agent is not connected")
        request_id = next(self._ids)
        pending = _PendingRequest()
        self._pending[request_id] = pending
        data = JsonLines.encode(CommandCall(request_id, method, request.to_wire()).to_wire())
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
        if reply.error is not None:
            raise AgentError(reply.error)
        try:
            return reply_type.from_wire(reply.result, "result")
        except WireError as error:
            raise AgentError(f"agent answered {method!r} with something else: {error}") from error

    def close(self) -> None:
        """Ask the agent to stop, then drop the connection."""
        try:
            self.request(Shutdown(), Acknowledgement, self._SHUTDOWN_TIMEOUT)
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

    def _dispatch(self, raw: JsonObject) -> None:
        try:
            match self._parser.parse(raw):
                case CommandResult() as reply:
                    pending = self._pending.get(reply.id)
                    if pending is not None:
                        pending.reply = reply
                        pending.done.set()
                case AgentMetrics() as metrics:
                    self._listener.on_agent_metrics(self, metrics)
        except Exception:  # a bad message must not kill the reader
            traceback.print_exc(file=sys.stderr)
