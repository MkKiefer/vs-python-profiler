import os
import sys
import unittest

from _vscode_pyprof.collector.sampler import (
    LinuxProcessStatsReader,
    ProcessStatsReader,
    PsProcessStatsReader,
    WindowsProcessStatsReader,
)


class TestProcessStatsReader(unittest.TestCase):
    def test_for_pid_returns_reader_for_current_platform(self) -> None:
        expected: type[ProcessStatsReader] = PsProcessStatsReader
        if sys.platform == "linux":
            expected = LinuxProcessStatsReader
        elif sys.platform == "win32":
            expected = WindowsProcessStatsReader

        reader = ProcessStatsReader.for_pid(os.getpid())

        self.assertIsInstance(reader, expected)

    def test_read_for_own_process_returns_positive_memory(self) -> None:
        reader = ProcessStatsReader.for_pid(os.getpid())
        self.addCleanup(reader.close)

        stats = reader.read()

        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertGreater(stats.rss_bytes, 1024 * 1024)
        self.assertGreaterEqual(stats.cpu_seconds, 0.0)


@unittest.skipUnless(sys.platform == "linux", "reads /proc")
class TestLinuxProcessStatsReader(unittest.TestCase):
    def test_read_with_unknown_pid_returns_none(self) -> None:
        reader = LinuxProcessStatsReader(2**30)

        self.assertIsNone(reader.read())


class TestPsProcessStatsReader(unittest.TestCase):
    def test_parse_cpu_time_with_minutes_and_seconds_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("1:02.50"), 62.5)

    def test_parse_cpu_time_with_hours_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("01:00:01"), 3601.0)

    def test_parse_cpu_time_with_days_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("2-00:00:10"), 2 * 86400 + 10.0)


if __name__ == "__main__":
    unittest.main()
