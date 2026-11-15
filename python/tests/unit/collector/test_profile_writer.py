import gzip
import json
import os
import tempfile
import unittest
from array import array

from _vspyprof.collector.profile_writer import ProfileWriter
from _vspyprof.collector.store.column_snapshot import ColumnSnapshot
from _vspyprof.collector.store.typed_column import TypedColumn


class TestProfileWriter(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "nested", "run.vspyprof")
        self.writer = ProfileWriter()

    def test_write_creates_gzipped_json_in_missing_directory(self) -> None:
        self.writer.write(self.path, {"format": "vspyprof", "markers": [[1.0, "deploy"]]})

        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"format": "vspyprof", "markers": [[1.0, "deploy"]]})

    def test_write_streams_column_snapshots_as_arrays(self) -> None:
        column: TypedColumn[float] = TypedColumn(array("d"))
        values = [i / 8 for i in range(150_000)]  # more than one chunk
        for value in values:
            column.append(value)
        empty: TypedColumn[int] = TypedColumn(array("B"))

        self.writer.write(
            self.path,
            {"samples": {"t": ColumnSnapshot(column, len(column)), "status": ColumnSnapshot(empty, 0)}, "now": 1.5},
        )

        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"samples": {"t": values, "status": []}, "now": 1.5})

    def test_write_returns_file_size(self) -> None:
        size = self.writer.write(self.path, {"format": "vspyprof"})

        self.assertEqual(size, os.path.getsize(self.path))

    def test_write_replaces_existing_file_and_leaves_no_temporary_file(self) -> None:
        self.writer.write(self.path, {"version": 1})

        self.writer.write(self.path, {"version": 2})

        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 2})
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["run.vspyprof"])


if __name__ == "__main__":
    unittest.main()
