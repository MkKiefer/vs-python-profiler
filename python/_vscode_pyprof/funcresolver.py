"""Map ``(file, line)`` to a qualified function name.

tracemalloc tracebacks only carry file and line. To show allocation flame
graphs with the same function names as CPU stacks (CPython 3.15 reports
``__qualname__``), we parse each source file once and look up the innermost
enclosing ``def``/``class``.
"""

import ast
import linecache
from dataclasses import dataclass


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
