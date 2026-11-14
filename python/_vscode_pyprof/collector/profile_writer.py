"""Writes ``.pyprof`` files."""

import gzip
import json
import os

from _vscode_pyprof.wire import JsonObject


class ProfileWriter:
    """A ``.pyprof`` file is the gzip-compressed JSON of ``Store.full()``."""

    _COMPRESSION_LEVEL = 6

    def write(self, path: str, profile: JsonObject) -> int:
        """Write ``profile`` to ``path``, creating its directory; returns the file size in bytes.

        The file is replaced atomically, so a failed save never leaves a truncated profile behind.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temporary = path + ".tmp"
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=self._COMPRESSION_LEVEL) as f:
            json.dump(profile, f, separators=(",", ":"), default=str)
        os.replace(temporary, path)
        return os.path.getsize(path)
