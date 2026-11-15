"""Profiling options of one collector session."""

from dataclasses import dataclass, field, replace

from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.wire import WireMessage, wire


@dataclass(frozen=True, slots=True)
class CollectorOptions(WireMessage):
    """Mirror of ``CollectorOptions`` in ``src/shared/protocol.ts``; missing or null keys keep their default."""

    rate_hz: int = field(default=1000, metadata=wire(at_least=1))
    native: bool = False
    gc: bool = True
    async_aware: bool = True
    tracemalloc: bool = False
    tracemalloc_frames: int = field(default=16, metadata=wire(at_least=1))
    asyncio_debug: bool = False
    slow_callback_ms: float = 100.0
    strip_launcher: bool = False
    blocking: bool = False

    def agent_options(self) -> AgentOptions:
        """The subset the in-process agent applies when it starts."""
        return AgentOptions(
            tracemalloc=self.tracemalloc,
            tracemalloc_frames=self.tracemalloc_frames,
            asyncio_debug=self.asyncio_debug,
            slow_callback_ms=self.slow_callback_ms,
        )

    def with_tracemalloc(self, enabled: bool) -> CollectorOptions:
        return replace(self, tracemalloc=enabled)

    def with_asyncio_debug(self, enabled: bool) -> CollectorOptions:
        return replace(self, asyncio_debug=enabled)
