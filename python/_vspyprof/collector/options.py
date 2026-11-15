"""Profiling options of one collector session."""

from dataclasses import dataclass, replace

from _vspyprof.agent_protocol.options import AgentOptions


@dataclass(frozen=True, slots=True)
class CollectorOptions:
    """Mirror of ``CollectorOptions`` in ``src/shared/protocol.ts``; keys the extension leaves out keep their default.

    The extension raises ``rate_hz`` and ``tracemalloc_frames`` to at least one
    (settings and launch configs may hold any number).
    """

    rate_hz: int = 1000
    native: bool = False
    gc: bool = True
    async_aware: bool = True
    tracemalloc: bool = False
    tracemalloc_frames: int = 16
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
