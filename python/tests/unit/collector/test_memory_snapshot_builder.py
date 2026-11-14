import os
import unittest
from dataclasses import replace

from _vscode_pyprof.agent_protocol.replies import Allocation, HeapSnapshot, SourceLine
from _vscode_pyprof.collector.frames.frame_classifier import FrameClassifier
from _vscode_pyprof.collector.frames.func_resolver import FuncResolver
from _vscode_pyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.collector.store.memory_snapshot import AllocationSite
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.stack_table import StackTable
from _vscode_pyprof.collector.store.store import Store
from _vscode_pyprof.wire import WireReader

ROOT = os.path.abspath(os.sep)
INTERNAL_DIR = os.path.join(ROOT, "ext", "_vscode_pyprof")
LAUNCHER = os.path.join(INTERNAL_DIR, "launcher.py")


class TestMemorySnapshotBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = SessionClock()
        self.store = Store(self.clock, StackTable(FrameClassifier([], [], INTERNAL_DIR)))
        self.builder = MemorySnapshotBuilder(self.store, self.clock, FuncResolver())

    @staticmethod
    def heap(*top: Allocation) -> HeapSnapshot:
        return HeapSnapshot(
            perf_counter=0.0,
            total_size=300,
            total_count=3,
            other_size=20,
            other_count=1,
            traced=400,
            peak=500,
            take_ms=1.5,
            top=list(top),
        )

    def test_build_copies_totals_from_heap_snapshot(self) -> None:
        snapshot = self.builder.build(self.heap(), "A")

        self.assertEqual(
            (snapshot.label, snapshot.total_size, snapshot.total_count, snapshot.other_size, snapshot.other_count),
            ("A", 300, 3, 20, 1),
        )
        self.assertEqual((snapshot.traced, snapshot.peak, snapshot.take_ms), (400, 500, 1.5))

    def test_build_without_label_numbers_snapshots(self) -> None:
        first = self.builder.build(self.heap(), None)
        second = self.builder.build(self.heap(), None)

        self.assertEqual((first.label, second.label), ("Snapshot 1", "Snapshot 2"))

    def test_build_converts_agent_time_to_session_time(self) -> None:
        snapshot = self.builder.build(replace(self.heap(), perf_counter=5.0), "A")

        self.assertEqual(snapshot.t, round(self.clock.from_perf_counter(5.0), 2))

    def test_build_resolves_function_names_of_allocation_sites(self) -> None:
        line = self.setUp.__code__.co_firstlineno + 1

        snapshot = self.builder.build(self.heap(Allocation([SourceLine(__file__, line)], 300, 3)), "A")

        frames = WireReader(self.store.full()).get_list("frames")
        self.assertEqual(snapshot.sites, (AllocationSite(stack=0, size=300, count=3),))
        self.assertEqual(frames, [[__file__, "TestMemorySnapshotBuilder.setUp", line, 0]])

    def test_build_gives_allocations_with_the_same_traceback_the_same_stack(self) -> None:
        traceback = [SourceLine(__file__, 1)]

        snapshot = self.builder.build(self.heap(Allocation(traceback, 10, 1), Allocation(traceback, 20, 2)), "A")

        self.assertEqual([site.stack for site in snapshot.sites], [0, 0])

    def test_build_skips_sites_allocated_by_the_launcher_alone(self) -> None:
        self.store.describe_session(CollectorOptions(strip_launcher=True), None)

        snapshot = self.builder.build(self.heap(Allocation([SourceLine(LAUNCHER, 1)], 10, 1)), "A")

        self.assertEqual(snapshot.sites, ())

    def test_build_skips_allocations_without_traceback(self) -> None:
        snapshot = self.builder.build(self.heap(Allocation([], 10, 1)), "A")

        self.assertEqual(snapshot.sites, ())


if __name__ == "__main__":
    unittest.main()
