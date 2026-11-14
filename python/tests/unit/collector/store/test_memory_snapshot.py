import unittest

from _vscode_pyprof.collector.store.memory_snapshot import AllocationSite, MemorySnapshot


class TestMemorySnapshot(unittest.TestCase):
    def test_to_wire_flattens_sites_into_entries(self) -> None:
        snapshot = MemorySnapshot(
            snapshot_id=1,
            label="A",
            t=12.5,
            total_size=300,
            total_count=3,
            other_size=0,
            other_count=0,
            traced=400,
            peak=500,
            take_ms=1.5,
            sites=(AllocationSite(stack=4, size=200, count=2), AllocationSite(stack=7, size=100, count=1)),
        )

        wire = snapshot.to_wire()

        self.assertEqual(wire["entries"], [[4, 200, 2], [7, 100, 1]])
        self.assertEqual((wire["id"], wire["label"], wire["totalSize"]), (1, "A", 300))


if __name__ == "__main__":
    unittest.main()
