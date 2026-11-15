import time
import unittest
from unittest.mock import MagicMock, create_autospec

from _vscode_pyprof.collector.frames.frame_classifier import FrameClassifier
from _vscode_pyprof.collector.sampling.gc_recorder import GcRecorder
from _vscode_pyprof.collector.sampling.tachyon import Tachyon
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.stack_table import StackTable
from _vscode_pyprof.collector.store.store import Store
from tests.unit.json_view import JsonView


class TestGcRecorder(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = SessionClock()
        self.store = Store(self.clock, StackTable(FrameClassifier([], [], "/ext")))
        self.tachyon = create_autospec(Tachyon, instance=True)
        self.recorder = GcRecorder(self.tachyon, self.store, self.clock)
        self.started_ns = time.perf_counter_ns() + 1_000_000

    def collection(self, number: int, *, start_ns: int | None = None, duration_ns: int = 2_000_000) -> MagicMock:
        start = self.started_ns if start_ns is None else start_ns
        return MagicMock(
            gen=2, ts_start=start, ts_stop=start + duration_ns, collections=number, collected=40, heap_size=9000
        )

    def recorded(self) -> list[list[float]]:
        rows = JsonView(self.store.full()).get_list("gc")
        return [row for row in rows if isinstance(row, list)]

    def test_record_stores_collection_with_duration_in_milliseconds(self) -> None:
        self.tachyon.gc_stats.return_value = [self.collection(1)]

        self.recorder.record(50.0)

        self.assertEqual(
            self.recorded(), [[round(self.clock.from_perf_counter_ns(self.started_ns), 3), 2.0, 2, 40, 9000]]
        )

    def test_record_stores_each_collection_once(self) -> None:
        self.tachyon.gc_stats.return_value = [self.collection(1)]

        self.recorder.record(50.0)
        self.recorder.record(60.0)

        self.assertEqual(len(self.recorded()), 1)

    def test_record_with_start_time_on_another_clock_uses_current_session_time(self) -> None:
        self.tachyon.gc_stats.return_value = [self.collection(1, start_ns=0)]

        self.recorder.record(50.0)

        self.assertEqual(self.recorded()[0][0], 50.0)

    def test_record_skips_collection_from_before_the_session(self) -> None:
        self.tachyon.gc_stats.return_value = [self.collection(1, start_ns=self.started_ns - 500_000_000)]

        self.recorder.record(50.0)

        self.assertEqual(self.recorded(), [])

    def test_record_with_stop_before_start_stores_zero_duration(self) -> None:
        self.tachyon.gc_stats.return_value = [self.collection(1, duration_ns=-5)]

        self.recorder.record(50.0)

        self.assertEqual(self.recorded()[0][1], 0.0)

    def test_record_when_target_cannot_be_read_stores_nothing(self) -> None:
        self.tachyon.gc_stats.side_effect = OSError("torn read")

        self.recorder.record(50.0)

        self.assertEqual(self.recorded(), [])


if __name__ == "__main__":
    unittest.main()
