"""What the sampler reports to its owner."""

from abc import ABC, abstractmethod

from _vspyprof.collector.protocol import StopReason


class SamplerListener(ABC):
    """Receives what the sampler notices about the target process."""

    @abstractmethod
    def on_target_exit(self, reason: StopReason) -> None: ...

    @abstractmethod
    def on_sampler_error(self, message: str) -> None:
        """The sampling loop failed unexpectedly and has stopped; ``message`` says why."""

    @abstractmethod
    def on_children(self, pids: list[int]) -> None: ...
