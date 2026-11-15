"""The commands the collector sends to the agent, and the envelopes around them.

Request: ``CommandCall`` ``{"id": 1, "method": "snapshot", "params": {...}}``
Reply:   ``CommandResult`` ``{"type": "result", "id": 1, "result": {...}}`` or ``..."error": "..."}``

Each command is a class whose ``command`` names it on the wire; the collector
sends an instance, the agent reads the same class back from ``params``.
"""

from dataclasses import dataclass

# annotations only: loading ``typing`` into the profiled program is not worth a ClassVar
lazy from typing import ClassVar

from _vscode_pyprof.agent_protocol.names import AgentCommand, AgentMessageType
from _vscode_pyprof.wire import JsonObject, WireMessage


class AgentRequest(WireMessage):
    """The ``params`` of one command."""

    __slots__ = ()

    command: ClassVar[AgentCommand]


@dataclass(frozen=True)
class StartTracing(AgentRequest):
    """Answered with a ``TracingStatus``."""

    command = AgentCommand.TRACEMALLOC_START

    frames: int
    """Traceback depth tracemalloc records."""


@dataclass(frozen=True)
class StopTracing(AgentRequest):
    """Answered with a ``TracingStatus``."""

    command = AgentCommand.TRACEMALLOC_STOP


@dataclass(frozen=True)
class TakeSnapshot(AgentRequest):
    """Answered with a ``HeapSnapshot``."""

    command = AgentCommand.SNAPSHOT

    limit: int
    """How many of the largest allocations to list."""


@dataclass(frozen=True)
class CountObjects(AgentRequest):
    """Answered with ``ObjectCounts``."""

    command = AgentCommand.OBJECT_COUNTS

    limit: int
    """How many of the most common types to list."""


@dataclass(frozen=True)
class SetAsyncioDebug(AgentRequest):
    """Answered with an ``AsyncioDebugStatus``."""

    command = AgentCommand.ASYNCIO_DEBUG

    enabled: bool
    slow_ms: float | None = None
    """Slow-callback threshold; ``None`` keeps the current one."""


@dataclass(frozen=True)
class Ping(AgentRequest):
    """Answered with a ``Pong``."""

    command = AgentCommand.PING


@dataclass(frozen=True)
class Shutdown(AgentRequest):
    """Answered with an ``Acknowledgement``; the agent then stops."""

    command = AgentCommand.SHUTDOWN


@dataclass(frozen=True)
class CommandCall(WireMessage):
    """One command on its way to the agent."""

    id: int
    method: str
    """An ``AgentCommand`` value; kept a string so the agent can name a command it does not know."""
    params: JsonObject


@dataclass(frozen=True)
class CommandResult(WireMessage):
    """The agent's answer to the ``CommandCall`` with the same ``id``: a result or an error."""

    wire_type = AgentMessageType.RESULT

    id: int
    result: JsonObject | None = None
    error: str | None = None
