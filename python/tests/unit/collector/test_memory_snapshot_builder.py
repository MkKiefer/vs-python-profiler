import os
import unittest

from _vscode_pyprof.collector.frames.frame_classifier import FrameClassifier
from _vscode_pyprof.collector.frames.func_resolver import FuncResolver
from _vscode_pyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
from _vscode_pyprof.collector.store.memory_snapshot import AllocationSite
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.stack_table import StackTable
from _vscode_pyprof.collector.store.store import Store
from _vscode_pyprof.wire import JsonObject, WireError, WireReader

ROOT = os.path.abspath(os.sep)
INTERNAL_DIR = os.path.join(ROOT, "ext", "_vscode_pyprof")
LAUNCHER = os.path.join(INTERNAL_DIR, "launcher.py")


class TestMemorySnapshotBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = SessionClock()
        self.store = Store(self.clock, StackTable(FrameClassifier([], [], INTERNAL_DIR)))
        self.builder = MemorySnapshotBuilder(self.store, self.clock, FuncResolver())

    @staticmethod
    def reply(top: list[object], **overrides: object) -> WireReader:
        fields: JsonObject = {
            "t": 0.0,
            "totalSize": 300,
            "totalCount": 3,
            "otherSize": 20,
            "otherCount": 1,
            "traced": 400,
            "peak": 500,
            "takeMs": 1.5,
            "top": top,
        }
        fields.update(overrides)
        return WireReader(fields)

    def test_build_copies_totals_from_reply(self) -> None:
        snapshot = self.builder.build(self.reply([]), "A")

        self.assertEqual(
            (snapshot.label, snapshot.total_size, snapshot.total_count, snapshot.other_size, snapshot.other_count),
            ("A", 300, 3, 20, 1),
        )
        self.assertEqual((snapshot.traced, snapshot.peak, snapshot.take_ms), (400, 500, 1.5))

    def test_build_without_label_numbers_snapshots(self) -> None:
        first = self.builder.build(self.reply([]), None)
        second = self.builder.build(self.reply([]), None)

        self.assertEqual((first.label, second.label), ("Snapshot 1", "Snapshot 2"))

    def test_build_converts_agent_time_to_session_time(self) -> None:
        snapshot = self.builder.build(self.reply([], t=5.0), "A")

        self.assertEqual(snapshot.t, round(self.clock.from_perf_counter(5.0), 2))

    def test_build_without_take_time_leaves_it_unknown(self) -> None:
        snapshot = self.builder.build(self.reply([], takeMs=None), "A")

        self.assertIsNone(snapshot.take_ms)

    def test_build_resolves_function_names_of_allocation_sites(self) -> None:
        line = self.setUp.__code__.co_firstlineno + 1

        snapshot = self.builder.build(self.reply([[[[__file__, line]], 300, 3]]), "A")

        frames = WireReader(self.store.full()).get_list("frames")
        self.assertEqual(snapshot.sites, (AllocationSite(stack=0, size=300, count=3),))
        self.assertEqual(frames, [[__file__, "TestMemorySnapshotBuilder.setUp", line, 0]])

    def test_build_skips_malformed_entries(self) -> None:
        snapshot = self.builder.build(self.reply(["oops", [[], 1], [[["app.py", 1]], "big", 1]]), "A")

        self.assertEqual(snapshot.sites, ())

    def test_build_skips_sites_allocated_by_the_launcher_alone(self) -> None:
        self.store.configure(strip_launcher=True)

        snapshot = self.builder.build(self.reply([[[[LAUNCHER, 1]], 10, 1]]), "A")

        self.assertEqual(snapshot.sites, ())

    def test_build_with_incomplete_reply_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            self.builder.build(WireReader({"t": 0.0, "top": []}), "A")


if __name__ == "__main__":
    unittest.main()
