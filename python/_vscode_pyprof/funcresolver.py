"""Map ``(file, line)`` to a qualified function name.

tracemalloc tracebacks only carry file and line. To show allocation flame
graphs with the same function names as CPU stacks (CPython 3.15 reports
``__qualname__``), we parse each source file once and look up the innermost
enclosing ``def``/``class``.
"""

from __future__ import annotations

import ast
import bisect
import linecache


class FuncResolver:
    def __init__(self):
        self._cache: dict[str, tuple[list, list] | None] = {}

    def resolve(self, filename: str, line: int) -> str:
        idx = self._index(filename)
        if not idx:
            return "<module>" if line else "?"
        starts, spans = idx
        i = bisect.bisect_right(starts, line)
        best = None
        # spans sorted by start; walk back to find the innermost enclosing span
        while i > 0:
            i -= 1
            start, end, name = spans[i]
            if start <= line <= end:
                if best is None or start >= best[0]:
                    best = (start, name)
                    break
        return best[1] if best else "<module>"

    def _index(self, filename):
        if filename in self._cache:
            return self._cache[filename]
        result = None
        try:
            src = "".join(linecache.getlines(filename))
            if src:
                tree = ast.parse(src, filename)
                spans: list = []
                _walk(tree, "", spans)
                # innermost-first ordering: sort by start, then by narrower span
                spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
                result = ([s[0] for s in spans], spans)
        except (SyntaxError, ValueError, RecursionError, OSError):
            result = None
        self._cache[filename] = result
        return result


def _walk(node, prefix, spans):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}{child.name}"
            start = min([child.lineno] + [d.lineno for d in child.decorator_list])
            end = getattr(child, "end_lineno", None) or child.lineno
            spans.append((start, end, name))
            if isinstance(child, ast.ClassDef):
                _walk(child, name + ".", spans)
            else:
                _walk(child, name + ".<locals>.", spans)
        else:
            _walk(child, prefix, spans)
