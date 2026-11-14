"""Profiling options of one collector session."""

from dataclasses import dataclass, replace

from _vscode_pyprof.wire import JsonObject, WireReader


@dataclass(frozen=True, slots=True)
class CollectorOptions:
    """Mirror of ``CollectorOptions`` in ``src/shared/protocol.ts`` (camelCase on the wire)."""

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

    @classmethod
    def from_wire(cls, raw: WireReader) -> CollectorOptions:
        """Build options from a JSON object; missing or null keys keep their default."""
        defaults = cls()
        return cls(
            rate_hz=max(1, raw.get_int("rateHz", defaults.rate_hz)),
            native=raw.get_bool("native", defaults.native),
            gc=raw.get_bool("gc", defaults.gc),
            async_aware=raw.get_bool("asyncAware", defaults.async_aware),
            tracemalloc=raw.get_bool("tracemalloc", defaults.tracemalloc),
            tracemalloc_frames=max(1, raw.get_int("tracemallocFrames", defaults.tracemalloc_frames)),
            asyncio_debug=raw.get_bool("asyncioDebug", defaults.asyncio_debug),
            slow_callback_ms=raw.get_float("slowCallbackMs", defaults.slow_callback_ms),
            strip_launcher=raw.get_bool("stripLauncher", defaults.strip_launcher),
            blocking=raw.get_bool("blocking", defaults.blocking),
        )

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

    def agent_options(self) -> JsonObject:
        """The subset the in-process agent applies when it starts."""
        return {
            "tracemalloc": self.tracemalloc,
            "tracemallocFrames": self.tracemalloc_frames,
            "asyncioDebug": self.asyncio_debug,
            "slowCallbackMs": self.slow_callback_ms,
        }

    def with_tracemalloc(self, enabled: bool) -> CollectorOptions:
        return replace(self, tracemalloc=enabled)

    def with_asyncio_debug(self, enabled: bool) -> CollectorOptions:
        return replace(self, asyncio_debug=enabled)
