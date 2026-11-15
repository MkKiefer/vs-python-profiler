"""Attaches a sampler to a process."""

from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.sampling.gc_recorder import GcRecorder
from _vspyprof.collector.sampling.process_stats_reader_factory import ProcessStatsReaderFactory
from _vspyprof.collector.sampling.sampler import Sampler
from _vspyprof.collector.sampling.sampler_listener import SamplerListener
from _vspyprof.collector.sampling.tachyon import Tachyon
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.store import Store


class SamplerFactory:
    """Builds the sampler of a session once the target's pid is known (the seam tests replace)."""

    def __init__(self, store: Store, clock: SessionClock, stats_readers: ProcessStatsReaderFactory) -> None:
        self._store = store
        self._clock = clock
        self._stats_readers = stats_readers

    def create(self, pid: int, options: CollectorOptions, listener: SamplerListener) -> Sampler:
        """Attach to ``pid``. Raises ``TachyonError`` if the process cannot be read."""
        tachyon = Tachyon(pid, native=options.native, gc=options.gc)
        return Sampler(
            tachyon=tachyon,
            store=self._store,
            clock=self._clock,
            stats_reader=self._stats_readers.for_pid(tachyon.pid),
            gc_recorder=GcRecorder(tachyon, self._store, self._clock),
            options=options,
            listener=listener,
        )
