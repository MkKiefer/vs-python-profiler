"""Cross-platform RSS and CPU-time readers for another process (stdlib only)."""

from __future__ import annotations

import os
import subprocess
import sys


class ProcStats:
    """Return ``(rss_bytes, cpu_seconds)`` for ``pid`` or ``None`` if gone."""

    def __init__(self, pid: int):
        self.pid = pid
        self._impl = {
            "linux": self._linux,
            "win32": self._windows,
            "darwin": self._ps,
        }.get(sys.platform, self._ps)
        self._handle = None
        if sys.platform == "linux":
            self._page = os.sysconf("SC_PAGE_SIZE")
            self._tck = os.sysconf("SC_CLK_TCK")

    def read(self):
        try:
            return self._impl()
        except (OSError, ValueError, IndexError):
            return None

    def close(self):
        if self._handle:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None

    # -- linux: /proc is cheap and always readable for same-user processes
    def _linux(self):
        with open(f"/proc/{self.pid}/statm", "rb") as f:
            rss_pages = int(f.read().split()[1])
        with open(f"/proc/{self.pid}/stat", "rb") as f:
            data = f.read()
        fields = data[data.rindex(b")") + 2:].split()
        cpu = (int(fields[11]) + int(fields[12])) / self._tck
        return rss_pages * self._page, cpu

    # -- macOS (and fallback): `ps` works without entitlements
    def _ps(self):
        out = subprocess.run(
            ["ps", "-o", "rss=,time=", "-p", str(self.pid)],
            capture_output=True, text=True, timeout=2,
        ).stdout.split()
        if len(out) < 2:
            return None
        rss = int(out[0]) * 1024
        return rss, _parse_ps_time(out[1])

    # -- windows: psapi via ctypes
    def _windows(self):
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        if not self._handle:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            self._handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
            if not self._handle:
                return None

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if not k32.K32GetProcessMemoryInfo(self._handle, ctypes.byref(pmc), pmc.cb):
            return None
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(self._handle, ctypes.byref(code)) and code.value != 259:
            return None  # STILL_ACTIVE == 259
        ft = [wintypes.FILETIME() for _ in range(4)]
        k32.GetProcessTimes(self._handle, *[ctypes.byref(x) for x in ft])

        def secs(f):
            return ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7

        return pmc.WorkingSetSize, secs(ft[2]) + secs(ft[3])


def _parse_ps_time(s: str) -> float:
    # [[dd-]hh:]mm:ss.ss
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [float(p) for p in s.split(":")]
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return days * 86400 + secs
