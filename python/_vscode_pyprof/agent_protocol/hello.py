"""The first message of an agent."""

from dataclasses import dataclass

from _vscode_pyprof.agent_protocol.names import AgentMessageType
from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class ThreadName:
    """The name of one thread of the target; sent as ``[ident, native_id, name]``."""

    ident: int | None
    native_id: int | None
    name: str

    @classmethod
    def list_from_wire(cls, raw_threads: list[object]) -> list[ThreadName]:
        """Read ``[[ident, native_id, name], ...]``; entries of another shape are skipped."""
        threads: list[ThreadName] = []
        for raw in raw_threads:
            if isinstance(raw, list) and len(raw) == 3:
                ident, native_id, name = raw
                threads.append(
                    cls(
                        ident=ident if isinstance(ident, int) else None,
                        native_id=native_id if isinstance(native_id, int) else None,
                        name=str(name),
                    )
                )
        return threads

    def to_wire(self) -> list[int | str | None]:
        return [self.ident, self.native_id, self.name]

    def ids(self) -> list[int]:
        """Every id samples may carry for this thread (which one depends on the platform)."""
        return [thread_id for thread_id in (self.native_id, self.ident) if thread_id is not None]


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

    @classmethod
    def from_wire(cls, message: WireReader) -> AgentHello:
        return cls(
            token=message.get_str("token", ""),
            pid=message.get_int("pid"),
            executable=message.get_optional_str("executable"),
            argv=message.get_str_list("argv"),
            cwd=message.get_optional_str("cwd"),
            version=message.get_optional_str("version"),
            threads=ThreadName.list_from_wire(message.get_list("threads")),
        )

    def to_wire(self) -> JsonObject:
        return {
            "type": AgentMessageType.HELLO,
            "token": self.token,
            "pid": self.pid,
            "executable": self.executable,
            "argv": self.argv,
            "cwd": self.cwd,
            "version": self.version,
            "threads": [thread.to_wire() for thread in self.threads],
        }
