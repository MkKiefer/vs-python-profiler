"""What the collector tells the extension without being asked.

Mirror of ``CollectorNotification`` in ``src/shared/protocol.ts``. The ``delta``
notification is not here: its payload is ``Store.delta()``.
"""

from abc import abstractmethod
from dataclasses import dataclass

from _vscode_pyprof.collector.protocol import RpcNotification, SessionState
from _vscode_pyprof.wire import JsonObject, WireMessage


class Notification(WireMessage):
    """A message with a fixed notification name."""

    __slots__ = ()

    @property
    @abstractmethod
    def method(self) -> RpcNotification: ...


@dataclass(frozen=True, slots=True)
class StateChanged(Notification):
    state: SessionState
    pid: int | None = None
    """The sampled process, when sampling starts."""
    reason: str | None = None
    """A ``StopReason`` value or the extension's own reason, when sampling ends."""

    @property
    def method(self) -> RpcNotification:
        return RpcNotification.STATE

    def to_wire(self) -> JsonObject:
        wire: JsonObject = {"state": self.state}
        if self.pid is not None:
            wire["pid"] = self.pid
        if self.reason is not None:
            wire["reason"] = self.reason
        return wire


@dataclass(frozen=True, slots=True)
class AgentConnected(Notification):
    pid: int
    argv: list[str]
    cwd: str | None

    @property
    def method(self) -> RpcNotification:
        return RpcNotification.AGENT

    def to_wire(self) -> JsonObject:
        return {"connected": True, "pid": self.pid, "argv": self.argv, "cwd": self.cwd}


@dataclass(frozen=True, slots=True)
class AgentDisconnected(Notification):
    @property
    def method(self) -> RpcNotification:
        return RpcNotification.AGENT

    def to_wire(self) -> JsonObject:
        return {"connected": False}


@dataclass(frozen=True, slots=True)
class ChildrenFound(Notification):
    """Python child processes of the target that were not known before."""

    pids: list[int]

    @property
    def method(self) -> RpcNotification:
        return RpcNotification.CHILDREN

    def to_wire(self) -> JsonObject:
        return {"pids": self.pids}


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Notification):
    """A failure outside any request, e.g. sampling could not start for a launched program."""

    message: str

    @property
    def method(self) -> RpcNotification:
        return RpcNotification.ERROR

    def to_wire(self) -> JsonObject:
        return {"message": self.message}
