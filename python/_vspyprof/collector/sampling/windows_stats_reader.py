"""Process statistics on Windows."""

import ctypes
import sys
from ctypes import wintypes

from _vspyprof.collector.sampling.process_stats import ProcessStats, ProcessStatsReader


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
        self._kernel32: ctypes.CDLL | None = None

    def close(self) -> None:
        if sys.platform != "win32":
            return
        if self._handle:
            self._api().CloseHandle(self._handle)
            self._handle = None

    def _api(self) -> ctypes.CDLL:
        """kernel32 with declared signatures.

        Undeclared, ctypes passes and returns C ``int``, which truncates 64-bit handles.
        """
        if sys.platform != "win32":
            raise OSError("kernel32 exists on Windows only")
        if self._kernel32 is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle, pointer = wintypes.HANDLE, ctypes.c_void_p
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = handle
            kernel32.CloseHandle.argtypes = (handle,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.K32GetProcessMemoryInfo.argtypes = (handle, pointer, wintypes.DWORD)
            kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            kernel32.GetExitCodeProcess.argtypes = (handle, pointer)
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.GetProcessTimes.argtypes = (handle, pointer, pointer, pointer, pointer)
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            self._kernel32 = kernel32
        return self._kernel32

    def _read(self) -> ProcessStats | None:
        if sys.platform != "win32":
            return None
        kernel32 = self._api()
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
