"""Newline-delimited JSON-RPC over stdio between the extension and collector.

Request:      {"id": 1, "method": "attach", "params": {...}}
Response:     {"id": 1, "result": {...}}  |  {"id": 1, "error": {"message": ...}}
Notification: {"method": "delta", "params": {...}}            (no id)
"""

from __future__ import annotations

import json
import sys
import threading
import traceback


class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, inp, out):
        self._inp = inp
        self._out = out
        self._lock = threading.Lock()
        self.handlers: dict = {}
        self.closed = threading.Event()

    def notify(self, method: str, params) -> None:
        self._send({"method": method, "params": params})

    def _send(self, msg) -> None:
        data = (json.dumps(msg, separators=(",", ":"), default=str) + "\n").encode("utf-8")
        with self._lock:
            try:
                self._out.write(data)
                self._out.flush()
            except (OSError, ValueError):
                self.closed.set()

    def serve(self) -> None:
        try:
            for raw in self._inp:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                threading.Thread(target=self._handle, args=(msg,), daemon=True).start()
        finally:
            self.closed.set()

    def _handle(self, msg) -> None:
        mid = msg.get("id")
        fn = self.handlers.get(msg.get("method"))
        try:
            if fn is None:
                raise RpcError(f"unknown method {msg.get('method')!r}")
            result = fn(msg.get("params") or {})
            if mid is not None:
                self._send({"id": mid, "result": result})
        except Exception as e:
            if not isinstance(e, RpcError):
                traceback.print_exc(file=sys.stderr)
            if mid is not None:
                self._send({"id": mid, "error": {"message": str(e) or type(e).__name__,
                                                 "type": type(e).__name__}})
