import tracemalloc
import unittest

from _vscode_pyprof.target.memory_probe import MemoryProbe
from _vscode_pyprof.wire import WireReader


@unittest.skipIf(tracemalloc.is_tracing(), "the test run itself is traced")
class TestMemoryProbe(unittest.TestCase):
    def setUp(self) -> None:
        self.probe = MemoryProbe()
        self.addCleanup(tracemalloc.stop)

    def test_start_tracing_starts_tracemalloc_with_requested_frames(self) -> None:
        result = WireReader(self.probe.start_tracing(5))

        self.assertTrue(tracemalloc.is_tracing())
        self.assertEqual((result.get_bool("tracing", False), result.get_int("frames")), (True, 5))

    def test_start_tracing_when_program_already_traces_keeps_its_settings(self) -> None:
        tracemalloc.start(3)

        result = WireReader(self.probe.start_tracing(9))

        self.assertEqual(result.get_int("frames"), 3)

    def test_stop_tracing_stops_tracemalloc(self) -> None:
        self.probe.start_tracing(5)

        result = WireReader(self.probe.stop_tracing())

        self.assertFalse(tracemalloc.is_tracing())
        self.assertFalse(result.get_bool("tracing", True))

    def test_release_stops_tracing_the_probe_started(self) -> None:
        self.probe.start_tracing(5)

        self.probe.release()

        self.assertFalse(tracemalloc.is_tracing())

    def test_release_leaves_tracing_the_program_started(self) -> None:
        tracemalloc.start(3)
        self.probe.start_tracing(5)

        self.probe.release()

        self.assertTrue(tracemalloc.is_tracing())

    def test_traced_memory_without_tracing_returns_none(self) -> None:
        self.assertIsNone(self.probe.traced_memory())

    def test_traced_memory_while_tracing_returns_current_and_peak(self) -> None:
        self.probe.start_tracing(5)
        block = bytearray(256 * 1024)

        traced = self.probe.traced_memory()

        assert traced is not None
        current, peak = traced
        self.assertGreaterEqual(current, len(block))
        self.assertGreaterEqual(peak, current)

    def test_snapshot_without_tracing_raises_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self.probe.snapshot(10)

        self.assertIn("start memory tracing first", str(ctx.exception))

    def test_snapshot_reports_allocation_with_its_traceback(self) -> None:
        self.probe.start_tracing(5)
        block = bytearray(512 * 1024)

        snapshot = WireReader(self.probe.snapshot(50))

        tracebacks = [entry[0] for entry in snapshot.get_list("top") if isinstance(entry, list)]
        files = {frame[0] for traceback in tracebacks for frame in traceback}
        self.assertIn(__file__, files)
        self.assertGreaterEqual(snapshot.get_int("totalSize"), len(block))

    def test_snapshot_with_limit_sums_the_rest_as_other(self) -> None:
        self.probe.start_tracing(5)
        small = bytearray(1024)  # two lines, so two tracebacks
        large = bytearray(4096)

        snapshot = WireReader(self.probe.snapshot(1))

        self.assertEqual(len(snapshot.get_list("top")), 1)
        self.assertGreater(snapshot.get_int("otherSize"), 0)
        self.assertLess(len(small), len(large))

    def test_object_counts_returns_most_common_types_first(self) -> None:
        counts = WireReader(self.probe.object_counts(5)).get_list("counts")

        numbers = [entry[1] for entry in counts if isinstance(entry, (list, tuple))]
        self.assertEqual(len(counts), 5)
        self.assertEqual(numbers, sorted(numbers, reverse=True))


if __name__ == "__main__":
    unittest.main()
