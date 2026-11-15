"""The one clock every table of a profile shares."""

import time


class SessionClock:
    """Milliseconds since the session started, on ``time.perf_counter``'s time base.

    The agent reports ``time.perf_counter()`` readings taken inside the target;
    they convert directly because that clock is system-wide.
    """

    def __init__(self) -> None:
        self._origin = time.perf_counter()
        self._origin_ns = time.perf_counter_ns()

    def now(self) -> float:
        return self.from_perf_counter(time.perf_counter())

    def from_perf_counter(self, seconds: float) -> float:
        """Convert a ``time.perf_counter()`` reading into session milliseconds."""
        return (seconds - self._origin) * 1000.0

    def from_perf_counter_ns(self, nanoseconds: int) -> float:
        """Convert a ``time.perf_counter_ns()`` reading into session milliseconds."""
        return (nanoseconds - self._origin_ns) / 1e6
