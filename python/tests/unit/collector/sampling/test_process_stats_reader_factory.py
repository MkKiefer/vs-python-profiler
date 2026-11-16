import os
import sys
import time
import unittest

from _vspyprof.collector.sampling.linux_stats_reader import LinuxProcessStatsReader
from _vspyprof.collector.sampling.process_stats import ProcessStatsReader
from _vspyprof.collector.sampling.process_stats_reader_factory import ProcessStatsReaderFactory
from _vspyprof.collector.sampling.ps_stats_reader import PsProcessStatsReader
from _vspyprof.collector.sampling.windows_stats_reader import WindowsProcessStatsReader


class TestProcessStatsReaderFactory(unittest.TestCase):
    def test_for_pid_returns_reader_for_current_platform(self) -> None:
        expected: type[ProcessStatsReader] = PsProcessStatsReader
        if sys.platform == "linux":
            expected = LinuxProcessStatsReader
        elif sys.platform == "win32":
            expected = WindowsProcessStatsReader

        reader = ProcessStatsReaderFactory().for_pid(os.getpid())

        self.assertIsInstance(reader, expected)

    def test_read_for_own_process_returns_positive_memory(self) -> None:
        reader = ProcessStatsReaderFactory().for_pid(os.getpid())
        self.addCleanup(reader.close)

        # the ps reader (macOS) answers a read with the result of the ps started by the previous one
        deadline = time.monotonic() + 5.0
        stats = reader.read()
        while stats is None and time.monotonic() < deadline:
            time.sleep(0.05)
            stats = reader.read()

        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertGreater(stats.rss_bytes, 1024 * 1024)
        self.assertGreaterEqual(stats.cpu_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
