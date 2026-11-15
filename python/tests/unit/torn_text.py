"""A stand-in for a string that Tachyon read torn from the target's memory.

The real thing is a ``str`` whose characters are not valid code points; CPython
raises ``SystemError`` once a character is taken out of it. Pure Python cannot
build such an object, so this subclass fails the same way.
"""

from collections.abc import Iterator


class TornText(str):
    __slots__ = ()

    def __iter__(self) -> Iterator[str]:
        raise SystemError("invalid maximum character passed to PyUnicode_New")
