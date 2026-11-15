import sys
import unittest

from _vspyprof.collector.sampling.linux_stats_reader import LinuxProcessStatsReader


@unittest.skipUnless(sys.platform == "linux", "reads /proc")
class TestLinuxProcessStatsReader(unittest.TestCase):
    def test_read_with_unknown_pid_returns_none(self) -> None:
        reader = LinuxProcessStatsReader(2**30)

        self.assertIsNone(reader.read())


if __name__ == "__main__":
    unittest.main()
