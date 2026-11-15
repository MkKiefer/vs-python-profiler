"""An append-only table that remembers how much of it has been handed out."""


class AppendLog[T]:
    """Rows are only ever appended, so "what is new" is everything after a cursor.

    Not thread-safe on its own: the ``Store`` guards its logs with one lock.
    """

    def __init__(self) -> None:
        self._rows: list[T] = []
        self._handed_out = 0

    def __len__(self) -> int:
        return len(self._rows)

    def append(self, row: T) -> None:
        self._rows.append(row)

    def rows(self, *, new_only: bool) -> list[T]:
        """Every row, or with ``new_only`` the rows appended since the previous ``new_only`` call."""
        if not new_only:
            return list(self._rows)
        new = self._rows[self._handed_out :]
        self._handed_out = len(self._rows)
        return new
