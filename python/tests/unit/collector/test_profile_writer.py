import gzip
import json
import os
import tempfile
import unittest

from _vscode_pyprof.collector.profile_writer import ProfileWriter


class TestProfileWriter(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "nested", "run.pyprof")
        self.writer = ProfileWriter()

    def test_write_creates_gzipped_json_in_missing_directory(self) -> None:
        self.writer.write(self.path, {"format": "pyprof", "markers": [[1.0, "deploy"]]})

        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"format": "pyprof", "markers": [[1.0, "deploy"]]})

    def test_write_returns_file_size(self) -> None:
        size = self.writer.write(self.path, {"format": "pyprof"})

        self.assertEqual(size, os.path.getsize(self.path))

    def test_write_replaces_existing_file_and_leaves_no_temporary_file(self) -> None:
        self.writer.write(self.path, {"version": 1})

        self.writer.write(self.path, {"version": 2})

        with gzip.open(self.path, "rt", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 2})
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["run.pyprof"])


if __name__ == "__main__":
    unittest.main()
