"""Process statistics on Linux."""

import os
import sys

from _vspyprof.collector.sampling.process_stats import ProcessStats, ProcessStatsReader


class LinuxProcessStatsReader(ProcessStatsReader):
    """``/proc`` is cheap and always readable for same-user processes."""

    _UTIME_FIELD = 11  # index in /proc/<pid>/stat counted after the command name; stime follows

    def __init__(self, pid: int) -> None:
        super().__init__(pid)
        if sys.platform == "win32":  # also tells mypy, which checks this module on Windows, that sysconf exists
            raise OSError("/proc statistics are not available on Windows")
        self._page_size: int = os.sysconf("SC_PAGE_SIZE")
        self._ticks_per_second: int = os.sysconf("SC_CLK_TCK")

    def _read(self) -> ProcessStats | None:
        with open(f"/proc/{self._pid}/statm", "rb") as f:
            rss_pages = int(f.read().split()[1])
        with open(f"/proc/{self._pid}/stat", "rb") as f:
            data = f.read()
        # the command name (field 2) may contain spaces and parentheses: split after the last ')'
        fields = data[data.rindex(b")") + 2 :].split()
        cpu_ticks = int(fields[self._UTIME_FIELD]) + int(fields[self._UTIME_FIELD + 1])
        return ProcessStats(rss_pages * self._page_size, cpu_ticks / self._ticks_per_second)
