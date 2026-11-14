"""In-memory profile store.

Everything the UI shows is kept in a handful of append-only tables that share
one clock (milliseconds since session start, ``SessionClock``):

* frames   - interned ``[file, func, line, category]``           (``StackTable``)
* stacks   - prefix tree ``[parent_stack, frame]``                (``StackTable``)
* samples  - columnar ``t / tid / stack / status`` (thread stacks) (``SampleColumns``)
* async    - same layout, stacks reconstructed per asyncio task
* tracks   - named time series ``[[t, value], ...]``
* tasks, task_events                                               (``TaskTable``)
* gc, markers, snapshots, events

The store hands out *deltas* (everything appended since the last call) so the
extension can stream live data cheaply, and ``full()`` returns the same shape
for saving ``.pyprof`` files. The TypeScript ``ProfileModel`` consumes both.
"""

import sys
import sysconfig
import threading
import time
from collections.abc import Iterable, Sequence

# annotations only (never evaluated at runtime): the store imports without the private Tachyon module
lazy from _remote_debugging import AwaitedInfo, FrameInfo, InterpreterInfo

from _vscode_pyprof.collector.store.append_log import AppendLog
from _vscode_pyprof.collector.store.memory_snapshot import MemorySnapshot
from _vscode_pyprof.collector.store.sample_columns import SampleColumns
from _vscode_pyprof.collector.store.sampling_stats import SamplingStats
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.stack_table import FrameKey, StackTable
from _vscode_pyprof.collector.store.task_table import TaskObservation, TaskState, TaskTable
from _vscode_pyprof.collector.store.track import Track
from _vscode_pyprof.wire import JsonObject


class Store:
    """Thread-safe facade over the tables of one profile.

    The sampler thread, the agent reader and the RPC handlers all record into
    it; one lock guards every table.
    """

    FORMAT = "pyprof"
    FORMAT_VERSION = 1
    NO_STACK = StackTable.NO_STACK

    def __init__(self, clock: SessionClock, stacks: StackTable) -> None:
        self._clock = clock
        self._stacks = stacks
        self._lock = threading.RLock()

        self._samples = SampleColumns()
        self._async_samples = SampleColumns()
        self._tracks: dict[Track, AppendLog[list[float]]] = {}
        self._gc: AppendLog[list[float]] = AppendLog()
        self._markers: AppendLog[list[float | str]] = AppendLog()
        self._events: AppendLog[JsonObject] = AppendLog()
        self._tasks = TaskTable()
        self._snapshots: AppendLog[MemorySnapshot] = AppendLog()
        self._object_counts: AppendLog[JsonObject] = AppendLog()
        self._threads: dict[int, str] = {}
        self._renamed_threads: set[int] = set()
        self._meta: JsonObject = {
            "python": sys.version.split()[0],
            "implementation": sys.implementation.name,
            "freeThreaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            "platform": sys.platform,
            "startedAt": time.time(),
        }
        self._meta_changed = True
        self._sample_count = 0
        self._error_count = 0
        self._rate_hz = 0.0

    # ---- configuration
    def configure(self, *, strip_launcher: bool) -> None:
        """``strip_launcher`` drops the launcher/runpy bootstrap frames at the root of every stack."""
        with self._lock:
            self._stacks.strip_launcher(strip_launcher)

    def set_meta(self, **values: object) -> None:
        """Add facts about the session (pid, options, argv, …) to the profile's ``meta`` object."""
        with self._lock:
            self._meta.update(values)
            self._meta_changed = True

    # ---- samples
    def add_thread_sample(self, t: float, interpreters: Iterable[InterpreterInfo]) -> None:
        """Record one sampling tick: the current stack of every thread."""
        t = round(t, 3)
        with self._lock:
            for interpreter in interpreters:
                for thread in interpreter.threads:
                    if not thread.frame_info:
                        continue
                    stack, internal = self._stacks.intern_sampled(thread.frame_info, strip=True)
                    if not internal:  # the profiler's own threads are left out
                        self._samples.append(t, thread.thread_id, stack, thread.status)
            self._sample_count += 1

    def add_async_sample(self, t: float, linear_stacks: Iterable[tuple[Sequence[FrameInfo], int, int]]) -> None:
        """Record async-aware stacks: ``(frames leaf first, thread id, leaf task id)`` per leaf task."""
        t = round(t, 3)
        with self._lock:
            for frames, thread_id, _leaf_task in linear_stacks:
                stack, internal = self._stacks.intern_sampled(frames, strip=False)
                if not internal:
                    self._async_samples.append(t, thread_id, stack, 0)

    def record_error(self) -> None:
        """Count a discarded sample (torn read)."""
        with self._lock:
            self._error_count += 1

    def set_sampling_rate(self, rate_hz: float) -> None:
        self._rate_hz = rate_hz

    def stats(self) -> SamplingStats:
        return SamplingStats(self._sample_count, self._error_count, self._rate_hz)

    # ---- time series, markers and events
    def add_track(self, track: Track, t: float, value: float) -> None:
        """Append one point to a time series."""
        with self._lock:
            points = self._tracks.get(track)
            if points is None:
                points = self._tracks[track] = AppendLog()
            points.append([round(t, 2), value])

    def add_gc(self, t: float, duration_ms: float, generation: int, collected: int, heap_size: int) -> None:
        with self._lock:
            self._gc.append([round(t, 3), round(duration_ms, 4), generation, collected, heap_size])

    def add_marker(self, name: str, t: float | None = None) -> None:
        """A named point in time; ``t`` defaults to now."""
        with self._lock:
            self._markers.append([self._rounded_time(t), name])

    def add_event(self, kind: str, message: str, t: float | None = None, extra: JsonObject | None = None) -> None:
        """Something worth showing on the timeline; ``extra`` carries kind-specific fields."""
        with self._lock:
            event: JsonObject = dict(extra) if extra else {}
            event.update(t=self._rounded_time(t), kind=kind, message=message)
            self._events.append(event)

    def set_thread_name(self, thread_id: int, name: str) -> None:
        with self._lock:
            if self._threads.get(thread_id) != name:
                self._threads[thread_id] = name
                self._renamed_threads.add(thread_id)

    # ---- tasks
    def has_tasks(self) -> bool:
        return len(self._tasks) > 0

    def update_tasks(self, t: float, awaited_infos: Iterable[AwaitedInfo], running_ids: set[int]) -> None:
        """Reconcile the task table with the tasks currently alive in the target."""
        with self._lock:
            self._tasks.reconcile(round(t, 2), self._observe_tasks(awaited_infos, running_ids))

    def _observe_tasks(self, awaited_infos: Iterable[AwaitedInfo], running_ids: set[int]) -> list[TaskObservation]:
        observations: list[TaskObservation] = []
        for info in awaited_infos:
            for task in info.awaited_by:
                frames = [frame for coroutine in task.coroutine_stack for frame in coroutine.call_stack]
                # awaited_by names the awaiting task by id (int) when it is known
                awaiter = task.awaited_by[0].task_name if task.awaited_by else None
                observations.append(
                    TaskObservation(
                        task_id=task.task_id,
                        name=task.task_name or f"Task-{task.task_id}",
                        parent=awaiter if isinstance(awaiter, int) else None,
                        thread=info.thread_id,
                        stack=self._stacks.intern_sampled(frames, strip=False)[0] if frames else self.NO_STACK,
                        state=TaskState.RUNNING if task.task_id in running_ids else TaskState.WAITING,
                    )
                )
        return observations

    # ---- memory
    def intern_traceback(self, frames_root_first: Sequence[FrameKey]) -> int:
        """Intern a stack recorded inside the target (tracemalloc), given root-first frames.

        Applies the same launcher stripping as sampled stacks so both kinds of
        stack share prefixes. Returns ``NO_STACK`` if nothing is left.
        """
        with self._lock:
            return self._stacks.intern(frames_root_first, strip=True)

    def add_snapshot(self, snapshot: MemorySnapshot) -> None:
        with self._lock:
            self._snapshots.append(snapshot)

    def add_object_counts(self, t: float, counts: list[object]) -> None:
        """``counts`` is the agent's ``[[type name, count], ...]``, passed through to the dashboard."""
        with self._lock:
            self._object_counts.append({"t": round(t, 2), "counts": counts})

    # ---- reading
    def delta(self) -> JsonObject:
        """Everything recorded since the previous ``delta()`` call."""
        with self._lock:
            data = self._tables(new_only=True)
            data["threads"] = {str(thread_id): self._threads[thread_id] for thread_id in self._renamed_threads}
            data["objectCounts"] = self._object_counts.rows(new_only=True)[-1:]  # only the latest is shown live
            if self._meta_changed:
                data["meta"] = dict(self._meta)
            self._renamed_threads.clear()
            self._meta_changed = False
            return data

    def full(self) -> JsonObject:
        """The whole profile in delta shape (the ``.pyprof`` file content)."""
        with self._lock:
            data = self._tables(new_only=False)
            data["threads"] = {str(thread_id): name for thread_id, name in self._threads.items()}
            data["objectCounts"] = self._object_counts.rows(new_only=False)
            data["meta"] = dict(self._meta)
            data["format"] = self.FORMAT
            data["version"] = self.FORMAT_VERSION
            return data

    def _tables(self, *, new_only: bool) -> JsonObject:
        tracks: JsonObject = {}
        for track, log in self._tracks.items():
            points = log.rows(new_only=new_only)
            if points:
                tracks[track] = points
        return {
            "now": round(self._clock.now(), 2),
            "frames": self._stacks.frames.rows(new_only=new_only),
            "stacks": self._stacks.stacks.rows(new_only=new_only),
            "samples": self._samples.to_wire(new_only=new_only),
            "asyncSamples": self._async_samples.to_wire(new_only=new_only),
            "tracks": tracks,
            "gc": self._gc.rows(new_only=new_only),
            "markers": self._markers.rows(new_only=new_only),
            "events": self._events.rows(new_only=new_only),
            "tasks": [task.to_wire() for task in self._tasks.records(new_only=new_only)],
            "taskEvents": self._tasks.events.rows(new_only=new_only),
            "snapshots": [snapshot.to_wire() for snapshot in self._snapshots.rows(new_only=new_only)],
            "stats": self.stats().to_wire(),
        }

    def _rounded_time(self, t: float | None) -> float:
        return round(self._clock.now() if t is None else t, 2)
