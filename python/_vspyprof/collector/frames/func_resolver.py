"""Which function a source line belongs to.

tracemalloc tracebacks only carry file and line. To show allocation flame
graphs with the same names as CPU stacks (CPython 3.15 reports
``__qualname__``), each source file is parsed once and the innermost enclosing
``def``/``class`` is looked up.
"""

import ast
import linecache
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Scope:
    """The lines of one ``def`` or ``class``, decorators included."""

    start: int
    end: int
    qualname: str


class FuncResolver:
    """Maps ``(file, line)`` to a qualified function name, cached per file and per line."""

    MODULE = "<module>"
    UNKNOWN = "?"

    def __init__(self) -> None:
        self._scopes_by_file: dict[str, list[_Scope] | None] = {}
        self._resolved: dict[tuple[str, int], str] = {}

    def resolve(self, filename: str, line: int) -> str:
        key = (filename, line)
        name = self._resolved.get(key)
        if name is None:
            name = self._resolved[key] = self._lookup(filename, line)
        return name

    def _lookup(self, filename: str, line: int) -> str:
        scopes = self._scopes(filename)
        if scopes is None:
            return self.MODULE if line else self.UNKNOWN
        # scopes are sorted outermost-first, so the last match is the innermost scope
        innermost = self.MODULE
        for scope in scopes:
            if scope.start > line:
                break
            if line <= scope.end:
                innermost = scope.qualname
        return innermost

    def _scopes(self, filename: str) -> list[_Scope] | None:
        """Scopes of a file sorted outermost-first; ``None`` if its source cannot be read or parsed."""
        if filename not in self._scopes_by_file:
            self._scopes_by_file[filename] = self._parse(filename)
        return self._scopes_by_file[filename]

    def _parse(self, filename: str) -> list[_Scope] | None:
        try:
            source = "".join(linecache.getlines(filename))
            if not source:
                return None
            scopes: list[_Scope] = []
            self._collect(ast.parse(source, filename), "", scopes)
        except SyntaxError, ValueError, RecursionError, OSError:
            return None
        scopes.sort(key=lambda scope: (scope.start, -scope.end))
        return scopes

    def _collect(self, node: ast.AST, prefix: str, scopes: list[_Scope]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = f"{prefix}{child.name}"
                start = min([child.lineno, *(decorator.lineno for decorator in child.decorator_list)])
                scopes.append(_Scope(start, child.end_lineno or child.lineno, qualname))
                inner = f"{qualname}." if isinstance(child, ast.ClassDef) else f"{qualname}.<locals>."
                self._collect(child, inner, scopes)
            else:
                self._collect(child, prefix, scopes)
