"""Columnar storage of stack samples."""

from array import array

from _vspyprof.collector.store.column_snapshot import ColumnSnapshot
from _vspyprof.collector.store.typed_column import TypedColumn
from _vspyprof.wire import JsonObject


class SampleColumns:
    """Sample table with one entry per (timestamp, thread), stored as one typed array per field.

    21 bytes per sample instead of ~70 in Python lists; the JSON stays columnar so the
    dashboard can load it into typed arrays of the same types (``SampleTable`` in
    ``src/shared/model.ts``).
    """

    STATUS_MASK = 0xFF
    """Thread status bits kept; the dashboard reads them as one byte."""

    def __init__(self) -> None:
        self._t: TypedColumn[float] = TypedColumn(array("d"))
        self._tid: TypedColumn[int] = TypedColumn(array("Q"))
        self._stack: TypedColumn[int] = TypedColumn(array("i"))
        self._status: TypedColumn[int] = TypedColumn(array("B"))

    def __len__(self) -> int:
        return len(self._t)

    def append(self, t: float, tid: int, stack: int, status: int) -> None:
        self._t.append(t)
        self._tid.append(tid)
        self._stack.append(stack)
        self._status.append(status & self.STATUS_MASK)

    def to_profile(self, *, new_only: bool) -> JsonObject:
        """All samples, or with ``new_only`` those appended since the previous ``new_only`` call."""
        if new_only:
            return {
                "t": self._t.new_values(),
                "tid": self._tid.new_values(),
                "stack": self._stack.new_values(),
                "status": self._status.new_values(),
            }
        return {
            "t": self._t.values(),
            "tid": self._tid.values(),
            "stack": self._stack.values(),
            "status": self._status.values(),
        }

    def snapshot(self) -> JsonObject:
        """All samples as ``ColumnSnapshot``s, for streaming them into a file without copying the columns."""
        length = len(self)
        return {
            "t": ColumnSnapshot(self._t, length),
            "tid": ColumnSnapshot(self._tid, length),
            "stack": ColumnSnapshot(self._stack, length),
            "status": ColumnSnapshot(self._status, length),
        }
