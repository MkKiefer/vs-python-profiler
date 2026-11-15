"""The collector's end of the connection to one in-process agent."""

import itertools
import socket
import sys
import threading
import traceback

from _vspyprof.agent_protocol.commands import Shutdown
from _vspyprof.agent_protocol.hello import AgentHello
from _vspyprof.agent_protocol.metrics import AgentMetrics
from _vspyprof.collector.agent.listener import AgentListener
from _vspyprof.wire import LineBuffer, Request, Response, WireDecoder, WireEncoder


class AgentError(RuntimeError):
    """The in-process agent failed, timed out or disconnected."""


class _PendingRequest:
    """A request waiting for its response; ``response`` stays ``None`` if the agent disconnects first."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.response: Response | None = None


class AgentConnection:
    """One authenticated agent: request/response plus unsolicited metrics."""

    DEFAULT_TIMEOUT = 60.0
    _SHUTDOWN_TIMEOUT = 2.0
    _RECEIVE_SIZE = 1 << 20

    def __init__(
        self,
        sock: socket.socket,
        hello: AgentHello,
        listener: AgentListener,
        lines: LineBuffer,
        encoder: WireEncoder,
        decoder: WireDecoder,
    ) -> None:
        """``lines`` may already hold what the agent sent right after its hello."""
        self._sock = sock
        self._hello = hello
        self._listener = listener
        self._lines = lines
        self._encoder = encoder
        self._decoder = decoder
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
        threading.Thread(target=self._read_loop, name="vspyprof-agent-reader", daemon=True).start()

    def request[R](self, command: object, reply_type: type[R], timeout: float = DEFAULT_TIMEOUT) -> R:
        """Run a command in the target process and return its result, which must be a ``reply_type``.

        Raises ``AgentError`` if the agent reports a failure, answers something
        else, does not answer within ``timeout`` seconds or is not connected (any more).
        """
        name = type(command).__name__
        request_id = next(self._ids)
        pending = _PendingRequest()
        # register before checking: a reader that ends after the check still finds and wakes this request
        self._pending[request_id] = pending
        if not self._alive:
            self._pending.pop(request_id, None)
            raise AgentError("agent is not connected")
        try:
            with self._write_lock:
                self._sock.sendall(self._encoder.encode(Request(request_id, command)))
            if not pending.done.wait(timeout):
                raise AgentError(f"agent did not answer {name} within {timeout:.0f}s")
        except OSError as error:
            raise AgentError(f"agent connection lost: {error}") from error
        finally:
            self._pending.pop(request_id, None)
        response = pending.response
        if response is None:
            raise AgentError("agent disconnected")
        if response.error is not None:
            raise AgentError(response.error)
        if not isinstance(response.result, reply_type):
            raise AgentError(f"agent answered {name} with {type(response.result).__name__}")
        return response.result

    def close(self) -> None:
        """Ask the agent to stop, then drop the connection."""
        try:
            self.request(Shutdown(), type(None), self._SHUTDOWN_TIMEOUT)
        except AgentError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def _read_loop(self) -> None:
        try:
            while True:
                while (line := self._lines.next_line()) is not None:
                    self._dispatch(line)
                chunk = self._sock.recv(self._RECEIVE_SIZE)
                if not chunk:
                    break
                self._lines.feed(chunk)
        except OSError:
            pass  # the connection was closed
        finally:
            self._alive = False
            for pending in list(self._pending.values()):
                pending.done.set()  # response stays None: "agent disconnected"
            self._listener.on_agent_close(self)

    def _dispatch(self, line: bytes) -> None:
        try:
            match self._decoder.decode(line):
                case Response() as response:
                    pending = self._pending.get(response.id)
                    if pending is not None:
                        pending.response = response
                        pending.done.set()
                case AgentMetrics() as metrics:
                    self._listener.on_agent_metrics(self, metrics)
                case other:
                    raise ValueError(f"unexpected message from the agent: {type(other).__name__}")
        except Exception:  # a bad message must not kill the reader
            traceback.print_exc(file=sys.stderr)
