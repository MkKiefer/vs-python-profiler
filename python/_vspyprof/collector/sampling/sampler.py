"""The sampling loop."""

import threading
import time
from dataclasses import dataclass

from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.protocol import StopReason
from _vspyprof.collector.sampling.gc_recorder import GcRecorder
from _vspyprof.collector.sampling.process_stats import ProcessStatsReader
from _vspyprof.collector.sampling.sampler_listener import SamplerListener
from _vspyprof.collector.sampling.tachyon import Tachyon
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.store import Store
from _vspyprof.collector.store.track import Track


class _Periodic:
    """Tells whether a low-frequency job is due."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._last = 0.0

    def due(self, now: float) -> bool:
        if now - self._last < self._seconds:
            return False
        self._last = now
        return True


@dataclass(frozen=True, slots=True)
class _CpuReading:
    at: float
    cpu_seconds: float
    """CPU time the target had used at that moment."""


@dataclass(frozen=True, slots=True)
class _TickReading:
    at: float
    ticks: int
    """Samples taken up to that moment."""


class Sampler:
    """Samples one target process on its own thread until stopped or the target exits.

    Every tick reads the stack of every thread. At lower rates it also records
    async-aware stacks, the asyncio task table, RSS and CPU usage, garbage
    collections and newly started child processes.
    """

    _RESYNC_AFTER = 0.5  # seconds behind schedule before we skip instead of catching up
    _MIN_SLEEP = 0.0002  # shorter waits spin: sleep() is not that precise
    _ASYNC_STACKS_HZ = 200  # async-aware stacks are costlier: cap their rate

    def __init__(
        self,
        tachyon: Tachyon,
        store: Store,
        clock: SessionClock,
        stats_reader: ProcessStatsReader,
        gc_recorder: GcRecorder,
        options: CollectorOptions,
        listener: SamplerListener,
    ) -> None:
        self._tachyon = tachyon
        self._store = store
        self._clock = clock
        self._stats_reader = stats_reader
        self._gc_recorder = gc_recorder
        self._listener = listener
        self._interval = 1.0 / options.rate_hz
        self._blocking = options.blocking and tachyon.supports_blocking()
        self._async_aware = options.async_aware
        self._async_stacks = options.async_aware and tachyon.supports_async_stacks()
        self._async_every = max(1, options.rate_hz // self._ASYNC_STACKS_HZ)

        self._thread = threading.Thread(target=self._run, name="vspyprof-sampler", daemon=True)
        self._stop = threading.Event()
        self._ticks = 0
        self._known_children: set[int] = set()
        self._last_cpu: _CpuReading | None = None
        self._last_ticks = _TickReading(time.perf_counter(), 0)
        self._tasks_job = _Periodic(0.2)
        self._stats_job = _Periodic(0.5)
        self._gc_job = _Periodic(1.0)
        self._children_job = _Periodic(2.0)

    @property
    def pid(self) -> int:
        return self._tachyon.pid

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop sampling and wait for the loop to finish (safe to call from the sampler thread)."""
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        target_exited = False
        next_tick = time.perf_counter()
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if now < next_tick:
                    delay = next_tick - now
                    if delay > self._MIN_SLEEP:
                        time.sleep(delay * 0.9)
                    continue
                next_tick += self._interval
                if now - next_tick > self._RESYNC_AFTER:  # suspend, long GC pause…
                    next_tick = now + self._interval
                t = self._clock.from_perf_counter(now)
                if not self._sample(t):
                    target_exited = True
                    break
                self._run_periodic_jobs(now, t)
        finally:
            self._stats_reader.close()
            if target_exited:
                self._listener.on_target_exit(StopReason.EXITED)

    def _sample(self, t: float) -> bool:
        """Take one sample. Returns ``False`` once the target is gone."""
        try:
            self._store.add_thread_sample(t, self._tachyon.sample_threads(blocking=self._blocking))
            self._ticks += 1
            if self._async_stacks and self._ticks % self._async_every == 0:
                self._sample_async_stacks(t)
        except ProcessLookupError:
            return False
        except Tachyon.READ_ERRORS:
            # torn read of a stack that changed while we read it: discard
            # (same as Tachyon's "error rate"; blocking mode avoids it)
            self._store.record_error()
            return self._tachyon.is_alive()
        return True

    def _run_periodic_jobs(self, now: float, t: float) -> None:
        if self._async_aware and self._tasks_job.due(now):
            self._sample_tasks(t)
        if self._stats_job.due(now):
            self._sample_process_stats(now, t)
            self._measure_sampling_rate(now)
        if self._gc_job.due(now):
            self._gc_recorder.record(t)
        if self._children_job.due(now):
            children = self._tachyon.python_children(self._known_children)
            if children:
                self._listener.on_children(children)

    def _sample_async_stacks(self, t: float) -> None:
        try:
            running = self._tachyon.running_tasks()
            if running:
                self._store.add_async_sample(t, self._tachyon.linearise(running))
        except ProcessLookupError:
            raise  # the target is gone: `_sample` ends the loop
        except Tachyon.READ_ERRORS:
            return

    def _sample_tasks(self, t: float) -> None:
        try:
            all_tasks = self._tachyon.all_tasks()
        except Tachyon.READ_ERRORS:
            return
        if not self._store.has_tasks() and not any(info.awaited_by for info in all_tasks):
            return  # not an asyncio program (yet)
        running: set[int] = set()
        try:
            for info in self._tachyon.running_tasks():
                if info.awaited_by:
                    running.add(info.awaited_by[0].task_id)
        except Tachyon.READ_ERRORS:
            pass  # states fall back to "waiting" for this tick
        self._store.update_tasks(t, all_tasks, running)

    def _sample_process_stats(self, now: float, t: float) -> None:
        stats = self._stats_reader.read()
        if stats is None:
            return
        self._store.add_track(Track.RSS, t, stats.rss_bytes)
        previous = self._last_cpu
        if previous is not None and now > previous.at:
            percent = 100.0 * (stats.cpu_seconds - previous.cpu_seconds) / (now - previous.at)
            self._store.add_track(Track.CPU, t, round(max(0.0, percent), 1))
        self._last_cpu = _CpuReading(now, stats.cpu_seconds)

    def _measure_sampling_rate(self, now: float) -> None:
        """The rate actually achieved since the previous measurement (the target may be too slow to read)."""
        previous = self._last_ticks
        if now > previous.at:
            self._store.set_sampling_rate(round((self._ticks - previous.ticks) / (now - previous.at), 1))
        self._last_ticks = _TickReading(now, self._ticks)
