import contextlib
import io
import itertools
import threading
import time
import unittest
from _remote_debugging import FrameInfo, InterpreterInfo, LocationInfo, ThreadInfo
from unittest.mock import create_autospec

from _vspyprof.collector.frames.frame_classifier import FrameClassifier
from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.protocol import StopReason
from _vspyprof.collector.sampling.gc_recorder import GcRecorder
from _vspyprof.collector.sampling.process_stats import ProcessStats, ProcessStatsReader
from _vspyprof.collector.sampling.sampler import Sampler
from _vspyprof.collector.sampling.sampler_listener import SamplerListener
from _vspyprof.collector.sampling.tachyon import Tachyon
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.stack_table import StackTable
from _vspyprof.collector.store.store import Store
from tests.unit.torn_text import TornText


class TestSampler(unittest.TestCase):
    _WAIT = 5.0

    def setUp(self) -> None:
        clock = SessionClock()
        self.store = Store(clock, StackTable(FrameClassifier([], [], "/ext")))
        self.tachyon = create_autospec(Tachyon, instance=True)
        self.tachyon.sample_threads.return_value = []
        self.tachyon.python_children.return_value = []
        self.stats_reader = create_autospec(ProcessStatsReader, instance=True)
        self.stats_reader.read.return_value = ProcessStats(1024, 0.0)
        self.listener = create_autospec(SamplerListener, instance=True)
        self.finished = threading.Event()
        self.listener.on_sampler_error.side_effect = lambda message: self.finished.set()
        self.listener.on_target_exit.side_effect = lambda reason: self.finished.set()
        self.sampler = Sampler(
            tachyon=self.tachyon,
            store=self.store,
            clock=clock,
            stats_reader=self.stats_reader,
            gc_recorder=create_autospec(GcRecorder, instance=True),
            options=CollectorOptions(rate_hz=200, async_aware=False),
            listener=self.listener,
        )
        self.addCleanup(self.sampler.stop)

    def test_unexpected_error_in_periodic_job_reports_sampler_error(self) -> None:
        self.stats_reader.read.side_effect = RuntimeError("reader broke")
        errors = io.StringIO()

        with contextlib.redirect_stderr(errors):
            self.sampler.start()
            self.assertTrue(self.finished.wait(self._WAIT))

        self.assertIn("RuntimeError: reader broke", errors.getvalue())
        self.listener.on_sampler_error.assert_called_once_with("Sampling stopped: RuntimeError: reader broke")
        self.listener.on_target_exit.assert_not_called()
        self.stats_reader.close.assert_called_once_with()

    def test_torn_frame_text_is_discarded_and_sampling_goes_on(self) -> None:
        def threads(filename: str) -> list[InterpreterInfo]:
            frame = FrameInfo((filename, LocationInfo((1, 1, 0, 0)), "main", None))
            return [InterpreterInfo((0, [ThreadInfo((1, 0, [frame]))]))]

        self.tachyon.sample_threads.side_effect = itertools.chain(
            [threads(TornText("/srv/app.py"))], itertools.repeat(threads("/srv/app.py"))
        )
        self.tachyon.is_alive.return_value = True

        self.sampler.start()
        deadline = time.monotonic() + self._WAIT
        while self.store.stats().samples < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.sampler.stop()

        self.assertGreaterEqual(self.store.stats().samples, 5)
        self.assertEqual(self.store.stats().errors, 1)
        self.listener.on_sampler_error.assert_not_called()

    def test_target_gone_reports_target_exit(self) -> None:
        self.tachyon.sample_threads.side_effect = ProcessLookupError()

        self.sampler.start()

        self.assertTrue(self.finished.wait(self._WAIT))
        self.listener.on_target_exit.assert_called_once_with(StopReason.EXITED)
        self.listener.on_sampler_error.assert_not_called()

    def test_stop_ends_loop_without_reporting(self) -> None:
        self.sampler.start()

        self.sampler.stop()

        self.listener.on_target_exit.assert_not_called()
        self.listener.on_sampler_error.assert_not_called()
        self.assertGreater(self.store.stats().samples, 0)


if __name__ == "__main__":
    unittest.main()
