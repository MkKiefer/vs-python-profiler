"""Names used in the messages between the collector and the in-process agent."""

from enum import StrEnum


class EventKind(StrEnum):
    """``kind`` of a timeline event. The dashboard styles the ones it knows and shows the others as text."""

    AGENT = "agent"
    SAMPLER = "sampler"
    ASYNCIO = "asyncio"
    SLOW_CALLBACK = "slow-callback"
    NEVER_AWAITED = "never-awaited"
    TASK_DESTROYED_PENDING = "task-destroyed-pending"
    EXCEPTION_NEVER_RETRIEVED = "exception-never-retrieved"
