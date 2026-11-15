"""The values a column held at one moment, readable later."""

from collections.abc import Iterator
from dataclasses import dataclass

from _vspyprof.collector.store.typed_column import TypedColumn


@dataclass(frozen=True, slots=True)
class ColumnSnapshot[N: (int, float)]:
    """The first ``length`` values of a column, taken under the store's lock.

    Columns only grow and their existing values never change, so the snapshot can be
    read without the lock while the sampler keeps appending (``ProfileWriter`` streams it).
    """

    column: TypedColumn[N]
    length: int

    def chunks(self, size: int) -> Iterator[list[N]]:
        """The values in lists of at most ``size``."""
        return self.column.chunks(self.length, size)
