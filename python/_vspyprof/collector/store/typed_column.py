"""An append-only column of numbers stored compactly."""

from array import array
from collections.abc import Iterator


class TypedColumn[N: (int, float)]:
    """Numbers of one machine type in an ``array``, which remembers how many have been handed out.

    A list of Python numbers costs 8 bytes per slot plus, for most values, an object of
    24-32 bytes; an ``array`` stores only the raw value (8 bytes for ``"d"`` or ``"Q"``,
    1 for ``"B"``). Sample tables grow by one row per thread and tick, so this is where a
    long recording keeps its memory.

    Not thread-safe on its own: the ``Store`` guards it with its lock. Values below a
    length taken under that lock never change, so they may be read without it.
    """

    def __init__(self, values: array[N]) -> None:
        """``values`` is an empty ``array`` of the column's type, such as ``array("d")``."""
        self._values: array[N] = values
        self._handed_out = 0

    def __len__(self) -> int:
        return len(self._values)

    def append(self, value: N) -> None:
        """Raises ``OverflowError`` if ``value`` does not fit the type."""
        self._values.append(value)

    def new_values(self) -> list[N]:
        """The values appended since the previous call."""
        new = self._values[self._handed_out :].tolist()
        self._handed_out += len(new)
        return new

    def values(self, stop: int | None = None) -> list[N]:
        """The first ``stop`` values (all of them by default) as a list."""
        return self._values[:stop].tolist()

    def chunks(self, stop: int, size: int) -> Iterator[list[N]]:
        """The first ``stop`` values in lists of at most ``size``, without copying the whole column at once."""
        for start in range(0, stop, size):
            yield self._values[start : min(stop, start + size)].tolist()
