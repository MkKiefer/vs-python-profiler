"""What a source location means.

``FrameClassifier`` sorts files into user code, library, stdlib, synthetic and
profiler-internal. ``FuncResolver`` maps ``(file, line)`` to a qualified
function name: tracemalloc tracebacks only carry file and line, so to show
allocation flame graphs with the same names as CPU stacks (CPython 3.15
reports ``__qualname__``) each source file is parsed once and the innermost
enclosing ``def``/``class`` is looked up.
"""

import ast
import linecache
import os
import sys
import sysconfig
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    qualname: str


class FuncResolver:
    MODULE = "<module>"
    UNKNOWN = "?"

    def __init__(self) -> None:
        self._spans_by_file: dict[str, list[_Span] | None] = {}
        self._resolved: dict[tuple[str, int], str] = {}

    def resolve(self, filename: str, line: int) -> str:
        key = (filename, line)
        name = self._resolved.get(key)
        if name is None:
            name = self._resolved[key] = self._lookup(filename, line)
        return name

    def _lookup(self, filename: str, line: int) -> str:
        spans = self._spans(filename)
        if spans is None:
            return self.MODULE if line else self.UNKNOWN
        # spans are sorted outermost-first, so the last match is the innermost scope
        innermost = self.MODULE
        for span in spans:
            if span.start > line:
                break
            if line <= span.end:
                innermost = span.qualname
        return innermost

    def _spans(self, filename: str) -> list[_Span] | None:
        if filename in self._spans_by_file:
            return self._spans_by_file[filename]
        spans: list[_Span] | None = None
        try:
            source = "".join(linecache.getlines(filename))
            if source:
                spans = []
                self._collect(ast.parse(source, filename), "", spans)
                spans.sort(key=lambda s: (s.start, -s.end))
        except SyntaxError, ValueError, RecursionError, OSError:
            spans = None
        self._spans_by_file[filename] = spans
        return spans

    def _collect(self, node: ast.AST, prefix: str, spans: list[_Span]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = f"{prefix}{child.name}"
                start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                spans.append(_Span(start, child.end_lineno or child.lineno, qualname))
                inner = f"{qualname}." if isinstance(child, ast.ClassDef) else f"{qualname}.<locals>."
                self._collect(child, inner, spans)
            else:
                self._collect(child, prefix, spans)
