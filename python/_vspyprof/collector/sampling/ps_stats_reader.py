"""Process statistics through ``ps``."""

import subprocess
import time

from _vspyprof.collector.sampling.process_stats import ProcessStats, ProcessStatsReader


class PsProcessStatsReader(ProcessStatsReader):
    """macOS and other POSIX systems: ``ps`` works without entitlements.

    The sampler reads stats on its own thread, so ``ps`` must not be waited
    for there: each ``read()`` collects the ``ps`` started by the previous call
    (if it has finished) and starts the next one. The values are therefore one
    reading interval old, which keeps CPU-usage deltas consistent.
    """

    _TIMEOUT = 2.0

    def __init__(self, pid: int) -> None:
        super().__init__(pid)
        self._running: subprocess.Popen[str] | None = None
        self._started = 0.0
        self._latest: ProcessStats | None = None

    def close(self) -> None:
        running, self._running = self._running, None
        if running is not None:
            if running.poll() is None:
                running.kill()
            running.communicate()  # reaps the process and closes its pipe

    def _read(self) -> ProcessStats | None:
        running = self._running
        if running is not None:
            if running.poll() is not None:
                stdout, _ = running.communicate()
                self._running = None
                self._latest = self.parse_output(stdout)
            elif time.monotonic() - self._started > self._TIMEOUT:
                self.close()  # a hanging ps must not block the readings for good
        if self._running is None:
            self._started = time.monotonic()
            self._running = subprocess.Popen(
                ["ps", "-o", "rss=,time=", "-p", str(self._pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        return self._latest

    @classmethod
    def parse_output(cls, stdout: str) -> ProcessStats | None:
        """``ps -o rss=,time=`` output; ``None`` if the process is gone (no output)."""
        columns = stdout.split()
        if len(columns) < 2:
            return None
        rss_kilobytes, cpu_time = columns[0], columns[1]
        return ProcessStats(int(rss_kilobytes) * 1024, cls.parse_cpu_time(cpu_time))

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
