"""The contract between the collector and the in-process agent.

Both ends take their message types, command names and the address format from
here, so they cannot drift apart. This module is loaded into the profiled
program: it stays tiny and imports nothing the agent does not need anyway.
"""

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


class AgentAddress:
    """Where the agent connects to and the one-time token it presents: ``host:port:token``."""

    __slots__ = ("host", "port", "token")

    def __init__(self, host: str, port: int, token: str) -> None:
        self.host = host
        self.port = port
        self.token = token

    @classmethod
    def parse(cls, text: str) -> AgentAddress:
        """Read ``host:port:token``. Raises ``ValueError`` if ``text`` has another shape."""
        try:
            host, port, token = text.rsplit(":", 2)
            return cls(host, int(port), token)
        except ValueError:
            raise ValueError(f"malformed agent address {text!r}; expected host:port:token") from None

    def __str__(self) -> str:
        return f"{self.host}:{self.port}:{self.token}"
