import unittest

from _vscode_pyprof.collector.sampling.ps_stats_reader import PsProcessStatsReader


class TestPsProcessStatsReader(unittest.TestCase):
    def test_parse_cpu_time_with_minutes_and_seconds_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("1:02.50"), 62.5)

    def test_parse_cpu_time_with_hours_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("01:00:01"), 3601.0)

    def test_parse_cpu_time_with_days_returns_seconds(self) -> None:
        self.assertAlmostEqual(PsProcessStatsReader.parse_cpu_time("2-00:00:10"), 2 * 86400 + 10.0)


if __name__ == "__main__":
    unittest.main()
