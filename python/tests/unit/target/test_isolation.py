"""The code that runs inside the profiled program stays apart from the collector.

Whatever ``_vscode_pyprof.target`` imports is loaded into the user's program, so
it may use only itself, the package root and the shared ``wire`` module, and it
must not load stdlib modules the program may not use itself (the agent's
``lazy`` imports).
"""

import json
import os
import subprocess
import sys
import unittest

from _vscode_pyprof import PACKAGE_DIR

ALLOWED = {"_vscode_pyprof", "_vscode_pyprof.wire", "_vscode_pyprof.target"}
# what a profile shows, and what the agent's "does the program use asyncio?" check reads
FEATURE_MODULES = {"asyncio", "logging", "tracemalloc", "warnings"}


class TestTargetIsolation(unittest.TestCase):
    def modules_loaded_by(self, module: str) -> set[str]:
        """Modules that importing `module` adds to a fresh, isolated interpreter."""
        script = (
            "import json, sys; before = set(sys.modules); sys.path.insert(0, sys.argv[1]); "
            f"import {module}; "
            "print(json.dumps(sorted(set(sys.modules) - before)))"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, os.path.dirname(PACKAGE_DIR)],
            capture_output=True,
            text=True,
            check=True,
        )
        return set(json.loads(result.stdout))

    def package_modules_loaded_by(self, module: str) -> set[str]:
        return {m for m in self.modules_loaded_by(module) if m.startswith("_vscode_pyprof")}

    def test_agent_import_loads_no_collector_code(self) -> None:
        loaded = self.package_modules_loaded_by("_vscode_pyprof.target.agent")

        self.assertEqual(loaded - ALLOWED, {"_vscode_pyprof.target.agent"})

    def test_launcher_import_loads_no_collector_code(self) -> None:
        loaded = self.package_modules_loaded_by("_vscode_pyprof.target.launcher")

        self.assertEqual(loaded - ALLOWED, {"_vscode_pyprof.target.launcher"})

    def test_agent_import_leaves_feature_modules_unloaded(self) -> None:
        loaded = self.modules_loaded_by("_vscode_pyprof.target.agent")

        self.assertEqual(loaded & FEATURE_MODULES, set())
