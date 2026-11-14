"""Memory and CPU usage of another process, stdlib only."""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessStats:
    rss_bytes: int
    cpu_seconds: float
    """CPU time used since the process started (user + system)."""


class ProcessStatsReader(ABC):
    """Reads memory and CPU usage of one process; one implementation per operating system."""

    def __init__(self, pid: int) -> None:
        self._pid = pid

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
