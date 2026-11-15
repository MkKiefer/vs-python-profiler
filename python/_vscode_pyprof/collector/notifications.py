"""What the collector tells the extension without being asked.

Mirror of ``CollectorNotification`` in ``src/shared/protocol.ts``. The ``delta``
notification is not here: its payload is ``Store.delta()``.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from _vscode_pyprof.collector.protocol import RpcNotification, SessionState
from _vscode_pyprof.wire import JsonObject, WireWritable


class Notification(WireWritable):
    """A message with a fixed notification name."""

    __slots__ = ()

    method: ClassVar[RpcNotification]

    @abstractmethod
    def to_wire(self) -> JsonObject:
        """The notification's ``params``."""


@dataclass(frozen=True, slots=True)
class StateChanged(Notification):
    method = RpcNotification.STATE

    state: SessionState
    pid: int | None = None
    """The sampled process, when sampling starts."""
    reason: str | None = None
    """A ``StopReason`` value or the extension's own reason, when sampling ends."""

    def to_wire(self) -> JsonObject:
        return self._omit_none({"state": self.state, "pid": self.pid, "reason": self.reason})


@dataclass(frozen=True, slots=True)
class AgentConnected(Notification):
    method = RpcNotification.AGENT

    pid: int
    argv: list[str]
    cwd: str | None

    def to_wire(self) -> JsonObject:
        return self._omit_none({"connected": True, "pid": self.pid, "argv": self.argv, "cwd": self.cwd})


@dataclass(frozen=True, slots=True)
class AgentDisconnected(Notification):
    method = RpcNotification.AGENT

    def to_wire(self) -> JsonObject:
        return {"connected": False}


@dataclass(frozen=True, slots=True)
class ChildrenFound(Notification):
    """Python child processes of the target that were not known before."""

    method = RpcNotification.CHILDREN

    pids: list[int]

    def to_wire(self) -> JsonObject:
        return {"pids": self.pids}


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Notification):
    """A failure outside any request, e.g. sampling could not start for a launched program."""

    method = RpcNotification.ERROR

    message: str

    def to_wire(self) -> JsonObject:
        return {"message": self.message}
