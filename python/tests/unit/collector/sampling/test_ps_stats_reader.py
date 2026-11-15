import os
import shutil
import time
import unittest

from _vspyprof.collector.sampling.process_stats import ProcessStats
from _vspyprof.collector.sampling.ps_stats_reader import PsProcessStatsReader


class TestPsProcessStatsReader(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ps"), "needs ps")
    def test_read_returns_previous_reading_without_waiting_for_ps(self) -> None:
        reader = PsProcessStatsReader(os.getpid())
        self.addCleanup(reader.close)

        first = reader.read()  # starts ps, nothing has finished yet
        deadline = time.monotonic() + 5
        second = reader.read()
        while second is None and time.monotonic() < deadline:
            time.sleep(0.05)
            second = reader.read()

        self.assertIsNone(first)
        assert second is not None
        self.assertGreater(second.rss_bytes, 0)

    def test_parse_output_reads_rss_and_cpu_time(self) -> None:
        self.assertEqual(PsProcessStatsReader.parse_output("  2048   0:01.50\n"), ProcessStats(2048 * 1024, 1.5))

    def test_parse_output_of_gone_process_returns_none(self) -> None:
        self.assertIsNone(PsProcessStatsReader.parse_output(""))

    def test_parse_cpu_time_with_minutes_and_seconds_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("1:02.50"), 62.5)

    def test_parse_cpu_time_with_hours_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("01:00:01"), 3601.0)

    def test_parse_cpu_time_with_days_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("2-00:00:10"), 2 * 86400 + 10.0)


if __name__ == "__main__":
    unittest.main()
