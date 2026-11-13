"""Classifies source files: user code, library, stdlib, synthetic, profiler-internal."""

import os
import sys
import sysconfig
from collections.abc import Iterable, Sequence
from enum import IntEnum

from _vscode_pyprof import PACKAGE_DIR


class FrameCategory(IntEnum):
    """Mirror of ``Cat`` in ``src/shared/model.ts``."""

    USER = 0
    LIBRARY = 1
    STDLIB = 2
    SYNTHETIC = 3


class FrameClassifier:
    """Answers "whose code is this file?" with per-filename caching (hot path of the sampler)."""

    _BOOTSTRAP_FILES = frozenset({"<string>", "<frozen runpy>"})

    def __init__(self, std_dirs: Sequence[str], lib_dirs: Sequence[str], internal_dir: str) -> None:
        self._std_dirs = self._normalise_dirs(std_dirs)
        self._lib_dirs = self._normalise_dirs(lib_dirs)
        self._internal_dir = self._normalise_dirs([internal_dir])[0]
        self._categories: dict[str, FrameCategory] = {}
        self._internal: dict[str, bool] = {}

    @classmethod
    def for_running_interpreter(cls) -> FrameClassifier:
        """Classifier for the interpreter running this code.

        The collector always runs with the same interpreter as the target, so
        its own sysconfig paths classify the target's frames correctly.
        """
        paths = sysconfig.get_paths()
        base = sysconfig.get_paths(vars={"base": sys.base_prefix, "platbase": sys.base_exec_prefix})
        std = [paths.get("stdlib"), paths.get("platstdlib"), base.get("stdlib"), base.get("platstdlib")]
        lib = [paths.get("purelib"), paths.get("platlib"), base.get("purelib"), base.get("platlib")]
        lib += [p for p in sys.path if "site-packages" in p or "dist-packages" in p]
        return cls([p for p in std if p], [p for p in lib if p], PACKAGE_DIR)

    def category(self, filename: str) -> FrameCategory:
        cached = self._categories.get(filename)
        if cached is not None:
            return cached
        if not filename or filename[0] in "<~":
            category = FrameCategory.SYNTHETIC
        else:
            normalised = os.path.normcase(filename)
            # site-packages usually lives below the stdlib directory: check libraries first
            if normalised.startswith(self._lib_dirs):
                category = FrameCategory.LIBRARY
            elif normalised.startswith(self._std_dirs):
                category = FrameCategory.STDLIB
            else:
                category = FrameCategory.USER
        self._categories[filename] = category
        return category

    def is_internal(self, filename: str) -> bool:
        """True for files of the profiler itself (launcher, agent)."""
        cached = self._internal.get(filename)
        if cached is None:
            cached = os.path.normcase(filename).startswith(self._internal_dir)
            self._internal[filename] = cached
        return cached

    def is_launcher_frame(self, filename: str) -> bool:
        """True for frames that only exist because the program was started by our launcher."""
        return (
            filename in self._BOOTSTRAP_FILES or os.path.basename(filename) == "runpy.py" or self.is_internal(filename)
        )

    def launcher_prefix_length(self, filenames_root_first: Iterable[str]) -> int:
        """Number of leading (root-side) frames that belong to the launcher bootstrap."""
        count = 0
        for filename in filenames_root_first:
            if not self.is_launcher_frame(filename):
                break
            count += 1
        return count

    @staticmethod
    def _normalise_dirs(paths: Iterable[str]) -> tuple[str, ...]:
        out: list[str] = []
        for path in paths:
            normalised = os.path.normcase(os.path.abspath(path))
            if not normalised.endswith(os.sep):
                normalised += os.sep
            if normalised not in out:
                out.append(normalised)
        return tuple(out)
