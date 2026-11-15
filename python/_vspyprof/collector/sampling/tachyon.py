"""Tachyon adapter: the only module that touches ``_remote_debugging`` at runtime.

We drive ``_remote_debugging.RemoteUnwinder`` directly instead of shelling out
to ``python -m profiling.sampling`` so that we can

* sample in ``all`` mode once and keep per-sample thread status bits, letting
  the UI switch between wall / CPU / GIL views *after* recording,
* interleave async-aware stacks, task graphs, GC stats, RSS/CPU and child
  process discovery on one clock,
* stream live deltas instead of writing a file at the end.

``_remote_debugging`` is private API. Everything version specific is guarded
here so a change in a future CPython only needs a fix in this file.
"""

import os
import sys
import time
from collections.abc import Callable

from _vspyprof.collector.store.async_stack import AsyncStack

try:
    import _remote_debugging
    from _remote_debugging import AwaitedInfo, GCStatsInfo, RemoteUnwinder
except ImportError:  # interpreter too old / unsupported build; `Tachyon.require()` reports it
    _AVAILABLE = False
else:
    _AVAILABLE = True

try:  # reuse Tachyon's own async stack linearisation when available
    from profiling.sampling.collector import iter_async_frames
except ImportError:
    _ASYNC_LINEARISATION = False
else:
    _ASYNC_LINEARISATION = True


# what reading another process's memory can raise (torn reads, exited process, bad UTF-8)
_READ_ERRORS = (OSError, RuntimeError, ValueError, MemoryError)


class TachyonError(RuntimeError):
    """Attaching to or reading from the target process failed."""


class Tachyon:
    """Version-guarded access to CPython's remote unwinder for one target process."""

    READ_ERRORS = _READ_ERRORS
    _MODE_ALL = 3  # profiling.sampling.constants.PROFILING_MODE_ALL
    _LAUNCHER_RESOLVE_TIMEOUT = 2.0

    def __init__(self, pid: int, *, native: bool, gc: bool) -> None:
        self.require()
        self._pid = self._resolve_python_pid(pid)
        self._unwinder = self._create_unwinder(self._pid, native, gc)
        self._gc_monitor = self._create_gc_monitor(self._pid)

    # ------------------------------------------------------------ capabilities
    @staticmethod
    def require() -> None:
        if not _AVAILABLE:
            raise TachyonError("This interpreter has no _remote_debugging module; Python >= 3.15 is required.")

    @staticmethod
    def supports_gc_stats() -> bool:
        return _AVAILABLE and (hasattr(_remote_debugging, "GCMonitor") or hasattr(_remote_debugging, "get_gc_stats"))

    @staticmethod
    def supports_async_stacks() -> bool:
        return _ASYNC_LINEARISATION

    def supports_blocking(self) -> bool:
        return hasattr(self._unwinder, "pause_threads")

    # ----------------------------------------------------------------- target
    @property
    def pid(self) -> int:
        """The sampled process (may differ from the requested pid on Windows, see below)."""
        return self._pid

    def is_alive(self) -> bool:
        if os.name == "nt":
            try:
                RemoteUnwinder(self._pid)
            except _READ_ERRORS:
                return False
            return True
        try:
            os.kill(self._pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def python_children(self, known: set[int]) -> list[int]:
        """Python child processes not in ``known``; every inspected pid is added to ``known``."""
        try:
            children = _remote_debugging.get_child_pids(self._pid, recursive=True)
        except _READ_ERRORS:
            return []
        new: list[int] = []
        for child in children:
            if child in known:
                continue
            known.add(child)
            try:
                if _remote_debugging.is_python_process(child):
                    new.append(child)
            except _READ_ERRORS:
                continue
        return new

    # --------------------------------------------------------------- sampling
    def sample_threads(self, *, blocking: bool) -> list[_remote_debugging.InterpreterInfo]:
        """Stacks of all threads. ``blocking`` pauses the target for a consistent read."""
        if not blocking:
            return self._unwinder.get_stack_trace()
        self._unwinder.pause_threads()
        try:
            return self._unwinder.get_stack_trace()
        finally:
            self._unwinder.resume_threads()

    def running_tasks(self) -> list[AwaitedInfo]:
        return self._unwinder.get_async_stack_trace()

    def all_tasks(self) -> list[AwaitedInfo]:
        return self._unwinder.get_all_awaited_by()

    @staticmethod
    def linearise(awaited: list[AwaitedInfo]) -> list[AsyncStack]:
        """The coroutine chain of every running leaf task as one linear stack."""
        return [
            AsyncStack(frames_leaf_first, thread_id, leaf_task_id)
            for frames_leaf_first, thread_id, leaf_task_id in iter_async_frames(awaited)
        ]

    def gc_stats(self) -> list[GCStatsInfo]:
        if self._gc_monitor is not None:
            return self._gc_monitor.get_gc_stats()
        if hasattr(_remote_debugging, "get_gc_stats"):
            return _remote_debugging.get_gc_stats(self._pid)
        return []

    # ------------------------------------------------------------ construction
    @classmethod
    def _resolve_python_pid(cls, pid: int) -> int:
        """On Windows a venv ``python.exe`` is a launcher; profile its child instead."""
        if os.name != "nt":
            return pid
        deadline = time.monotonic() + cls._LAUNCHER_RESOLVE_TIMEOUT
        while True:
            try:
                if _remote_debugging.is_python_process(pid):
                    children = [
                        child
                        for child in _remote_debugging.get_child_pids(pid, recursive=False)
                        if _remote_debugging.is_python_process(child)
                    ]
                    if len(children) == 1:
                        return children[0]
                    if not children:
                        return pid
            except _READ_ERRORS:
                pass
            if time.monotonic() > deadline:
                return pid
            time.sleep(0.05)

    @classmethod
    def _create_unwinder(cls, pid: int, native: bool, gc: bool) -> RemoteUnwinder:
        # newest keyword set first; older 3.15 builds reject keywords they do not know (TypeError)
        attempts: tuple[Callable[[], RemoteUnwinder], ...] = (
            lambda: RemoteUnwinder(
                pid,
                all_threads=True,
                mode=cls._MODE_ALL,
                native=native,
                gc=gc,
                skip_non_matching_threads=False,
                cache_frames=True,
            ),
            lambda: RemoteUnwinder(pid, all_threads=True, mode=cls._MODE_ALL, native=native, gc=gc),
            lambda: RemoteUnwinder(pid, all_threads=True),
        )
        unsupported: TypeError | None = None
        for attempt in attempts:
            try:
                return attempt()
            except TypeError as error:
                unsupported = error
            except PermissionError as error:
                raise TachyonError(cls._permission_hint(pid, error)) from error
            except ProcessLookupError as error:
                raise TachyonError(f"Process {pid} does not exist") from error
            except RuntimeError as error:
                message = str(error)
                if "ermission" in message or "Operation not permitted" in message:
                    raise TachyonError(cls._permission_hint(pid, error)) from error
                raise TachyonError(f"Cannot attach to process {pid}: {message}") from error
        raise TachyonError(f"Unsupported _remote_debugging API: {unsupported}")

    @staticmethod
    def _create_gc_monitor(pid: int) -> _remote_debugging.GCMonitor | None:
        if not hasattr(_remote_debugging, "GCMonitor"):
            return None
        try:
            return _remote_debugging.GCMonitor(pid)
        except _READ_ERRORS:
            return None

    @staticmethod
    def _permission_hint(pid: int, error: BaseException) -> str:
        base = f"Permission denied while attaching to PID {pid} ({error})."
        if sys.platform == "linux":
            scope = ""
            try:
                with open("/proc/sys/kernel/yama/ptrace_scope") as f:
                    scope = f.read().strip()
            except OSError:
                pass
            return (
                base
                + " Linux restricts attaching to non-child processes"
                + (f" (kernel.yama.ptrace_scope={scope})" if scope else "")
                + ". Start the program with the profiler (Run with Profiler),"
                " or run `sudo sysctl kernel.yama.ptrace_scope=0`. In containers add `--cap-add=SYS_PTRACE`."
            )
        if sys.platform == "darwin":
            return (
                base + " macOS only allows reading another process's memory as root."
                " Run VS Code as root or start the program with the profiler."
            )
        return base + " The target probably runs elevated or as another user; run VS Code as Administrator."
