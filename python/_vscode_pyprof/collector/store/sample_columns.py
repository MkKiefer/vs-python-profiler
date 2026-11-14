"""Columnar storage of stack samples."""

from _vscode_pyprof.collector.store.append_log import AppendLog
from _vscode_pyprof.wire import JsonObject


class SampleColumns:
    """Sample table with one entry per (timestamp, thread), stored as one list per field.

    Columns keep the JSON small and let the dashboard load them into typed arrays.
    """

    def __init__(self) -> None:
        self._t: AppendLog[float] = AppendLog()
        self._tid: AppendLog[int] = AppendLog()
        self._stack: AppendLog[int] = AppendLog()
        self._status: AppendLog[int] = AppendLog()

    def __len__(self) -> int:
        return len(self._t)

    def append(self, t: float, tid: int, stack: int, status: int) -> None:
        self._t.append(t)
        self._tid.append(tid)
        self._stack.append(stack)
        self._status.append(status)

    def to_wire(self, *, new_only: bool) -> JsonObject:
        """All samples, or with ``new_only`` those appended since the previous ``new_only`` call."""
        return {
            "t": self._t.rows(new_only=new_only),
            "tid": self._tid.rows(new_only=new_only),
            "stack": self._stack.rows(new_only=new_only),
            "status": self._status.rows(new_only=new_only),
        }
