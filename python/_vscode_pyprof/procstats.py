"""Cross-platform RSS and CPU-time readers for another process (stdlib only)."""

import ctypes
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessStats:
    rss_bytes: int
    cpu_seconds: float


class ProcessStatsReader(ABC):
    """Reads memory and CPU usage of one process."""

    def __init__(self, pid: int) -> None:
        self._pid = pid

    @classmethod
    def for_pid(cls, pid: int) -> ProcessStatsReader:
        """The reader matching the current operating system."""
        if sys.platform == "linux":
            return LinuxProcessStatsReader(pid)
        if sys.platform == "win32":
            return WindowsProcessStatsReader(pid)
        return PsProcessStatsReader(pid)

    def read(self) -> ProcessStats | None:
        """Current stats, or ``None`` if the process is gone or cannot be read."""
        try:
            return self._read()
        except OSError, ValueError, IndexError, subprocess.SubprocessError:
            return None

    def close(self) -> None:  # noqa: B027 - optional hook, most readers hold no resources
        """Release OS resources held by the reader."""

    @abstractmethod
    def _read(self) -> ProcessStats | None: ...


class LinuxProcessStatsReader(ProcessStatsReader):
    """``/proc`` is cheap and always readable for same-user processes."""

    def __init__(self, pid: int) -> None:
        super().__init__(pid)
        self._page_size = os.sysconf("SC_PAGE_SIZE")
        self._ticks_per_second = os.sysconf("SC_CLK_TCK")

    def _read(self) -> ProcessStats | None:
        with open(f"/proc/{self._pid}/statm", "rb") as f:
            rss_pages = int(f.read().split()[1])
        with open(f"/proc/{self._pid}/stat", "rb") as f:
            data = f.read()
        # the command name (field 2) may contain spaces and parentheses: split after the last ')'
        fields = data[data.rindex(b")") + 2 :].split()
        cpu_ticks = int(fields[11]) + int(fields[12])  # utime + stime
        return ProcessStats(rss_pages * self._page_size, cpu_ticks / self._ticks_per_second)


class PsProcessStatsReader(ProcessStatsReader):
    """macOS and other POSIX systems: ``ps`` works without entitlements."""

    def _read(self) -> ProcessStats | None:
        out = subprocess.run(
            ["ps", "-o", "rss=,time=", "-p", str(self._pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.split()
        if len(out) < 2:
            return None
        return ProcessStats(int(out[0]) * 1024, self.parse_cpu_time(out[1]))

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


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


class WindowsProcessStatsReader(ProcessStatsReader):
    """Windows: psapi through ctypes, with one process handle kept open."""

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259

    def __init__(self, pid: int) -> None:
        super().__init__(pid)
        self._handle: int | None = None

    def close(self) -> None:
        if sys.platform != "win32":
            return
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    def _read(self) -> ProcessStats | None:
        if sys.platform != "win32":
            return None
        kernel32 = ctypes.windll.kernel32
        if not self._handle:
            self._handle = kernel32.OpenProcess(self._PROCESS_QUERY_LIMITED_INFORMATION, False, self._pid)
            if not self._handle:
                return None
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        if not kernel32.K32GetProcessMemoryInfo(self._handle, ctypes.byref(counters), counters.cb):
            return None
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(self._handle, ctypes.byref(exit_code)) and exit_code.value != self._STILL_ACTIVE:
            return None
        # creation, exit, kernel, user
        times = [wintypes.FILETIME() for _ in range(4)]
        kernel32.GetProcessTimes(self._handle, *[ctypes.byref(t) for t in times])
        cpu = self._filetime_seconds(times[2]) + self._filetime_seconds(times[3])
        return ProcessStats(int(counters.WorkingSetSize), cpu)

    @staticmethod
    def _filetime_seconds(filetime: wintypes.FILETIME) -> float:
        return ((filetime.dwHighDateTime << 32) | filetime.dwLowDateTime) / 1e7
