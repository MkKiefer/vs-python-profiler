"""Turns asyncio's debug output into profiler events."""

import threading
import time
from collections.abc import Callable
from typing import TextIO
lazy import logging
lazy import warnings

from _vspyprof.agent_protocol.metrics import AgentEvent, EventDetails
from _vspyprof.agent_protocol.names import EventKind


class AsyncioDebugCapture:
    """Collects asyncio debug output (log records and never-awaited warnings) as events.

    ``install`` hooks the ``asyncio`` logger and ``warnings.showwarning``;
    ``remove`` restores both.
    """

    _MESSAGE_LIMIT = 2000
    _HANDLE_LIMIT = 500

    def __init__(self, emit: Callable[[AgentEvent], None]) -> None:
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
                    pass

            def handle(self, record: logging.LogRecord) -> bool:
                handled = super().handle(record)
                AsyncioDebugCapture._show_like_without_us(self, record)
                return handled

        return Handler(level=logging.WARNING)

    @staticmethod
    def _show_like_without_us(ours: logging.Handler, record: logging.LogRecord) -> None:
        """Print ``record`` the way logging would if our handler were not installed.

        A logger without any handler prints records of WARNING and above to stderr
        (``logging.lastResort``). Our handler counts as one, so when it is the only
        handler the record reaches, logging stays silent; we print it instead.
        """
        logger: logging.Logger | None = logging.getLogger(record.name)
        while logger is not None:
            if any(handler is not ours for handler in logger.handlers):
                return
            if not logger.propagate:
                break
            logger = logger.parent
        last_resort = logging.lastResort
        if last_resort is not None and record.levelno >= last_resort.level:
            last_resort.handle(record)

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
                details = EventDetails(file=filename, line=lineno)
                self._emit(AgentEvent(EventKind.NEVER_AWAITED, text, time.perf_counter(), details))
        except Exception:  # never let profiling break the program's warnings
            pass
        if self._original_showwarning is not None:
            self._original_showwarning(message, category, filename, lineno, file, line)

    def _on_log_record(self, record: logging.LogRecord) -> None:
        happened = time.perf_counter()
        message = record.getMessage()
        kind = EventKind.ASYNCIO
        seconds: float | None = None
        handle: str | None = None
        if message.startswith("Executing") and "took" in message:
            kind = EventKind.SLOW_CALLBACK
            args = record.args  # asyncio logs ("Executing %s took %.3f seconds", handle, seconds)
            if isinstance(args, tuple) and len(args) >= 2 and isinstance(args[-1], (int, float)):
                seconds = float(args[-1])
                handle = str(args[0])[: self._HANDLE_LIMIT]
        elif "was destroyed but it is pending" in message:
            kind = EventKind.TASK_DESTROYED_PENDING
        elif "exception was never retrieved" in message:
            kind = EventKind.EXCEPTION_NEVER_RETRIEVED
        details = EventDetails(thread=threading.current_thread().name, seconds=seconds, handle=handle)
        self._emit(AgentEvent(kind, message[: self._MESSAGE_LIMIT], happened, details))
