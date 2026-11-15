"""Requests and notifications over stdio between the extension and the collector, one JSON line each.

Extension → collector: ``{"type": "Request", "id": 1, "body": {"type": "Attach", "pid": 42}}``
Collector → extension: ``{"type": "Response", "id": 1, "result": {...}, "error": null}``
                       and notifications such as ``{"type": "StateChanged", "state": "running", ...}``
"""

import json
import sys
import threading
import traceback
from collections.abc import Callable
from typing import BinaryIO

from _vspyprof.wire import Request, Response, WireDecoder, WireEncoder, WireError

type RequestHandler = Callable[[object], object]
"""Runs the body of one request and returns its result."""


class RpcError(Exception):
    """An error the caller is expected to see (reported without a traceback)."""


class RpcServer:
    """Serves requests from ``inp`` and writes responses and notifications to ``out``."""

    def __init__(self, inp: BinaryIO, out: BinaryIO, encoder: WireEncoder, decoder: WireDecoder) -> None:
        """``decoder`` reads what the extension sends (``collector.messages.FROM_EXTENSION``)."""
        self._inp = inp
        self._out = out
        self._encoder = encoder
        self._decoder = decoder
        self._write_lock = threading.Lock()
        self._closed = threading.Event()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def notify(self, notification: object) -> None:
        self._send(notification)

    def serve(self, handler: RequestHandler) -> None:
        """Answer requests with ``handler`` until the input stream closes. Each request runs on its own thread."""
        try:
            for line in self._inp:
                if line.strip():
                    threading.Thread(target=self._answer, args=(line, handler), daemon=True).start()
        finally:
            self._closed.set()

    def _answer(self, line: bytes, handler: RequestHandler) -> None:
        try:
            request = self._decoder.decode(line)
            if not isinstance(request, Request):
                raise WireError(f"expected a Request, got {type(request).__name__}")
        except ValueError as error:  # the extension is broken; answer if the line names a request id
            request_id = self._request_id(line)
            if request_id is not None:
                self._send(Response(request_id, error=str(error)))
            return
        try:
            response = Response(request.id, result=handler(request.body))
        except Exception as error:
            if not isinstance(error, RpcError):  # an RpcError is the caller's mistake
                traceback.print_exc(file=sys.stderr)
            response = Response(request.id, error=str(error) or type(error).__name__)
        self._send(response)

    @staticmethod
    def _request_id(line: bytes) -> int | None:
        try:
            raw = json.loads(line)
        except ValueError:
            return None
        request_id = raw.get("id") if isinstance(raw, dict) else None
        return request_id if isinstance(request_id, int) else None

    def _send(self, message: object) -> None:
        data = self._encoder.encode(message)
        with self._write_lock:
            try:
                self._out.write(data)
                self._out.flush()
            except OSError, ValueError:
                self._closed.set()
