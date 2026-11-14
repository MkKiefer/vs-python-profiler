"""Turns asyncio's debug output into profiler events."""

import threading
import time
from collections.abc import Callable
from typing import TextIO
lazy import logging
lazy import warnings

from _vscode_pyprof.agent_protocol import EventKind
from _vscode_pyprof.wire import JsonObject


class AsyncioDebugCapture:
    """Collects asyncio debug output (log records and never-awaited warnings) as events.

    ``install`` hooks the ``asyncio`` logger and ``warnings.showwarning``;
    ``remove`` restores both.
    """

    _MESSAGE_LIMIT = 2000
    _HANDLE_LIMIT = 500

    def __init__(self, emit: Callable[[JsonObject], None]) -> None:
        self._emit = emit
        self._handler: logging.Handler | None = None
        self._original_showwarning: Callable[..., None] | None = None

    def install(self) -> None:
        if self._handler is None:
            self._handler = self._create_handler()
        logger = logging.getLogger("asyncio")
        if self._handler not in logger.handlers:
            logger.addHandler(self._handler)
        if self._original_showwarning is None:
            self._original_showwarning = warnings.showwarning
            warnings.showwarning = self._showwarning

    def remove(self) -> None:
        if self._handler is not None:
            logging.getLogger("asyncio").removeHandler(self._handler)
        if self._original_showwarning is not None:
            warnings.showwarning = self._original_showwarning
            self._original_showwarning = None

    def _create_handler(self) -> logging.Handler:
        # The subclass is defined here because `logging` must not load when this module is imported.
        on_log_record = self._on_log_record

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    on_log_record(record)
                except Exception:  # never let profiling break the program's logging
                    return

        return Handler(level=logging.WARNING)

    def _showwarning(
        self,
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: TextIO | None = None,
        line: str | None = None,
    ) -> None:
        try:
            text = str(message)
            if issubclass(category, RuntimeWarning) and "never awaited" in text:
                self._emit(
                    {
                        "t": time.perf_counter(),
                        "kind": EventKind.NEVER_AWAITED,
                        "message": text,
                        "file": filename,
                        "line": lineno,
                    }
                )
        except Exception:  # never let profiling break the program's warnings
            pass
        if self._original_showwarning is not None:
            self._original_showwarning(message, category, filename, lineno, file, line)

    def _on_log_record(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        event: JsonObject = {
            "t": time.perf_counter(),
            "kind": EventKind.ASYNCIO,
            "message": message[: self._MESSAGE_LIMIT],
            "thread": threading.current_thread().name,
        }
        if message.startswith("Executing") and "took" in message:
            event["kind"] = EventKind.SLOW_CALLBACK
            args = record.args
            if isinstance(args, tuple) and len(args) >= 2 and isinstance(args[-1], (int, float)):
                event["seconds"] = float(args[-1])
                event["handle"] = str(args[0])[: self._HANDLE_LIMIT]
        elif "was destroyed but it is pending" in message:
            event["kind"] = EventKind.TASK_DESTROYED_PENDING
        elif "exception was never retrieved" in message:
            event["kind"] = EventKind.EXCEPTION_NEVER_RETRIEVED
        self._emit(event)
