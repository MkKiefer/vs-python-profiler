"""Picks the process statistics reader of the current operating system."""

import sys

from _vspyprof.collector.sampling.linux_stats_reader import LinuxProcessStatsReader
from _vspyprof.collector.sampling.process_stats import ProcessStatsReader
from _vspyprof.collector.sampling.ps_stats_reader import PsProcessStatsReader
from _vspyprof.collector.sampling.windows_stats_reader import WindowsProcessStatsReader


class ProcessStatsReaderFactory:
    def for_pid(self, pid: int) -> ProcessStatsReader:
        if sys.platform == "linux":
            return LinuxProcessStatsReader(pid)
        if sys.platform == "win32":
            return WindowsProcessStatsReader(pid)
        return PsProcessStatsReader(pid)
