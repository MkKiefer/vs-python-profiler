"""A call stack that follows ``await`` instead of the thread."""

from collections.abc import Sequence
from dataclasses import dataclass

# annotations only (never evaluated at runtime): this module imports without the private Tachyon module
lazy from _remote_debugging import FrameInfo


@dataclass(frozen=True, slots=True)
class AsyncStack:
    """The coroutine chain that leads to one running task, as one linear stack."""

    frames_leaf_first: Sequence[FrameInfo]
    thread_id: int
    task_id: int
    """The task at the leaf of the chain."""
