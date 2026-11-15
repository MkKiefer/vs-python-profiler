"""Type stubs for CPython 3.15's private ``_remote_debugging`` module.

Only the surface used by ``_vspyprof.collector.tachyon`` and its callers is declared.
"""

from typing import final

THREAD_STATUS_HAS_GIL: int
THREAD_STATUS_ON_CPU: int
THREAD_STATUS_UNKNOWN: int
THREAD_STATUS_GIL_REQUESTED: int
THREAD_STATUS_HAS_EXCEPTION: int
THREAD_STATUS_MAIN_THREAD: int

@final
class LocationInfo:
    lineno: int | None
    end_lineno: int | None
    col_offset: int | None
    end_col_offset: int | None
    def __init__(self, fields: tuple[int | None, int | None, int | None, int | None]) -> None: ...
    def __getitem__(self, index: int) -> int | None: ...

@final
class FrameInfo:
    filename: str
    location: LocationInfo | int | None
    funcname: str
    opcode: int | None
    def __init__(self, fields: tuple[str, LocationInfo | int | None, str, int | None]) -> None: ...
    def __hash__(self) -> int: ...

@final
class ThreadInfo:
    thread_id: int
    status: int
    frame_info: list[FrameInfo]
    def __init__(self, fields: tuple[int, int, list[FrameInfo]]) -> None: ...

@final
class InterpreterInfo:
    interpreter_id: int
    threads: list[ThreadInfo]
    def __init__(self, fields: tuple[int, list[ThreadInfo]]) -> None: ...

@final
class CoroInfo:
    call_stack: list[FrameInfo]
    task_name: int | str
    def __init__(self, fields: tuple[list[FrameInfo], int | str]) -> None: ...

@final
class TaskInfo:
    task_id: int
    task_name: str
    coroutine_stack: list[CoroInfo]
    awaited_by: list[CoroInfo]
    def __init__(self, fields: tuple[int, str, list[CoroInfo], list[CoroInfo]]) -> None: ...

@final
class AwaitedInfo:
    thread_id: int
    awaited_by: list[TaskInfo]
    def __init__(self, fields: tuple[int, list[TaskInfo]]) -> None: ...

@final
class GCStatsInfo:
    gen: int
    iid: int
    ts_start: int
    ts_stop: int
    collections: int
    collected: int
    uncollectable: int
    candidates: int
    heap_size: int
    duration: float

@final
class GCMonitor:
    def __init__(self, pid: int) -> None: ...
    def get_gc_stats(self, all_interpreters: bool = False) -> list[GCStatsInfo]: ...

@final
class RemoteUnwinder:
    def __init__(
        self,
        pid: int,
        *,
        all_threads: bool = False,
        mode: int = 0,
        native: bool = False,
        gc: bool = False,
        skip_non_matching_threads: bool = True,
        cache_frames: bool = False,
    ) -> None: ...
    def get_stack_trace(self) -> list[InterpreterInfo]: ...
    def get_async_stack_trace(self) -> list[AwaitedInfo]: ...
    def get_all_awaited_by(self) -> list[AwaitedInfo]: ...
    def pause_threads(self) -> None: ...
    def resume_threads(self) -> None: ...

def get_child_pids(pid: int, *, recursive: bool = True) -> list[int]: ...
def get_gc_stats(pid: int, *, all_interpreters: bool = False) -> list[GCStatsInfo]: ...
def is_python_process(pid: int) -> bool: ...
