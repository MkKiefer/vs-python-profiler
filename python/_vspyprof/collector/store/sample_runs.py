"""Run-length encoded storage of stack samples."""

from array import array
from collections.abc import Iterable
from dataclasses import dataclass

from _vspyprof.collector.store.append_log import AppendLog
from _vspyprof.collector.store.column_snapshot import ColumnSnapshot
from _vspyprof.collector.store.typed_column import TypedColumn
from _vspyprof.wire import JsonObject


@dataclass(frozen=True, slots=True)
class Sample:
    """One thread's stack at one tick."""

    thread_id: int
    stack: int
    status: int


@dataclass(slots=True)
class _OpenRun:
    """A run that may still grow: its key was seen in the latest tick."""

    start: int
    count: int


class SampleRuns:
    """Samples as runs: one row for each stretch of consecutive ticks in which a thread kept the same stack and status.

    A thread that waits on a lock, a socket or a queue repeats one sample every
    tick; storing ``count`` instead of one row per tick is what keeps a long
    recording of a thread pool small. Rows (14 bytes each) are::

        tick    first tick of the run (index into ``ticks``)
        count   ticks in the run, 1..MAX_RUN
        thread  index into ``threadIds``
        stack, status

    ``ticks`` holds the time of every tick (8 bytes per tick, shared by all
    threads), so a time range maps to a range of ticks and the samples in it
    are counted exactly.

    A run is written when it closes: when its thread's next sample differs or
    is missing, after ``MAX_RUN`` ticks, or when the table is read (``flush``),
    so readers only ever see appended rows. Rows are therefore ordered by their
    last tick, and a run is at most ``MAX_RUN`` ticks long; readers rely on both
    (``SampleTable`` in ``src/shared/model.ts``).

    Not thread-safe on its own: the ``Store`` guards it with its lock.
    """

    MAX_RUN = 255
    STATUS_MASK = 0xFF
    """Thread status bits kept; the dashboard reads them as one byte."""

    def __init__(self) -> None:
        self._ticks: TypedColumn[float] = TypedColumn(array("d"))
        self._thread_ids: AppendLog[int] = AppendLog()
        self._thread_index: dict[int, int] = {}
        self._tick: TypedColumn[int] = TypedColumn(array("i"))
        self._count: TypedColumn[int] = TypedColumn(array("B"))
        self._thread: TypedColumn[int] = TypedColumn(array("I"))
        self._stack: TypedColumn[int] = TypedColumn(array("i"))
        self._status: TypedColumn[int] = TypedColumn(array("B"))
        self._open: dict[tuple[int, int, int], _OpenRun] = {}  # (thread, stack, status) -> run

    @property
    def tick_count(self) -> int:
        return len(self._ticks)

    @property
    def row_count(self) -> int:
        """Rows written so far; runs still open are not counted until ``flush``."""
        return len(self._tick)

    def add_tick(self, t: float, samples: Iterable[Sample]) -> None:
        """Record one tick at session time ``t``: the samples taken in it."""
        tick = len(self._ticks)
        self._ticks.append(t)
        seen: set[tuple[int, int, int]] = set()
        repeated: list[tuple[int, int, int]] = []
        for sample in samples:
            key = (self._index_of(sample.thread_id), sample.stack, sample.status & self.STATUS_MASK)
            if key in seen:  # the same sample twice in one tick (async stacks of two tasks can be equal)
                repeated.append(key)
                continue
            seen.add(key)
            run = self._open.get(key)
            if run is not None and run.count < self.MAX_RUN:
                run.count += 1  # open runs were all seen in the previous tick, so this one continues
            else:
                if run is not None:
                    self._write(key, run)
                self._open[key] = _OpenRun(tick, 1)
        # every run not seen in this tick ended in the previous one: close them before anything ends here
        for key in [key for key in self._open if key not in seen]:
            self._write(key, self._open.pop(key))
        for key in repeated:  # these end in this tick, after the runs closed above (rows stay ordered)
            self._write(key, _OpenRun(tick, 1))

    def flush(self) -> None:
        """Write the open runs, so every sample taken so far is in a row."""
        for key, run in self._open.items():
            self._write(key, run)
        self._open.clear()

    def to_profile(self, *, new_only: bool) -> JsonObject:
        """All samples, or with ``new_only`` those not handed out by a previous ``new_only`` call. Flushes first."""
        self.flush()
        if new_only:
            return {
                "ticks": self._ticks.new_values(),
                "threadIds": self._thread_ids.rows(new_only=True),
                "tick": self._tick.new_values(),
                "count": self._count.new_values(),
                "thread": self._thread.new_values(),
                "stack": self._stack.new_values(),
                "status": self._status.new_values(),
            }
        return {
            "ticks": self._ticks.values(),
            "threadIds": self._thread_ids.rows(new_only=False),
            "tick": self._tick.values(),
            "count": self._count.values(),
            "thread": self._thread.values(),
            "stack": self._stack.values(),
            "status": self._status.values(),
        }

    def snapshot(self) -> JsonObject:
        """All samples with the large columns as ``ColumnSnapshot``s, for streaming them into a file. Flushes first."""
        self.flush()
        rows = len(self._tick)
        return {
            "ticks": ColumnSnapshot(self._ticks, len(self._ticks)),
            "threadIds": self._thread_ids.rows(new_only=False),
            "tick": ColumnSnapshot(self._tick, rows),
            "count": ColumnSnapshot(self._count, rows),
            "thread": ColumnSnapshot(self._thread, rows),
            "stack": ColumnSnapshot(self._stack, rows),
            "status": ColumnSnapshot(self._status, rows),
        }

    def _index_of(self, thread_id: int) -> int:
        index = self._thread_index.get(thread_id)
        if index is None:
            index = self._thread_index[thread_id] = len(self._thread_ids)
            self._thread_ids.append(thread_id)
        return index

    def _write(self, key: tuple[int, int, int], run: _OpenRun) -> None:
        thread, stack, status = key
        self._tick.append(run.start)
        self._count.append(run.count)
        self._thread.append(thread)
        self._stack.append(stack)
        self._status.append(status)
