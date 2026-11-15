"""In-memory profile store.

Everything the UI shows is kept in a handful of append-only tables that share
one clock (milliseconds since session start, ``SessionClock``):

* frames   - interned ``[file, func, line, category]``           (``StackTable``)
* stacks   - prefix tree ``[parent_stack, frame]``                (``StackTable``)
* samples  - columnar ``t / tid / stack / status`` (thread stacks) (``SampleColumns``)
* async    - same layout, stacks reconstructed per asyncio task
* tracks   - named time series ``[[t, value], ...]``              (``Track``)
* tasks, task_events                                               (``TaskTable``)
* gc, markers, snapshots, events, object counts

The store hands out *deltas* (everything appended since the last call) so the
extension can stream live data cheaply, and ``full()`` returns the same shape
for saving ``.vspyprof`` files. The TypeScript ``ProfileModel`` consumes both.
"""

import threading
from collections.abc import Iterable, Sequence
from dataclasses import replace

# annotations only (never evaluated at runtime): the store imports without the private Tachyon module
lazy from _remote_debugging import AwaitedInfo, InterpreterInfo

from _vspyprof.agent_protocol.metrics import EventDetails
from _vspyprof.agent_protocol.replies import ObjectCounts
from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.store.append_log import AppendLog
from _vspyprof.collector.store.async_stack import AsyncStack
from _vspyprof.collector.store.memory_snapshot import MemorySnapshot
from _vspyprof.collector.store.profile_meta import ProfileMeta
from _vspyprof.collector.store.sample_columns import SampleColumns
from _vspyprof.collector.store.sampling_stats import SamplingStats
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.stack_table import SourceFrame, StackTable
from _vspyprof.collector.store.task_table import TaskObservation, TaskState, TaskTable
from _vspyprof.collector.store.timeline_event import TimelineEvent
from _vspyprof.collector.store.track import Track
from _vspyprof.wire import JsonObject


class Store:
    """Thread-safe facade over the tables of one profile.

    The sampler thread, the agent reader and the RPC handlers all record into
    it; one lock guards every table. ``delta()`` and ``full()`` are where the
    tables become JSON.
    """

    FORMAT = "vspyprof"
    FORMAT_VERSION = 1
    NO_STACK = StackTable.NO_STACK

    def __init__(self, clock: SessionClock, stacks: StackTable) -> None:
        self._clock = clock
        self._stacks = stacks
        self._lock = threading.RLock()

        self._samples = SampleColumns()
        self._async_samples = SampleColumns()
        self._tracks: dict[Track, AppendLog[list[float]]] = {}  # rows are [t, value]
        self._gc: AppendLog[list[float]] = AppendLog()  # rows are [t, duration ms, generation, collected, heap size]
        self._markers: AppendLog[list[float | str]] = AppendLog()  # rows are [t, name]
        self._events: AppendLog[TimelineEvent] = AppendLog()
        self._tasks = TaskTable()
        self._snapshots: AppendLog[MemorySnapshot] = AppendLog()
        self._object_counts: AppendLog[ObjectCounts] = AppendLog()
        self._threads: dict[int, str] = {}
        self._renamed_threads: set[int] = set()
        self._meta = ProfileMeta.for_running_interpreter()
        self._meta_changed = True
        self._sample_count = 0
        self._error_count = 0
        self._rate_hz = 0.0

    # ---- session facts
    def describe_session(self, options: CollectorOptions, label: str | None) -> None:
        """Record the options the session runs with; ``strip_launcher`` takes effect for new stacks."""
        with self._lock:
            self._stacks.strip_launcher(options.strip_launcher)
            self._change_meta(replace(self._meta, options=options, label=label))

    def set_target(self, pid: int) -> None:
        """Record which process is sampled."""
        with self._lock:
            self._change_meta(replace(self._meta, pid=pid))

    def set_agent_process(self, executable: str | None, argv: list[str], cwd: str | None) -> None:
        """Record what the connected agent reports about its process."""
        with self._lock:
            self._change_meta(replace(self._meta, agent=True, executable=executable, argv=argv, cwd=cwd))

    def _change_meta(self, meta: ProfileMeta) -> None:
        self._meta = meta
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
                    stack = self._stacks.intern_sampled(thread.frame_info, strip=True)
                    if not stack.internal:  # the profiler's own threads are left out
                        self._samples.append(t, thread.thread_id, stack.stack_id, thread.status)
            self._sample_count += 1

    def add_async_sample(self, t: float, stacks: Iterable[AsyncStack]) -> None:
        """Record the async-aware stacks of one tick, one per running leaf task."""
        t = round(t, 3)
        with self._lock:
            for async_stack in stacks:
                stack = self._stacks.intern_sampled(async_stack.frames_leaf_first, strip=False)
                if not stack.internal:
                    self._async_samples.append(t, async_stack.thread_id, stack.stack_id, 0)

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

    def add_event(self, kind: str, message: str, t: float | None = None, details: EventDetails | None = None) -> None:
        """Something worth showing on the timeline; ``t`` defaults to now.

        ``kind`` is an ``EventKind`` value, or a kind only a newer agent knows.
        """
        with self._lock:
            self._events.append(TimelineEvent(self._rounded_time(t), kind, message, details or EventDetails()))

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
                        stack=self._stacks.intern_sampled(frames, strip=False).stack_id,
                        state=TaskState.RUNNING if task.task_id in running_ids else TaskState.WAITING,
                    )
                )
        return observations

    # ---- memory
    def intern_traceback(self, frames_root_first: Sequence[SourceFrame]) -> int:
        """Intern a stack recorded inside the target (tracemalloc), given root-first frames.

        Applies the same launcher stripping as sampled stacks so both kinds of
        stack share prefixes. Returns ``NO_STACK`` if nothing is left.
        """
        with self._lock:
            return self._stacks.intern(frames_root_first, strip=True).stack_id

    def add_snapshot(self, snapshot: MemorySnapshot) -> None:
        with self._lock:
            self._snapshots.append(snapshot)

    def add_object_counts(self, counts: ObjectCounts) -> None:
        """``counts.t`` is in session milliseconds."""
        with self._lock:
            self._object_counts.append(replace(counts, t=round(counts.t, 2)))

    # ---- reading
    def delta(self) -> JsonObject:
        """Everything recorded since the previous ``delta()`` call."""
        with self._lock:
            data = self._tables(new_only=True)
            data["threads"] = {str(thread_id): self._threads[thread_id] for thread_id in self._renamed_threads}
            latest_counts = self._object_counts.rows(new_only=True)[-1:]  # only the latest is shown live
            data["objectCounts"] = [self._counts_profile(counts) for counts in latest_counts]
            if self._meta_changed:
                data["meta"] = self._meta.to_profile()
            self._renamed_threads.clear()
            self._meta_changed = False
            return data

    def full(self) -> JsonObject:
        """The whole profile in delta shape (the ``.vspyprof`` file content)."""
        with self._lock:
            data = self._tables(new_only=False)
            data["threads"] = {str(thread_id): name for thread_id, name in self._threads.items()}
            data["objectCounts"] = [self._counts_profile(counts) for counts in self._object_counts.rows(new_only=False)]
            data["meta"] = self._meta.to_profile()
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
            "samples": self._samples.to_profile(new_only=new_only),
            "asyncSamples": self._async_samples.to_profile(new_only=new_only),
            "tracks": tracks,
            "gc": self._gc.rows(new_only=new_only),
            "markers": self._markers.rows(new_only=new_only),
            "events": [event.to_profile() for event in self._events.rows(new_only=new_only)],
            "tasks": [task.to_profile() for task in self._tasks.records(new_only=new_only)],
            "taskEvents": self._tasks.events.rows(new_only=new_only),
            "snapshots": [snapshot.to_profile() for snapshot in self._snapshots.rows(new_only=new_only)],
            "stats": self.stats().to_profile(),
        }

    @staticmethod
    def _counts_profile(counts: ObjectCounts) -> JsonObject:
        return {"t": counts.t, "counts": [[count.type_name, count.count] for count in counts.counts]}

    def _rounded_time(self, t: float | None) -> float:
        return round(self._clock.now() if t is None else t, 2)
