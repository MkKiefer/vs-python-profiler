"""How well the sampler keeps up."""

from dataclasses import dataclass

from _vscode_pyprof.wire import JsonObject


@dataclass(frozen=True, slots=True)
class SamplingStats:
    samples: int
    """Sampling ticks recorded."""
    errors: int
    """Ticks discarded because the stack changed while it was read."""
    rate_hz: float
    """The rate actually achieved, which may be below the requested one."""

    def to_profile(self) -> JsonObject:
        return {"samples": self.samples, "errors": self.errors, "rateHz": self.rate_hz}
