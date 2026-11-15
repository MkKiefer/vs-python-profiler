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
    """One task as it was seen alive at a single moment.

    Tachyon identifies a task by the address of its object, and CPython reuses
    the address of a finished task for new ones within milliseconds. An address
    therefore names a task only while that task is alive.
    """

    address: int
    name: str
    parent_address: int | None
    """Address of the task awaiting this one, if known."""
    thread: int
    stack: int
    state: TaskState


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """One asyncio task over its lifetime, as seen from outside the process."""

    task_id: int
    """Unique within the profile; unlike the task's address it is never reused."""
    name: str
    parent: int | None
    """``task_id`` of the awaiting task."""
    thread: int
    start: float
    stack: int
    state: TaskState
    end: float | None = None

    @classmethod
    def first_seen(cls, task_id: int, t: float, observation: TaskObservation, parent: int | None) -> TaskRecord:
        return cls(
            task_id=task_id,
            name=observation.name,
            parent=parent,
            thread=observation.thread,
            start=t,
            stack=observation.stack,
            state=observation.state,
        )

    def matches(self, observation: TaskObservation, parent: int | None) -> bool:
        """True if the observation tells nothing new about this task."""
        return (self.state, self.stack, self.parent) == (observation.state, observation.stack, parent)

    def observed(self, observation: TaskObservation, parent: int | None) -> TaskRecord:
        return replace(self, state=observation.state, stack=observation.stack, parent=parent)

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

    ``events`` rows are ``[t, task id, new state]``. Only the tasks alive at the
    previous ``reconcile`` are compared with the next one, so its cost does not
    grow with the number of tasks that have finished. Not thread-safe on its
    own: the ``Store`` guards it with its lock.
    """

    def __init__(self) -> None:
        self.events: AppendLog[list[float | int | str]] = AppendLog()
        self._records: dict[int, TaskRecord] = {}
        self._alive: dict[int, int] = {}  # address -> task id of the task living there
        self._changed: set[int] = set()
        self._last_task_id = 0

    def __len__(self) -> int:
        return len(self._records)

    def reconcile(self, t: float, alive: Iterable[TaskObservation]) -> None:
        """Bring the table up to date with the tasks alive at ``t``; the others have finished."""
        observations = {observation.address: observation for observation in alive}
        for address in [address for address in self._alive if address not in observations]:
            self._finish(t, self._alive.pop(address))
        for address, observation in observations.items():
            task_id = self._alive.get(address)
            if task_id is not None and self._records[task_id].name != observation.name:
                # another task took the address between two observations (asyncio names tasks Task-<n>)
                self._finish(t, self._alive.pop(address))
                task_id = None
            if task_id is None:
                self._last_task_id += 1
                self._alive[address] = self._last_task_id
        for address, observation in observations.items():  # parents are resolved once every task has its id
            task_id = self._alive[address]
            parent = None if observation.parent_address is None else self._alive.get(observation.parent_address)
            record = self._records.get(task_id)
            if record is None:
                self._put(TaskRecord.first_seen(task_id, t, observation, parent))
                self._record_state(t, task_id, observation.state)
            elif not record.matches(observation, parent):
                if record.state != observation.state:
                    self._record_state(t, task_id, observation.state)
                self._put(record.observed(observation, parent))

    def records(self, *, new_only: bool) -> list[TaskRecord]:
        """Every task, or with ``new_only`` those that changed since the previous ``new_only`` call."""
        if not new_only:
            return list(self._records.values())
        changed = [self._records[task_id] for task_id in self._changed]
        self._changed.clear()
        return changed

    def _finish(self, t: float, task_id: int) -> None:
        self._put(self._records[task_id].finished(t))
        self._record_state(t, task_id, TaskState.DONE)

    def _put(self, record: TaskRecord) -> None:
        self._records[record.task_id] = record
        self._changed.add(record.task_id)

    def _record_state(self, t: float, task_id: int, state: TaskState) -> None:
        self.events.append([t, task_id, state])
