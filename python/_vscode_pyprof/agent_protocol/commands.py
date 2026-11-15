"""The commands the collector sends to the agent, and the envelopes around them.

Request: ``CommandCall`` ``{"id": 1, "method": "snapshot", "params": {...}}``
Reply:   ``CommandResult`` ``{"type": "result", "id": 1, "result": {...}}`` or ``..."error": "..."}``

Each command is a class whose ``command`` names it on the wire; the collector
sends an instance, the agent reads the same class back from ``params``.
"""

from abc import abstractmethod
from dataclasses import dataclass

# annotations only: loading ``typing`` into the profiled program is not worth a ClassVar
lazy from typing import ClassVar, Self

from _vscode_pyprof.agent_protocol.names import AgentCommand, AgentMessageType
from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


class AgentRequest(WireMessage):
    """The ``params`` of one command."""

    __slots__ = ()

    command: ClassVar[AgentCommand]

    @abstractmethod
    def to_wire(self) -> JsonObject:
        """The command's parameters, sent as the ``params`` of a ``CommandCall``."""


@dataclass(frozen=True)
class StartTracing(AgentRequest):
    """Answered with a ``TracingStatus``."""

    command = AgentCommand.TRACEMALLOC_START

    frames: int
    """Traceback depth tracemalloc records."""

    def to_wire(self) -> JsonObject:
        return {"frames": self.frames}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(frames=WireReader.for_object(raw, where).get("frames", int))


@dataclass(frozen=True)
class StopTracing(AgentRequest):
    """Answered with a ``TracingStatus``."""

    command = AgentCommand.TRACEMALLOC_STOP

    def to_wire(self) -> JsonObject:
        return {}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        WireReader.for_object(raw, where)
        return cls()


@dataclass(frozen=True)
class TakeSnapshot(AgentRequest):
    """Answered with a ``HeapSnapshot``."""

    command = AgentCommand.SNAPSHOT

    limit: int
    """How many of the largest allocations to list."""

    def to_wire(self) -> JsonObject:
        return {"limit": self.limit}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(limit=WireReader.for_object(raw, where).get("limit", int))


@dataclass(frozen=True)
class CountObjects(AgentRequest):
    """Answered with ``ObjectCounts``."""

    command = AgentCommand.OBJECT_COUNTS

    limit: int
    """How many of the most common types to list."""

    def to_wire(self) -> JsonObject:
        return {"limit": self.limit}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(limit=WireReader.for_object(raw, where).get("limit", int))


@dataclass(frozen=True)
class SetAsyncioDebug(AgentRequest):
    """Answered with an ``AsyncioDebugStatus``."""

    command = AgentCommand.ASYNCIO_DEBUG

    enabled: bool
    slow_ms: float | None = None
    """Slow-callback threshold; ``None`` keeps the current one."""

    def to_wire(self) -> JsonObject:
        return self._omit_none({"enabled": self.enabled, "slowMs": self.slow_ms})

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(enabled=message.get("enabled", bool), slow_ms=message.get_or("slowMs", float, None))


@dataclass(frozen=True)
class Ping(AgentRequest):
    """Answered with a ``Pong``."""

    command = AgentCommand.PING

    def to_wire(self) -> JsonObject:
        return {}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        WireReader.for_object(raw, where)
        return cls()


@dataclass(frozen=True)
class Shutdown(AgentRequest):
    """Answered with an ``Acknowledgement``; the agent then stops."""

    command = AgentCommand.SHUTDOWN

    def to_wire(self) -> JsonObject:
        return {}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        WireReader.for_object(raw, where)
        return cls()


@dataclass(frozen=True)
class CommandCall(WireMessage):
    """One command on its way to the agent."""

    id: int
    method: str
    """An ``AgentCommand`` value; kept a string so the agent can name a command it does not know."""
    params: JsonObject

    def to_wire(self) -> JsonObject:
        return {"id": self.id, "method": self.method, "params": self.params}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(id=message.get("id", int), method=message.get("method", str), params=message.json_object("params"))


@dataclass(frozen=True)
class CommandResult(WireMessage):
    """The agent's answer to the ``CommandCall`` with the same ``id``: a result or an error."""

    id: int
    result: object = None
    """Any JSON value (the reply's ``to_wire()``); the caller reads it as the reply type it expects."""
    error: str | None = None

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {"type": AgentMessageType.RESULT, "id": self.id, "result": self.result, "error": self.error}
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        message.require_type(AgentMessageType.RESULT)
        return cls(
            id=message.get("id", int),
            result=message.value("result"),
            error=message.get_or("error", str, None),
        )
