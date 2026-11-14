"""Interned frames and call stacks."""

from collections.abc import Sequence
from dataclasses import dataclass

# annotations only (never evaluated at runtime): this module imports without the private Tachyon module
lazy from _remote_debugging import FrameInfo

from _vscode_pyprof.collector.frames.frame_classifier import FrameClassifier
from _vscode_pyprof.collector.store.append_log import AppendLog


@dataclass(frozen=True, slots=True)
class SourceFrame:
    """One frame of a call stack: a line of a function in a file."""

    filename: str
    function: str
    line: int


@dataclass(frozen=True, slots=True)
class InternedStack:
    """A call stack in the table."""

    stack_id: int
    """Row of the stack's leaf, or ``StackTable.NO_STACK`` for a stack without frames."""
    internal: bool
    """True if the stack belongs to the profiler itself: one of its frames is profiler code, or it is empty."""


class StackTable:
    """Stores every distinct frame once and every call stack as a prefix tree.

    * ``frames`` rows are ``[file, function, line, category]``
    * ``stacks`` rows are ``[parent stack, frame]``; the parent of a root is ``NO_STACK``

    A stack is identified by the row of its leaf, so stacks that share callers
    share rows. Not thread-safe on its own: the ``Store`` guards it with its lock.
    """

    NO_STACK = -1
    _SAMPLED_CACHE_LIMIT = 200_000

    def __init__(self, classifier: FrameClassifier) -> None:
        self._classifier = classifier
        self._strip_launcher = False
        self.frames: AppendLog[list[str | int]] = AppendLog()
        self.stacks: AppendLog[list[int]] = AppendLog()
        self._frame_ids: dict[SourceFrame, int] = {}
        self._stack_ids: dict[tuple[int, int], int] = {}  # (parent stack, frame) -> stack
        self._stack_is_internal: list[bool] = []
        self._sampled: dict[tuple[tuple[FrameInfo, ...], bool], InternedStack] = {}  # (frames, strip) -> stack

    def strip_launcher(self, enabled: bool) -> None:
        """Whether ``strip=True`` drops the launcher/runpy bootstrap frames at the root of a stack."""
        self._strip_launcher = enabled

    def intern(self, frames_root_first: Sequence[SourceFrame], *, strip: bool) -> InternedStack:
        """Add a stack given its frames, root first, and return where it lives."""
        return self._intern(self._without_launcher(frames_root_first) if strip else frames_root_first)

    def intern_sampled(self, frames_leaf_first: Sequence[FrameInfo], *, strip: bool) -> InternedStack:
        """Intern a stack as Tachyon reports it; cached, because most samples repeat a known stack."""
        key = (tuple(frames_leaf_first), strip)
        cached = self._sampled.get(key)
        if cached is not None:
            return cached
        interned = self.intern([self._source_frame(frame) for frame in reversed(key[0])], strip=strip)
        if len(self._sampled) > self._SAMPLED_CACHE_LIMIT:
            self._sampled.clear()
        self._sampled[key] = interned
        return interned

    def _intern(self, frames_root_first: Sequence[SourceFrame]) -> InternedStack:
        stack_id = self.NO_STACK
        internal = not frames_root_first
        for frame in frames_root_first:
            frame_id = self._frame_id(frame)
            parent = stack_id
            known = self._stack_ids.get((parent, frame_id))
            if known is not None:
                stack_id = known
                internal = self._stack_is_internal[stack_id]
                continue
            stack_id = len(self.stacks)
            self.stacks.append([parent, frame_id])
            internal = internal or self._classifier.is_internal(frame.filename)
            self._stack_is_internal.append(internal)
            self._stack_ids[(parent, frame_id)] = stack_id
        return InternedStack(stack_id, internal)

    def _frame_id(self, frame: SourceFrame) -> int:
        frame_id = self._frame_ids.get(frame)
        if frame_id is None:
            frame_id = self._frame_ids[frame] = len(self.frames)
            category = int(self._classifier.category(frame.filename))
            self.frames.append([frame.filename, frame.function, frame.line, category])
        return frame_id

    def _without_launcher(self, frames_root_first: Sequence[SourceFrame]) -> Sequence[SourceFrame]:
        if not self._strip_launcher:
            return frames_root_first
        skip = self._classifier.launcher_prefix_length(frame.filename for frame in frames_root_first)
        return frames_root_first[skip:]

    @staticmethod
    def _source_frame(frame: FrameInfo) -> SourceFrame:
        location = frame.location
        if location is None:
            line = 0
        elif isinstance(location, int):
            line = location
        else:
            line = location[0] or 0
        return SourceFrame(frame.filename, frame.funcname, line)
