"""Records the target's garbage collections."""

import time

from _vspyprof.collector.sampling.tachyon import Tachyon
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.store import Store


class GcRecorder:
    """Polls the target's GC statistics and stores every collection once.

    The interpreter reports its most recent collections on every poll, so the
    ones already stored are remembered.
    """

    _SEEN_LIMIT = 10_000
    _CLOCK_SKEW_NS = 60e9  # a start time this far in the future is on another clock
    _CLOCK_SKEW_MS = 1000.0

    def __init__(self, tachyon: Tachyon, store: Store, clock: SessionClock) -> None:
        self._tachyon = tachyon
        self._store = store
        self._clock = clock
        self._seen: dict[tuple[int, int, int], None] = {}  # insertion ordered, oldest first

    def record(self, t: float) -> None:
        """Store the collections that finished since the previous call; ``t`` is the current session time."""
        try:
            collections = self._tachyon.gc_stats()
        except Tachyon.READ_ERRORS:
            return
        now_ns = time.perf_counter_ns()
        for collection in collections:
            key = (collection.gen, collection.ts_start, collection.collections)
            if key in self._seen:
                continue
            self._seen[key] = None
            started = self._clock.from_perf_counter_ns(collection.ts_start)
            # ts_start is CLOCK_MONOTONIC on Linux; if the clocks differ, use the arrival time
            if (
                collection.ts_start <= 0
                or collection.ts_start > now_ns + self._CLOCK_SKEW_NS
                or started < -self._CLOCK_SKEW_MS
            ):
                started = t
            if started < 0:
                continue  # collected before the session started
            elapsed_ns = collection.ts_stop - collection.ts_start
            self._store.add_gc(
                started, max(0.0, elapsed_ns / 1e6), collection.gen, collection.collected, collection.heap_size
            )
        while len(self._seen) > self._SEEN_LIMIT:
            del self._seen[next(iter(self._seen))]
