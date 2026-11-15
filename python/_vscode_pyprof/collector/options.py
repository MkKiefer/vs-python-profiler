"""Profiling options of one collector session."""

from dataclasses import dataclass, replace
from typing import Self

from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True, slots=True)
class CollectorOptions(WireMessage):
    """Mirror of ``CollectorOptions`` in ``src/shared/protocol.ts``; missing or null keys keep their default."""

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

    def to_wire(self) -> JsonObject:
        return {
            "rateHz": self.rate_hz,
            "native": self.native,
            "gc": self.gc,
            "asyncAware": self.async_aware,
            "tracemalloc": self.tracemalloc,
            "tracemallocFrames": self.tracemalloc_frames,
            "asyncioDebug": self.asyncio_debug,
            "slowCallbackMs": self.slow_callback_ms,
            "stripLauncher": self.strip_launcher,
            "blocking": self.blocking,
        }

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        """Rates and traceback depths below one are raised to one (settings may hold any number)."""
        message = WireReader.for_object(raw, where)
        defaults = cls()
        return cls(
            rate_hz=max(1, message.get_or("rateHz", int, defaults.rate_hz)),
            native=message.get_or("native", bool, defaults.native),
            gc=message.get_or("gc", bool, defaults.gc),
            async_aware=message.get_or("asyncAware", bool, defaults.async_aware),
            tracemalloc=message.get_or("tracemalloc", bool, defaults.tracemalloc),
            tracemalloc_frames=max(1, message.get_or("tracemallocFrames", int, defaults.tracemalloc_frames)),
            asyncio_debug=message.get_or("asyncioDebug", bool, defaults.asyncio_debug),
            slow_callback_ms=message.get_or("slowCallbackMs", float, defaults.slow_callback_ms),
            strip_launcher=message.get_or("stripLauncher", bool, defaults.strip_launcher),
            blocking=message.get_or("blocking", bool, defaults.blocking),
        )
