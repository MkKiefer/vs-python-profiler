"""Writes ``.vspyprof`` files."""

import gzip
import json
import os
from typing import TextIO

from _vspyprof.collector.store.column_snapshot import ColumnSnapshot
from _vspyprof.wire import JsonObject


class ProfileWriter:
    """A ``.vspyprof`` file is gzip-compressed JSON in the shape of ``Store.full()``.

    The profile is streamed: objects are written key by key and ``ColumnSnapshot``
    values (the sample columns, by far the largest part) chunk by chunk, so saving a
    long recording never builds its whole JSON text, or a list copy of its samples, in memory.
    """

    _COMPRESSION_LEVEL = 6
    _CHUNK = 65_536  # values per chunk of a streamed column
    _SEPARATORS = (",", ":")

    def write(self, path: str, profile: JsonObject) -> int:
        """Write ``profile`` to ``path``, creating its directory; returns the file size in bytes.

        Values may be ``ColumnSnapshot``s, which are written as arrays. The file is
        replaced atomically, so a failed save never leaves a truncated profile behind.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temporary = path + ".tmp"
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=self._COMPRESSION_LEVEL) as f:
            self._write_value(f, profile)
        os.replace(temporary, path)
        return os.path.getsize(path)

    def _write_value(self, f: TextIO, value: object) -> None:
        match value:
            case ColumnSnapshot():
                self._write_column(f, value)
            case dict():
                f.write("{")
                for index, (key, item) in enumerate(value.items()):
                    if index:
                        f.write(",")
                    f.write(json.dumps(str(key)))
                    f.write(":")
                    self._write_value(f, item)
                f.write("}")
            case _:
                json.dump(value, f, separators=self._SEPARATORS, default=str)

    def _write_column(self, f: TextIO, column: ColumnSnapshot[int] | ColumnSnapshot[float]) -> None:
        f.write("[")
        first = True
        for chunk in column.chunks(self._CHUNK):
            if not chunk:
                continue
            if not first:
                f.write(",")
            f.write(json.dumps(chunk, separators=self._SEPARATORS)[1:-1])  # the values without the brackets
            first = False
        f.write("]")
