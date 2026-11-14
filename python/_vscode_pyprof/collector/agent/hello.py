"""The first message of an agent."""

from dataclasses import dataclass

from _vscode_pyprof.collector.agent.thread_name import ThreadName
from _vscode_pyprof.wire import WireReader


@dataclass(frozen=True, slots=True)
class AgentHello:
    """What the agent tells us about its process when it connects."""

    pid: int
    executable: str | None
    argv: list[str]
    cwd: str | None
    threads: list[ThreadName]

    @classmethod
    def from_wire(cls, message: WireReader) -> AgentHello:
        return cls(
            pid=message.get_int("pid"),
            executable=message.get_optional_str("executable"),
            argv=message.get_str_list("argv"),
            cwd=message.get_optional_str("cwd"),
            threads=ThreadName.list_from_wire(message.get_list("threads")),
        )
