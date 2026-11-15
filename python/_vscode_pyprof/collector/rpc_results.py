"""What the collector answers to the extension's requests.

Mirror of the ``result`` types of ``CollectorRequests`` in ``src/shared/protocol.ts``.
"""

from dataclasses import dataclass, field

from _vscode_pyprof.collector.protocol import SessionState
from _vscode_pyprof.collector.store.sampling_stats import SamplingStats
from _vscode_pyprof.wire import WireMessage, wire


@dataclass(frozen=True, slots=True)
class Features(WireMessage):
    """What the target's interpreter supports."""

    gc_stats: bool
    remote_exec: bool
    """The agent can be injected into a running program."""
    async_aware: bool


@dataclass(frozen=True, slots=True)
class InitializeResult(WireMessage):
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


@dataclass(frozen=True, slots=True)
class AttachResult(WireMessage):
    pid: int
    """The sampled process; on Windows it can differ from the requested one (venv launcher)."""
    injected: bool
    inject_error: str | None
    """Why the agent could not be injected; sampling runs regardless."""


@dataclass(frozen=True, slots=True)
class StatusResult(WireMessage):
    state: SessionState
    pid: int | None
    agent: bool
    stats: SamplingStats


@dataclass(frozen=True, slots=True)
class SnapshotResult(WireMessage):
    snapshot_id: int = field(metadata=wire("id"))
    total_size: int
    entries: int
    """Number of call stacks the snapshot lists."""


@dataclass(frozen=True, slots=True)
class SaveResult(WireMessage):
    path: str
    size_bytes: int = field(metadata=wire("bytes"))
