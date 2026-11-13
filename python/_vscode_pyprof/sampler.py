"""The sampling loop: reads the target's stacks at a fixed rate and feeds the store."""

import threading
import time
from abc import ABC, abstractmethod

from _vscode_pyprof.options import CollectorOptions
from _vscode_pyprof.procstats import ProcessStatsReader
from _vscode_pyprof.store import Store
from _vscode_pyprof.tachyon import Tachyon


class SamplerListener(ABC):
    """Receives what the sampler notices about the target process."""

    @abstractmethod
    def on_target_exit(self, reason: str) -> None: ...

    @abstractmethod
    def on_children(self, pids: list[int]) -> None: ...


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


class Sampler:
    """Samples one target process on its own thread until stopped or the target exits."""

    _RESYNC_AFTER = 0.5  # seconds behind schedule before we skip instead of catching up
    _ASYNC_STACKS_HZ = 200  # async-aware stacks are costlier: cap their rate
    _GC_SEEN_LIMIT = 10_000

    def __init__(
        self,
        tachyon: Tachyon,
        store: Store,
        stats_reader: ProcessStatsReader,
        options: CollectorOptions,
        listener: SamplerListener,
    ) -> None:
        self._tachyon = tachyon
        self._store = store
        self._stats_reader = stats_reader
        self._listener = listener
        self._interval = 1.0 / options.rate_hz
        self._blocking = options.blocking and tachyon.supports_blocking()
        self._async_aware = options.async_aware
        self._async_stacks = options.async_aware and tachyon.supports_async_stacks()
        self._async_every = max(1, options.rate_hz // self._ASYNC_STACKS_HZ)

        self._thread = threading.Thread(target=self._run, name="pyprof-sampler", daemon=True)
        self._stop = threading.Event()
        self._ticks = 0
        self._known_children: set[int] = set()
        self._gc_seen: dict[tuple[int, int, int], None] = {}  # insertion ordered, oldest first
        self._last_cpu: tuple[float, float] | None = None
        self._rate_window = (0, time.perf_counter())
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

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        exit_reason: str | None = None
        next_tick = time.perf_counter()
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if now < next_tick:
                    delay = next_tick - now
                    if delay > 0.0002:
                        time.sleep(delay * 0.9)
                    continue
                next_tick += self._interval
                if now - next_tick > self._RESYNC_AFTER:  # suspend, long GC pause…
                    next_tick = now + self._interval
                t = self._store.to_session_ms(now)
                if not self._sample(t):
                    exit_reason = "exited"
                    break
                self._run_periodic_jobs(now, t)
        finally:
            self._stats_reader.close()
            if exit_reason is not None:
                self._listener.on_target_exit(exit_reason)

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
        if self._gc_job.due(now):
            self._sample_gc(t)
        if self._children_job.due(now):
            children = self._tachyon.python_children(self._known_children)
            if children:
                self._listener.on_children(children)

    # ----------------------------------------------------------- async/tasks
    def _sample_async_stacks(self, t: float) -> None:
        try:
            running = self._tachyon.running_tasks()
            if running:
                self._store.add_async_sample(t, list(self._tachyon.linearise(running)))
        except ProcessLookupError:
            raise
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

    # ---------------------------------------------------------- process stats
    def _sample_process_stats(self, now: float, t: float) -> None:
        stats = self._stats_reader.read()
        if stats is not None:
            self._store.add_track("rss", t, stats.rss_bytes)
            if self._last_cpu is not None and now > self._last_cpu[0]:
                percent = 100.0 * (stats.cpu_seconds - self._last_cpu[1]) / (now - self._last_cpu[0])
                self._store.add_track("cpu", t, round(max(0.0, percent), 1))
            self._last_cpu = (now, stats.cpu_seconds)
        ticks_before, time_before = self._rate_window
        if now > time_before:
            self._store.set_sampling_rate(round((self._ticks - ticks_before) / (now - time_before), 1))
        self._rate_window = (self._ticks, now)

    # -------------------------------------------------------------------- gc
    def _sample_gc(self, t: float) -> None:
        try:
            collections = self._tachyon.gc_stats()
        except Tachyon.READ_ERRORS:
            return
        now_ns = time.perf_counter_ns()
        for gc in collections:
            key = (gc.gen, gc.ts_start, gc.collections)
            if key in self._gc_seen:
                continue
            self._gc_seen[key] = None
            started = self._store.ns_to_session_ms(gc.ts_start)
            # ts_start is CLOCK_MONOTONIC on Linux; if the clocks differ, use the arrival time
            if gc.ts_start <= 0 or gc.ts_start > now_ns + 60e9 or started < -1000:
                started = t
            if started < 0:
                continue  # collected before the session started
            duration_ms = (gc.ts_stop - gc.ts_start) / 1e6 if gc.ts_stop >= gc.ts_start else 0.0
            self._store.add_gc(started, duration_ms, gc.gen, gc.collected, gc.heap_size)
        while len(self._gc_seen) > self._GC_SEEN_LIMIT:
            del self._gc_seen[next(iter(self._gc_seen))]


class SamplerFactory:
    """Builds a sampler attached to a process (the seam tests replace)."""

    def create(self, pid: int, store: Store, options: CollectorOptions, listener: SamplerListener) -> Sampler:
        """Attach to ``pid``. Raises ``TachyonError`` if the process cannot be read."""
        tachyon = Tachyon(pid, native=options.native, gc=options.gc)
        return Sampler(tachyon, store, ProcessStatsReader.for_pid(tachyon.pid), options, listener)
