"""Names used on the wire between the collector and the in-process agent."""

from enum import StrEnum


class AgentMessageType(StrEnum):
    """``type`` of a message the agent sends."""

    HELLO = "hello"
    METRICS = "metrics"
    RESULT = "result"


class AgentCommand(StrEnum):
    """``method`` of a request the collector sends to the agent."""

    TRACEMALLOC_START = "tracemalloc_start"
    TRACEMALLOC_STOP = "tracemalloc_stop"
    SNAPSHOT = "snapshot"
    OBJECT_COUNTS = "object_counts"
    ASYNCIO_DEBUG = "asyncio_debug"
    PING = "ping"
    SHUTDOWN = "shutdown"


class EventKind(StrEnum):
    """``kind`` of a timeline event. The dashboard styles the ones it knows and shows the others as text."""

    AGENT = "agent"
    ASYNCIO = "asyncio"
    SLOW_CALLBACK = "slow-callback"
    NEVER_AWAITED = "never-awaited"
    TASK_DESTROYED_PENDING = "task-destroyed-pending"
    EXCEPTION_NEVER_RETRIEVED = "exception-never-retrieved"
