"""Process statistics through ``ps``."""

import subprocess

from _vspyprof.collector.sampling.process_stats import ProcessStats, ProcessStatsReader


class PsProcessStatsReader(ProcessStatsReader):
    """macOS and other POSIX systems: ``ps`` works without entitlements."""

    _TIMEOUT = 2.0

    def _read(self) -> ProcessStats | None:
        columns = subprocess.run(
            ["ps", "-o", "rss=,time=", "-p", str(self._pid)],
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT,
            check=False,
        ).stdout.split()
        if len(columns) < 2:
            return None
        rss_kilobytes, cpu_time = columns[0], columns[1]
        return ProcessStats(int(rss_kilobytes) * 1024, self.parse_cpu_time(cpu_time))

    @staticmethod
    def parse_cpu_time(text: str) -> float:
        """Parse ``ps`` cumulative CPU time, ``[[dd-]hh:]mm:ss[.ss]``, into seconds."""
        days = 0
        if "-" in text:
            day_part, text = text.split("-", 1)
            days = int(day_part)
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
        return days * 86400 + seconds
