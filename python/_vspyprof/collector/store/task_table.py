"""The asyncio tasks of the target and how their state changed over time."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from _vspyprof.collector.store.append_log import AppendLog
from _vspyprof.wire import JsonObject


class TaskState(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class TaskObservation:
    """One task as it was seen alive at a single moment."""

    task_id: int
    name: str
    parent: int | None
    thread: int
    stack: int
    state: TaskState


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """One asyncio task over its lifetime, as seen from outside the process."""

    task_id: int
    name: str
    parent: int | None
    thread: int
    start: float
    stack: int
    state: TaskState
    end: float | None = None

    @classmethod
    def first_seen(cls, t: float, observation: TaskObservation) -> TaskRecord:
        return cls(
            task_id=observation.task_id,
            name=observation.name,
            parent=observation.parent,
            thread=observation.thread,
            start=t,
            stack=observation.stack,
            state=observation.state,
        )

    def matches(self, observation: TaskObservation) -> bool:
        """True if the observation tells nothing new about this task."""
        return (self.state, self.stack, self.parent) == (observation.state, observation.stack, observation.parent)

    def observed(self, observation: TaskObservation) -> TaskRecord:
        return replace(self, state=observation.state, stack=observation.stack, parent=observation.parent)

    def finished(self, t: float) -> TaskRecord:
        return replace(self, state=TaskState.DONE, end=t)

    def to_profile(self) -> JsonObject:
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


class TaskTable:
    """Follows tasks from the first time they are seen until they disappear.

    ``events`` rows are ``[t, task id, new state]``. Not thread-safe on its
    own: the ``Store`` guards it with its lock.
    """

    def __init__(self) -> None:
        self.events: AppendLog[list[float | int | str]] = AppendLog()
        self._records: dict[int, TaskRecord] = {}
        self._changed: set[int] = set()

    def __len__(self) -> int:
        return len(self._records)

    def reconcile(self, t: float, alive: Iterable[TaskObservation]) -> None:
        """Bring the table up to date with the tasks alive at ``t``; the others have finished."""
        seen: set[int] = set()
        for observation in alive:
            seen.add(observation.task_id)
            record = self._records.get(observation.task_id)
            if record is None:
                self._put(TaskRecord.first_seen(t, observation))
                self._record_state(t, observation.task_id, observation.state)
            elif not record.matches(observation):
                if record.state != observation.state:
                    self._record_state(t, observation.task_id, observation.state)
                self._put(record.observed(observation))
        for record in list(self._records.values()):
            if record.end is None and record.task_id not in seen:
                self._put(record.finished(t))
                self._record_state(t, record.task_id, TaskState.DONE)

    def records(self, *, new_only: bool) -> list[TaskRecord]:
        """Every task, or with ``new_only`` those that changed since the previous ``new_only`` call."""
        if not new_only:
            return list(self._records.values())
        changed = [self._records[task_id] for task_id in self._changed]
        self._changed.clear()
        return changed

    def _put(self, record: TaskRecord) -> None:
        self._records[record.task_id] = record
        self._changed.add(record.task_id)

    def _record_state(self, t: float, task_id: int, state: TaskState) -> None:
        self.events.append([t, task_id, state])
