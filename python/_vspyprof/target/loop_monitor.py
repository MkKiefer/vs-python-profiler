"""Watches the event loops of the profiled program."""

import sys
import threading
import time
from types import FrameType
lazy import asyncio

from _vspyprof.agent_protocol.metrics import LoopMetrics
from _vspyprof.target.asyncio_debug import AsyncioDebugCapture


class _LoopProbe:
    """Lag measurement state of one running event loop.

    Not a dataclass: ``@dataclass`` evaluates the field annotations when the
    module is imported, which would load ``asyncio`` into the program.
    """

    __slots__ = ("loop", "max_lag_ms", "pending_since", "thread_name")

    def __init__(self, loop: asyncio.AbstractEventLoop, thread_name: str) -> None:
        self.loop = loop
        self.thread_name = thread_name
        self.pending_since: float | None = None
        """When a probe was scheduled that the loop has not run yet."""
        self.max_lag_ms = 0.0


class LoopMonitor:
    """Finds running event loops, measures how long callbacks wait and switches asyncio debug mode.

    ``asyncio`` is only touched once the program itself has imported it. Every
    method runs on the agent thread, except the probe callback, which the
    probed event loop runs.
    """

    _SCAN_INTERVAL = 2.0
    _LOOP_FUNCTIONS = frozenset({"run_forever", "_run_once"})

    def __init__(self, debug_capture: AsyncioDebugCapture) -> None:
        self._debug_capture = debug_capture
        self._probes: dict[int, _LoopProbe] = {}
        self._last_scan = 0.0
        self._debug = False
        self._slow_callback_ms = 100.0

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def loop_count(self) -> int:
        return len(self._probes)

    def probe(self, now: float) -> None:
        """Schedule a lag probe on every running loop that has answered its previous one."""
        if "asyncio" not in sys.modules:
            return  # the program does not use asyncio (yet)
        if now - self._last_scan > self._SCAN_INTERVAL:
            self._last_scan = now
            self._scan()
        for key, probe in list(self._probes.items()):
            if probe.loop.is_closed() or not probe.loop.is_running():
                self._probes.pop(key, None)
                continue
            if probe.pending_since is not None:
                continue  # previous probe not yet executed: loop is blocked
            probe.pending_since = now
            try:
                probe.loop.call_soon_threadsafe(self._probe_done, key, now)
            except RuntimeError:
                self._probes.pop(key, None)

    def take_metrics(self, now: float) -> list[LoopMetrics]:
        """Worst lag and task count of every loop since the previous call."""
        metrics: list[LoopMetrics] = []
        for key, probe in list(self._probes.items()):
            lag = probe.max_lag_ms
            if probe.pending_since is not None:  # still waiting: the loop is blocked right now
                lag = max(lag, (now - probe.pending_since) * 1000.0)
            metrics.append(LoopMetrics(key, probe.thread_name, round(lag, 3), self._task_count(probe.loop)))
            probe.max_lag_ms = 0.0
        return metrics

    def set_debug(self, enabled: bool, slow_callback_ms: float | None = None) -> None:
        """Switch asyncio debug mode on every loop; ``slow_callback_ms`` is what counts as slow."""
        if slow_callback_ms is not None:
            self._slow_callback_ms = slow_callback_ms
        if enabled == self._debug:
            return
        self._debug = enabled
        if "asyncio" in sys.modules:
            self._scan()
        for probe in list(self._probes.values()):
            self._apply_debug(probe.loop)
        if enabled:
            self._debug_capture.install()
        else:
            self._debug_capture.remove()

    def _probe_done(self, key: int, sent: float) -> None:
        """Runs on the event loop: the time since ``sent`` is how long a callback had to wait."""
        probe = self._probes.get(key)
        if probe is None:
            return
        probe.max_lag_ms = max(probe.max_lag_ms, (time.perf_counter() - sent) * 1000.0)
        probe.pending_since = None

    def _scan(self) -> None:
        """Find running event loops by walking the frames of every thread."""
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        for ident, top_frame in sys._current_frames().items():
            loop = self._loop_running_in(top_frame)
            if loop is not None and id(loop) not in self._probes:
                self._probes[id(loop)] = _LoopProbe(loop, names.get(ident, str(ident)))
                if self._debug:
                    self._apply_debug(loop)

    @classmethod
    def _loop_running_in(cls, top_frame: FrameType) -> asyncio.AbstractEventLoop | None:
        frame: FrameType | None = top_frame
        while frame is not None:
            if frame.f_code.co_name in cls._LOOP_FUNCTIONS:
                loop = frame.f_locals.get("self")
                if isinstance(loop, asyncio.AbstractEventLoop):
                    return loop
            frame = frame.f_back
        return None

    def _apply_debug(self, loop: asyncio.AbstractEventLoop) -> None:
        enabled = self._debug
        slow_callback_seconds = self._slow_callback_ms / 1000.0

        def apply() -> None:
            loop.set_debug(enabled)
            loop.slow_callback_duration = slow_callback_seconds

        try:
            loop.call_soon_threadsafe(apply)
        except RuntimeError:
            pass  # loop closed in the meantime

    @staticmethod
    def _task_count(loop: asyncio.AbstractEventLoop) -> int | None:
        try:
            return len(asyncio.all_tasks(loop))
        except RuntimeError:  # task set changed while iterating
            return None
