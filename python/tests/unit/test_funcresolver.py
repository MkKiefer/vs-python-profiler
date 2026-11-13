import os
import tempfile
import textwrap
import unittest

from _vscode_pyprof.funcresolver import FuncResolver

SOURCE = textwrap.dedent(
    """\
    import functools

    CONSTANT = 1

    def plain():
        return 1

    class Service:
        limit = 3

        def method(self):
            def helper():
                return 2
            return helper()

        @functools.cache
        def decorated(self):
            return 3

    async def fetch():
        return 4
    """
)


class TestFuncResolver(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "sample.py")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SOURCE)
        self.resolver = FuncResolver()

    def test_resolve_with_module_level_line_returns_module(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 3), "<module>")

    def test_resolve_with_line_in_function_returns_function_name(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 6), "plain")

    def test_resolve_with_line_in_class_body_returns_class_name(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 9), "Service")

    def test_resolve_with_line_in_method_returns_qualified_name(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 14), "Service.method")

    def test_resolve_with_line_in_nested_function_returns_locals_qualname(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 13), "Service.method.<locals>.helper")

    def test_resolve_with_decorator_line_returns_decorated_function(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 16), "Service.decorated")

    def test_resolve_with_line_in_async_function_returns_function_name(self) -> None:
        self.assertEqual(self.resolver.resolve(self.path, 21), "fetch")

    def test_resolve_with_missing_file_and_line_returns_module(self) -> None:
        self.assertEqual(self.resolver.resolve(os.path.join(self.path, "missing.py"), 5), "<module>")

    def test_resolve_with_missing_file_and_no_line_returns_unknown(self) -> None:
        self.assertEqual(self.resolver.resolve(os.path.join(self.path, "missing.py"), 0), "?")

    def test_resolve_with_syntax_error_file_returns_module(self) -> None:
        broken = self.path.replace("sample.py", "broken.py")
        with open(broken, "w", encoding="utf-8") as f:
            f.write("def broken(:\n")

        self.assertEqual(self.resolver.resolve(broken, 1), "<module>")


if __name__ == "__main__":
    unittest.main()
