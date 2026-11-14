"""How well the sampler keeps up."""

from dataclasses import dataclass

from _vscode_pyprof.wire import JsonObject, WireMessage


@dataclass(frozen=True, slots=True)
class SamplingStats(WireMessage):
    samples: int
    """Sampling ticks recorded."""
    errors: int
    """Ticks discarded because the stack changed while it was read."""
    rate_hz: float
    """The rate actually achieved, which may be below the requested one."""

    def to_wire(self) -> JsonObject:
        return {"samples": self.samples, "errors": self.errors, "rateHz": self.rate_hz}
