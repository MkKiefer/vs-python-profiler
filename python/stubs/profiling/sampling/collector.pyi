"""Type stubs for the part of ``profiling.sampling.collector`` (CPython 3.15) we reuse."""

from collections.abc import Iterator

from _remote_debugging import AwaitedInfo, FrameInfo

def iter_async_frames(awaited_info_list: list[AwaitedInfo]) -> Iterator[tuple[list[FrameInfo], int, int]]: ...
