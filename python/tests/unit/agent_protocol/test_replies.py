import unittest

from _vscode_pyprof.agent_protocol.replies import (
    Acknowledgement,
    Allocation,
    AsyncioDebugStatus,
    HeapSnapshot,
    ObjectCounts,
    Pong,
    SourceLine,
    TracingStatus,
    TypeCount,
)
from _vscode_pyprof.wire import WireError


class TestTracingStatus(unittest.TestCase):
    def test_to_wire_while_tracing_includes_frames(self) -> None:
        self.assertEqual(TracingStatus(True, 16).to_wire(), {"tracing": True, "frames": 16})

    def test_to_wire_when_stopped_leaves_frames_out(self) -> None:
        self.assertEqual(TracingStatus(False).to_wire(), {"tracing": False})

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        for status in (TracingStatus(True, 16), TracingStatus(False)):
            with self.subTest(status=status):
                self.assertEqual(TracingStatus.from_wire(status.to_wire()), status)


class TestAsyncioDebugStatus(unittest.TestCase):
    def test_to_wire_round_trips_through_from_wire(self) -> None:
        status = AsyncioDebugStatus(enabled=True, loops=2)

        self.assertEqual(AsyncioDebugStatus.from_wire(status.to_wire()), status)


class TestAllocation(unittest.TestCase):
    def test_to_wire_nests_traceback_size_and_count(self) -> None:
        allocation = Allocation([SourceLine("app.py", 3), SourceLine("lib.py", 9)], size=300, count=3)

        self.assertEqual(allocation.to_wire(), [[["app.py", 3], ["lib.py", 9]], 300, 3])

    def test_from_wire_round_trips_to_wire(self) -> None:
        allocation = Allocation([SourceLine("app.py", 3)], size=300, count=3)

        self.assertEqual(Allocation.from_wire(allocation.to_wire()), allocation)

    def test_from_wire_with_other_shape_raises_wire_error(self) -> None:
        for raw in ("oops", [[], 1], [[["app.py", 1]], "big", 1], [None, 1, 1]):
            with self.subTest(raw=raw), self.assertRaises(WireError):
                Allocation.from_wire(raw)

    def test_from_wire_with_frame_of_another_shape_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.traceback\[1\] must have 2 items"):
            Allocation.from_wire([[["app.py", 3], ["broken"]], 10, 1])


class TestHeapSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = HeapSnapshot(
            perf_counter=5.0,
            total_size=300,
            total_count=3,
            other_size=20,
            other_count=1,
            traced=400,
            peak=500,
            take_ms=1.5,
            top=[Allocation([SourceLine("app.py", 3)], 280, 2)],
        )

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        self.assertEqual(HeapSnapshot.from_wire(self.snapshot.to_wire()), self.snapshot)

    def test_from_wire_without_take_time_leaves_it_unknown(self) -> None:
        wire = self.snapshot.to_wire()
        wire["takeMs"] = None

        self.assertIsNone(HeapSnapshot.from_wire(wire).take_ms)

    def test_from_wire_with_missing_total_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            HeapSnapshot.from_wire({"t": 0.0, "top": []})


class TestObjectCounts(unittest.TestCase):
    def test_to_wire_lists_type_name_and_count_pairs(self) -> None:
        counts = ObjectCounts(3.0, [TypeCount("dict", 10), TypeCount("app.Order", 4)])

        self.assertEqual(counts.to_wire(), {"t": 3.0, "counts": [["dict", 10], ["app.Order", 4]]})

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        counts = ObjectCounts(3.0, [TypeCount("dict", 10)])

        self.assertEqual(ObjectCounts.from_wire(counts.to_wire()), counts)

    def test_from_wire_with_entry_of_another_shape_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.counts\[1\] must be an array"):
            ObjectCounts.from_wire({"t": 3.0, "counts": [["dict", 10], "x"]})


class TestSimpleReplies(unittest.TestCase):
    def test_pong_to_wire_reports_time_and_pid(self) -> None:
        self.assertEqual(Pong(2.5, 4242).to_wire(), {"t": 2.5, "pid": 4242})

    def test_acknowledgement_to_wire_reports_ok(self) -> None:
        self.assertEqual(Acknowledgement().to_wire(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
