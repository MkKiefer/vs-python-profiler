"""The time series of a profile."""

from enum import StrEnum


class Track(StrEnum):
    """Mirror of the track names the dashboard reads from ``Delta.tracks``."""

    RSS = "rss"
    """Resident memory of the target in bytes."""
    CPU = "cpu"
    """CPU usage of the target in percent of one core."""
    TRACED = "traced"
    """Bytes tracemalloc currently traces."""
    TRACED_PEAK = "tracedPeak"
    LOOP_LAG = "loopLag"
    """Worst event-loop lag in milliseconds."""
    LOOP_TASKS = "loopTasks"
    """Number of asyncio tasks alive."""
