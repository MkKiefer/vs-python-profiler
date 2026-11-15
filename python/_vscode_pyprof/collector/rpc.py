"""Newline-delimited JSON-RPC over stdio between the extension and collector.

Request:      {"id": 1, "method": "attach", "params": {...}}
Response:     {"id": 1, "result": {...}}  |  {"id": 1, "error": {"message": ...}}
Notification: {"method": "delta", "params": {...}}            (no id)
"""

import json
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO

from _vscode_pyprof.wire import JsonLines, JsonObject, WireError, WireMessage

type _Handler = Callable[[JsonObject], WireMessage]
"""Reads the ``params`` of a request and returns its result."""


@dataclass(frozen=True, slots=True)
class RpcRequest(WireMessage):
    """A request or notification; ``params`` is read by the handler of ``method``."""

    method: str
    id: object = None
    """Any JSON value; ``None`` for a notification, which gets no response."""
    params: JsonObject = field(default_factory=dict)


class RpcError(Exception):
    """An error the caller is expected to see (reported without a traceback)."""


class RpcServer:
    """Serves requests from ``inp`` and writes responses/notifications to ``out``."""

    def __init__(self, inp: BinaryIO, out: BinaryIO) -> None:
        self._inp = inp
        self._out = out
        self._write_lock = threading.Lock()
        self._handlers: dict[str, _Handler] = {}
        self._closed = threading.Event()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def register[P: WireMessage](self, method: str, params_type: type[P], handler: Callable[[P], WireMessage]) -> None:
        """Serve ``method`` with ``handler``, which gets the request's ``params`` read as ``params_type``."""
        self._handlers[method] = lambda params: handler(params_type.from_wire(params, "params"))

    def notify(self, method: str, params: JsonObject) -> None:
        self._send({"method": method, "params": params})

    def serve(self) -> None:
        """Dispatch requests until the input stream closes. Each request runs on its own thread."""
        try:
            for raw in self._inp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    threading.Thread(target=self.handle, args=(message,), daemon=True).start()
        finally:
            self._closed.set()

    def handle(self, message: JsonObject) -> None:
        """Run one request and write its response (notifications get none)."""
        request_id = message.get("id")  # read first: a malformed request still gets its error response
        try:
            request = RpcRequest.from_wire(message)
            handler = self._handlers.get(request.method)
            if handler is None:
                raise RpcError(f"unknown method {request.method!r}")
            result = handler(request.params).to_wire()
        except Exception as error:
            if not isinstance(error, (RpcError, WireError)):  # those are the caller's mistakes
                traceback.print_exc(file=sys.stderr)
            if request_id is not None:
                detail: JsonObject = {"message": str(error) or type(error).__name__, "type": type(error).__name__}
                self._send({"id": request_id, "error": detail})
            return
        if request_id is not None:
            self._send({"id": request_id, "result": result})

    def _send(self, message: JsonObject) -> None:
        data = JsonLines.encode(message, fallback=str)
        with self._write_lock:
            try:
                self._out.write(data)
                self._out.flush()
            except OSError, ValueError:
                self._closed.set()
