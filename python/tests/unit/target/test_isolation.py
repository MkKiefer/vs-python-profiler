"""The code that runs inside the profiled program stays apart from the collector.

Whatever ``_vscode_pyprof.target`` imports is loaded into the user's program, so
it may use only itself, the package root and the shared ``wire`` module.
"""

import json
import os
import subprocess
import sys
import unittest

from _vscode_pyprof import PACKAGE_DIR

ALLOWED = {"_vscode_pyprof", "_vscode_pyprof.wire", "_vscode_pyprof.target"}


class TestTargetIsolation(unittest.TestCase):
    def loaded_package_modules(self, module: str) -> set[str]:
        """Our modules present after importing `module` in a fresh, isolated interpreter."""
        script = (
            "import json, sys; sys.path.insert(0, sys.argv[1]); "
            f"import {module}; "
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('_vscode_pyprof'))))"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, os.path.dirname(PACKAGE_DIR)],
            capture_output=True,
            text=True,
            check=True,
        )
        return set(json.loads(result.stdout))

    def test_agent_import_loads_no_collector_code(self) -> None:
        loaded = self.loaded_package_modules("_vscode_pyprof.target.agent")

        self.assertEqual(loaded - ALLOWED, {"_vscode_pyprof.target.agent"})

    def test_launcher_import_loads_no_collector_code(self) -> None:
        loaded = self.loaded_package_modules("_vscode_pyprof.target.launcher")

        self.assertEqual(loaded - ALLOWED, {"_vscode_pyprof.target.launcher"})
