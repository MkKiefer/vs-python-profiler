"""In-memory profile store.

Everything the UI shows is kept in a handful of append-only tables that share
one clock (milliseconds since session start):

* frames   - interned ``[file, func, line, category]``
* stacks   - prefix tree ``[parent_stack, frame]`` (parent -1 = root)
* samples  - columnar ``t / tid / stack / status`` (thread stacks)
* async    - same layout, stacks reconstructed per asyncio task
* tracks   - named time series ``[[t, value], ...]``
* gc, markers, tasks, task_events, snapshots, events

The store hands out *deltas* (everything appended since the last call) so the
extension can stream live data cheaply, and ``full()`` returns the same shape
for saving ``.pyprof`` files. The TypeScript ``ProfileModel`` consumes both.
"""

import sys
import sysconfig
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from _vscode_pyprof.collector.frames import FrameClassifier
from _vscode_pyprof.wire import JsonObject

if TYPE_CHECKING:  # annotations only: keeps the store importable without the private Tachyon module
    from _remote_debugging import AwaitedInfo, FrameInfo, InterpreterInfo

type FrameKey = tuple[str, str, int]
"""``(filename, function, line)``"""


@dataclass(slots=True)
class _Cursor:
    """How much of each append-only table has already been handed out as a delta."""

    frames: int = 0
    stacks: int = 0
    samples: int = 0
    async_samples: int = 0
    gc: int = 0
    markers: int = 0
    events: int = 0
    task_events: int = 0
    tracks: dict[str, int] = field(default_factory=dict)


class Store:
    FORMAT = "pyprof"
    FORMAT_VERSION = 1
    NO_STACK = -1
    _RAW_CACHE_LIMIT = 200_000

    def __init__(self, classifier: FrameClassifier) -> None:
        self._classifier = classifier
        self._lock = threading.RLock()
        self._t0 = time.perf_counter()
        self._t0_ns = time.perf_counter_ns()
        self._strip_launcher = False

        self._frames: list[list[object]] = []
        self._frame_ids: dict[FrameKey, int] = {}
        self._stacks: list[list[int]] = []
        self._stack_ids: dict[tuple[int, int], int] = {}
        self._stack_internal: list[bool] = []
        self._raw_cache: dict[tuple[FrameInfo, ...], tuple[int, bool]] = {}

        self._samples = SampleColumns()
        self._async_samples = SampleColumns()
        self._tracks: dict[str, list[list[float]]] = {}
        self._gc: list[list[float]] = []
        self._markers: list[list[object]] = []
        self._events: list[JsonObject] = []
        self._threads: dict[int, str] = {}
        self._tasks: dict[int, TaskRecord] = {}
        self._task_events: list[list[object]] = []
        self._snapshots: dict[int, MemorySnapshot] = {}
        self._object_counts: list[JsonObject] = []
        self._meta: JsonObject = {
            "python": sys.version.split()[0],
            "implementation": sys.implementation.name,
            "freeThreaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            "platform": sys.platform,
            "startedAt": time.time(),
        }
        self._sample_count = 0
        self._error_count = 0
        self._rate_hz = 0.0

        self._cursor = _Cursor()
        self._dirty_tasks: set[int] = set()
        self._dirty_threads: set[int] = set()
        self._new_snapshots: list[int] = []
        self._new_object_counts = False
        self._meta_dirty = True

    # ------------------------------------------------------------------ time
    def now(self) -> float:
        """Milliseconds since the session started."""
        return (time.perf_counter() - self._t0) * 1000.0

    def to_session_ms(self, perf_counter_seconds: float) -> float:
        """Convert a ``time.perf_counter()`` reading into session milliseconds."""
        return (perf_counter_seconds - self._t0) * 1000.0

    def ns_to_session_ms(self, perf_counter_ns: int) -> float:
        return (perf_counter_ns - self._t0_ns) / 1e6

    # --------------------------------------------------------- configuration
    def configure(self, *, strip_launcher: bool) -> None:
        """``strip_launcher`` drops the launcher/runpy bootstrap frames at the root of every stack."""
        self._strip_launcher = strip_launcher

    def set_meta(self, **values: object) -> None:
        with self._lock:
            self._meta.update(values)
            self._meta_dirty = True

    # -------------------------------------------------------------- interning
    def intern_path(self, frames_root_first: Sequence[FrameKey]) -> int:
        """Intern a stack given root-first frames; returns ``NO_STACK`` for an empty one."""
        with self._lock:
            return self._intern_path(frames_root_first)[0]

    def intern_traceback(self, frames_root_first: Sequence[FrameKey]) -> int:
        """Like ``intern_path`` for stacks recorded inside the target (tracemalloc).

        Applies the same launcher stripping as sampled stacks so both kinds of
        stack share prefixes. Returns ``NO_STACK`` if nothing is left.
        """
        frames = self._without_launcher_prefix(frames_root_first)
        with self._lock:
            return self._intern_path(frames)[0]

    def _intern_path(self, frames_root_first: Sequence[FrameKey]) -> tuple[int, bool]:
        parent = self.NO_STACK
        internal = not frames_root_first
        for key in frames_root_first:
            frame_id = self._frame_ids.get(key)
            if frame_id is None:
                frame_id = len(self._frames)
                self._frames.append([key[0], key[1], key[2], int(self._classifier.category(key[0]))])
                self._frame_ids[key] = frame_id
            stack_key = (parent, frame_id)
            stack_id = self._stack_ids.get(stack_key)
            if stack_id is None:
                stack_id = len(self._stacks)
                self._stacks.append([parent, frame_id])
                internal = internal or self._classifier.is_internal(key[0])
                self._stack_internal.append(internal)
                self._stack_ids[stack_key] = stack_id
            else:
                internal = self._stack_internal[stack_id]
            parent = stack_id
        return parent, internal

    def _without_launcher_prefix(self, frames_root_first: Sequence[FrameKey]) -> Sequence[FrameKey]:
        if not self._strip_launcher:
            return frames_root_first
        skip = self._classifier.launcher_prefix_length(key[0] for key in frames_root_first)
        return frames_root_first[skip:] if skip else frames_root_first

    def _stack_for_frames(self, leaf_first: Sequence[FrameInfo], *, strip: bool) -> tuple[int, bool]:
        """Intern Tachyon frames (leaf first); cached on the raw tuple. Returns ``(stack, internal)``."""
        raw = tuple(leaf_first)
        hit = self._raw_cache.get(raw)
        if hit is not None:
            return hit
        keys = [self._frame_key(frame) for frame in reversed(raw)]
        result = self._intern_path(self._without_launcher_prefix(keys) if strip else keys)
        if len(self._raw_cache) > self._RAW_CACHE_LIMIT:
            self._raw_cache.clear()
        self._raw_cache[raw] = result
        return result

    @staticmethod
    def _frame_key(frame: FrameInfo) -> FrameKey:
        location = frame.location
        if location is None:
            line = 0
        elif isinstance(location, int):
            line = location
        else:
            line = location[0] or 0
        return frame.filename, frame.funcname, line

    # ---------------------------------------------------------------- samples
    def add_thread_sample(self, t: float, interpreters: Iterable[InterpreterInfo]) -> None:
        """Record one sampling tick: the current stack of every thread."""
        t = round(t, 3)
        with self._lock:
            for interpreter in interpreters:
                for thread in interpreter.threads:
                    frames = thread.frame_info
                    if not frames:
                        continue
                    stack, internal = self._stack_for_frames(frames, strip=True)
                    if internal:
                        continue  # the profiler's own threads
                    self._samples.append(t, thread.thread_id, stack, thread.status)
            self._sample_count += 1

    def add_async_sample(self, t: float, linear_stacks: Iterable[tuple[list[FrameInfo], int, int]]) -> None:
        """Record async-aware stacks (one linearised coroutine chain per leaf task)."""
        t = round(t, 3)
        with self._lock:
            for frames, thread_id, _leaf_task in linear_stacks:
                stack, internal = self._stack_for_frames(frames, strip=False)
                if not internal:
                    self._async_samples.append(t, thread_id, stack, 0)

    def record_error(self) -> None:
        """Count a discarded sample (torn read)."""
        with self._lock:
            self._error_count += 1

    def set_sampling_rate(self, rate_hz: float) -> None:
        self._rate_hz = rate_hz

    def stats(self) -> JsonObject:
        return {"samples": self._sample_count, "errors": self._error_count, "rateHz": self._rate_hz}

    # ------------------------------------------------------------ time series
    def add_track(self, name: str, t: float, value: float) -> None:
        with self._lock:
            self._tracks.setdefault(name, []).append([round(t, 2), value])

    def add_gc(self, t: float, duration_ms: float, generation: int, collected: int, heap_size: int) -> None:
        with self._lock:
            self._gc.append([round(t, 3), round(duration_ms, 4), generation, collected, heap_size])

    def add_marker(self, name: str, t: float | None = None) -> None:
        with self._lock:
            self._markers.append([round(self.now() if t is None else t, 2), name])

    def add_event(self, kind: str, message: str, t: float | None = None, extra: JsonObject | None = None) -> None:
        with self._lock:
            event: JsonObject = dict(extra) if extra else {}
            event.update(t=round(self.now() if t is None else t, 2), kind=kind, message=message)
            self._events.append(event)

    def set_thread_name(self, thread_id: int, name: str) -> None:
        with self._lock:
            if self._threads.get(thread_id) != name:
                self._threads[thread_id] = name
                self._dirty_threads.add(thread_id)

    # ------------------------------------------------------------------ tasks
    def has_tasks(self) -> bool:
        return bool(self._tasks)

    def update_tasks(self, t: float, awaited_infos: Iterable[AwaitedInfo], running_ids: set[int]) -> None:
        """Reconcile the task table with the tasks currently alive in the target."""
        t = round(t, 2)
        seen: set[int] = set()
        with self._lock:
            for info in awaited_infos:
                for task in info.awaited_by:
                    task_id = task.task_id
                    seen.add(task_id)
                    frames = [frame for coro in task.coroutine_stack for frame in coro.call_stack]
                    stack = self._stack_for_frames(frames, strip=False)[0] if frames else self.NO_STACK
                    # awaited_by names the awaiting task by id (int) when it is known
                    awaiter = task.awaited_by[0].task_name if task.awaited_by else None
                    parent = awaiter if isinstance(awaiter, int) else None
                    state = "running" if task_id in running_ids else "waiting"
                    record = self._tasks.get(task_id)
                    if record is None:
                        self._tasks[task_id] = TaskRecord(
                            task_id=task_id,
                            name=task.task_name or f"Task-{task_id}",
                            parent=parent,
                            thread=info.thread_id,
                            start=t,
                            stack=stack,
                            state=state,
                        )
                        self._task_events.append([t, task_id, state])
                        self._dirty_tasks.add(task_id)
                    elif (record.state, record.stack, record.parent) != (state, stack, parent):
                        if record.state != state:
                            self._task_events.append([t, task_id, state])
                        record.state, record.stack, record.parent = state, stack, parent
                        self._dirty_tasks.add(task_id)
            for task_id, record in self._tasks.items():
                if record.end is None and task_id not in seen:
                    record.end = t
                    record.state = "done"
                    self._task_events.append([t, task_id, "done"])
                    self._dirty_tasks.add(task_id)

    # ----------------------------------------------------------------- memory
    def add_snapshot(self, snapshot: MemorySnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.snapshot_id] = snapshot
            self._new_snapshots.append(snapshot.snapshot_id)

    def add_object_counts(self, t: float, counts: list[object]) -> None:
        with self._lock:
            self._object_counts.append({"t": round(t, 2), "counts": counts})
            self._new_object_counts = True

    # ----------------------------------------------------------------- deltas
    def delta(self) -> JsonObject:
        """Everything recorded since the previous ``delta()`` call."""
        with self._lock:
            cursor = self._cursor
            data = self._appended_since(cursor)
            data["tasks"] = [self._tasks[i].to_wire() for i in self._dirty_tasks]
            data["threads"] = {str(i): self._threads[i] for i in self._dirty_threads}
            data["snapshots"] = [self._snapshots[i].to_wire() for i in self._new_snapshots]
            data["objectCounts"] = self._object_counts[-1:] if self._new_object_counts else []
            if self._meta_dirty:
                data["meta"] = dict(self._meta)

            self._cursor = _Cursor(
                frames=len(self._frames),
                stacks=len(self._stacks),
                samples=len(self._samples),
                async_samples=len(self._async_samples),
                gc=len(self._gc),
                markers=len(self._markers),
                events=len(self._events),
                task_events=len(self._task_events),
                tracks={name: len(points) for name, points in self._tracks.items()},
            )
            self._dirty_tasks.clear()
            self._dirty_threads.clear()
            self._new_snapshots.clear()
            self._new_object_counts = False
            self._meta_dirty = False
            return data

    def full(self) -> JsonObject:
        """The whole profile in delta shape (the ``.pyprof`` file content)."""
        with self._lock:
            data = self._appended_since(_Cursor())
            data["tasks"] = [task.to_wire() for task in self._tasks.values()]
            data["threads"] = {str(i): name for i, name in self._threads.items()}
            data["snapshots"] = [snapshot.to_wire() for snapshot in self._snapshots.values()]
            data["objectCounts"] = list(self._object_counts)
            data["meta"] = dict(self._meta)
            data["format"] = self.FORMAT
            data["version"] = self.FORMAT_VERSION
            return data

    def _appended_since(self, cursor: _Cursor) -> JsonObject:
        tracks: JsonObject = {}
        for name, points in self._tracks.items():
            start = cursor.tracks.get(name, 0)
            if start < len(points):
                tracks[name] = points[start:]
        return {
            "now": round(self.now(), 2),
            "frames": self._frames[cursor.frames :],
            "stacks": self._stacks[cursor.stacks :],
            "samples": self._samples.to_wire(cursor.samples),
            "asyncSamples": self._async_samples.to_wire(cursor.async_samples),
            "tracks": tracks,
            "gc": self._gc[cursor.gc :],
            "markers": self._markers[cursor.markers :],
            "events": self._events[cursor.events :],
            "taskEvents": self._task_events[cursor.task_events :],
            "stats": self.stats(),
        }


@dataclass(slots=True)
class TaskRecord:
    """One asyncio task as seen from outside the process (mutable: tasks change state)."""

    task_id: int
    name: str
    parent: int | None
    thread: int
    start: float
    stack: int
    state: str
    end: float | None = None

    def to_wire(self) -> JsonObject:
        return {
            "id": self.task_id,
            "name": self.name,
            "parent": self.parent,
            "thread": self.thread,
            "start": self.start,
            "end": self.end,
            "stack": self.stack,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class AllocationSite:
    """Live memory allocated from one call stack."""

    stack: int
    size: int
    count: int


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """A tracemalloc snapshot grouped by call stack."""

    snapshot_id: int
    label: str
    t: float
    total_size: int
    total_count: int
    other_size: int
    other_count: int
    traced: int
    peak: int
    take_ms: float | None
    sites: tuple[AllocationSite, ...]

    def to_wire(self) -> JsonObject:
        return {
            "id": self.snapshot_id,
            "label": self.label,
            "t": self.t,
            "totalSize": self.total_size,
            "totalCount": self.total_count,
            "otherSize": self.other_size,
            "otherCount": self.other_count,
            "traced": self.traced,
            "peak": self.peak,
            "takeMs": self.take_ms,
            "entries": [[site.stack, site.size, site.count] for site in self.sites],
        }


@dataclass(slots=True)
class SampleColumns:
    """Columnar sample table: one entry per (timestamp, thread)."""

    t: list[float] = field(default_factory=list)
    tid: list[int] = field(default_factory=list)
    stack: list[int] = field(default_factory=list)
    status: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.t)

    def append(self, t: float, tid: int, stack: int, status: int) -> None:
        self.t.append(t)
        self.tid.append(tid)
        self.stack.append(stack)
        self.status.append(status)

    def to_wire(self, start: int = 0) -> JsonObject:
        return {
            "t": self.t[start:],
            "tid": self.tid[start:],
            "stack": self.stack[start:],
            "status": self.status[start:],
        }
