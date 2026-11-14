"""What the agent switches on when it starts."""

import json
from dataclasses import dataclass

from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class AgentOptions(WireMessage):
    """The part of the session options the agent applies itself.

    The wire names are those of ``CollectorOptions`` in ``src/shared/protocol.ts``,
    so the extension can hand its whole options object to a launched program.
    """

    tracemalloc: bool = False
    tracemalloc_frames: int = 16
    asyncio_debug: bool = False
    slow_callback_ms: float = 100.0

    @classmethod
    def from_wire(cls, raw: WireReader) -> AgentOptions:
        """Missing or null keys keep their default."""
        defaults = cls()
        return cls(
            tracemalloc=raw.get_bool("tracemalloc", defaults.tracemalloc),
            tracemalloc_frames=max(1, raw.get_int("tracemallocFrames", defaults.tracemalloc_frames)),
            asyncio_debug=raw.get_bool("asyncioDebug", defaults.asyncio_debug),
            slow_callback_ms=raw.get_float("slowCallbackMs", defaults.slow_callback_ms),
        )

    @classmethod
    def from_json(cls, text: str | None) -> AgentOptions:
        """Read options from JSON text; text that is missing or unusable gives the defaults."""
        if not text:
            return cls()
        try:
            return cls.from_wire(WireReader.of(json.loads(text)))
        except ValueError:  # not JSON, or a value of the wrong type
            return cls()

    def to_wire(self) -> JsonObject:
        return {
            "tracemalloc": self.tracemalloc,
            "tracemallocFrames": self.tracemalloc_frames,
            "asyncioDebug": self.asyncio_debug,
            "slowCallbackMs": self.slow_callback_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_wire())
