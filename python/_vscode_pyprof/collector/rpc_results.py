"""What the collector answers to the extension's requests.

Mirror of the ``result`` types of ``CollectorRequests`` in ``src/shared/protocol.ts``.
"""

from dataclasses import dataclass

from _vscode_pyprof.collector.protocol import SessionState
from _vscode_pyprof.collector.store.sampling_stats import SamplingStats
from _vscode_pyprof.wire import JsonObject, WireWritable


@dataclass(frozen=True, slots=True)
class Features(WireWritable):
    """What the target's interpreter supports."""

    gc_stats: bool
    remote_exec: bool
    """The agent can be injected into a running program."""
    async_aware: bool

    def to_wire(self) -> JsonObject:
        return {"gcStats": self.gc_stats, "remoteExec": self.remote_exec, "asyncAware": self.async_aware}


@dataclass(frozen=True, slots=True)
class InitializeResult(WireWritable):
    protocol: int
    python: str
    executable: str
    platform: str
    pid: int
    """The collector process."""
    agent_address: str
    """``host:port:token`` for an agent to connect back; the extension passes it to a launched program."""
    package_dir: str
    features: Features

    def to_wire(self) -> JsonObject:
        return {
            "protocol": self.protocol,
            "python": self.python,
            "executable": self.executable,
            "platform": self.platform,
            "pid": self.pid,
            "agentAddress": self.agent_address,
            "packageDir": self.package_dir,
            "features": self.features.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class AttachResult(WireWritable):
    pid: int
    """The sampled process; on Windows it can differ from the requested one (venv launcher)."""
    injected: bool
    inject_error: str | None
    """Why the agent could not be injected; sampling runs regardless."""

    def to_wire(self) -> JsonObject:
        return self._omit_none({"pid": self.pid, "injected": self.injected, "injectError": self.inject_error})


@dataclass(frozen=True, slots=True)
class StatusResult(WireWritable):
    state: SessionState
    pid: int | None
    agent: bool
    stats: SamplingStats

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {"state": self.state, "pid": self.pid, "agent": self.agent, "stats": self.stats.to_wire()}
        )


@dataclass(frozen=True, slots=True)
class SnapshotResult(WireWritable):
    snapshot_id: int
    total_size: int
    entries: int
    """Number of call stacks the snapshot lists."""

    def to_wire(self) -> JsonObject:
        return {"id": self.snapshot_id, "totalSize": self.total_size, "entries": self.entries}


@dataclass(frozen=True, slots=True)
class SaveResult(WireWritable):
    path: str
    size_bytes: int

    def to_wire(self) -> JsonObject:
        return {"path": self.path, "bytes": self.size_bytes}
