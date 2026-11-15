"""The first message of an agent."""

from dataclasses import dataclass

# annotations only: loading ``typing`` into the profiled program is not worth a Self
lazy from typing import Self

from _vscode_pyprof.agent_protocol.names import AgentMessageType
from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class ThreadName(WireMessage):
    """The name of one thread of the target; sent as ``[ident, native_id, name]``."""

    ident: int | None
    native_id: int | None
    name: str

    def ids(self) -> list[int]:
        """Every id samples may carry for this thread (which one depends on the platform)."""
        return [thread_id for thread_id in (self.native_id, self.ident) if thread_id is not None]

    def to_wire(self) -> list[object]:
        return [self.ident, self.native_id, self.name]

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        row = WireReader.for_row(raw, where, ("ident", "nativeId", "name"))
        return cls(
            ident=row.get_or("ident", int, None), native_id=row.get_or("nativeId", int, None), name=row.get("name", str)
        )


@dataclass(frozen=True)
class AgentHello(WireMessage):
    """What the agent tells the collector about its process when it connects."""

    token: str
    """The one-time token of the ``AgentAddress``; proves the agent was started by this session."""
    pid: int
    executable: str | None
    argv: list[str]
    cwd: str | None
    version: str | None
    """Python version of the target, ``major.minor.micro``."""
    threads: list[ThreadName]

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {
                "type": AgentMessageType.HELLO,
                "token": self.token,
                "pid": self.pid,
                "executable": self.executable,
                "argv": self.argv,
                "cwd": self.cwd,
                "version": self.version,
                "threads": [thread.to_wire() for thread in self.threads],
            }
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        message.require_type(AgentMessageType.HELLO)
        return cls(
            token=message.get("token", str),
            pid=message.get("pid", int),
            executable=message.get_or("executable", str, None),
            argv=message.list_of("argv", str),
            cwd=message.get_or("cwd", str, None),
            version=message.get_or("version", str, None),
            threads=message.list_of("threads", ThreadName),
        )
