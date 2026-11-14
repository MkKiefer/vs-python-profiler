"""Process statistics on Windows."""

import ctypes
import sys
from ctypes import wintypes

from _vscode_pyprof.collector.sampling.process_stats import ProcessStats, ProcessStatsReader


class _ProcessMemoryCounters(ctypes.Structure):
    """``PROCESS_MEMORY_COUNTERS`` of psapi."""

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
    _FILETIME_TICKS_PER_SECOND = 1e7

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
        creation, exit_, kernel, user = (wintypes.FILETIME() for _ in range(4))
        kernel32.GetProcessTimes(
            self._handle, ctypes.byref(creation), ctypes.byref(exit_), ctypes.byref(kernel), ctypes.byref(user)
        )
        return ProcessStats(int(counters.WorkingSetSize), self._seconds(kernel) + self._seconds(user))

    @classmethod
    def _seconds(cls, filetime: wintypes.FILETIME) -> float:
        return ((filetime.dwHighDateTime << 32) | filetime.dwLowDateTime) / cls._FILETIME_TICKS_PER_SECOND
