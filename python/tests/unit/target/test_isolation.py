"""The code that runs inside the profiled program stays apart from the collector.

Whatever ``_vscode_pyprof.target`` imports is loaded into the user's program, so
it may use only itself, the package root and the modules it shares with the
collector (``wire``, ``agent_protocol``), and it must not load stdlib modules the
program may not use itself (the agent's ``lazy`` imports).
"""

import json
import os
import subprocess
import sys
import unittest

from _vscode_pyprof import PACKAGE_DIR

SHARED = ("_vscode_pyprof", "_vscode_pyprof.wire")
SHARED_PACKAGES = ("_vscode_pyprof.agent_protocol", "_vscode_pyprof.target")
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

    def foreign_package_modules_loaded_by(self, module: str) -> set[str]:
        """Profiler modules loaded by `module` that are neither shared nor part of the target package."""
        return {
            name
            for name in self.modules_loaded_by(module)
            if name.startswith("_vscode_pyprof")
            and name not in SHARED
            and not any(name == package or name.startswith(package + ".") for package in SHARED_PACKAGES)
        }

    def test_agent_import_loads_no_collector_code(self) -> None:
        self.assertEqual(self.foreign_package_modules_loaded_by("_vscode_pyprof.target.agent"), set())

    def test_launcher_import_loads_no_collector_code(self) -> None:
        self.assertEqual(self.foreign_package_modules_loaded_by("_vscode_pyprof.target.launcher"), set())

    def test_launcher_import_does_not_load_the_agent(self) -> None:
        loaded = self.modules_loaded_by("_vscode_pyprof.target.launcher")

        self.assertNotIn("_vscode_pyprof.target.agent", loaded)

    def test_agent_import_leaves_feature_modules_unloaded(self) -> None:
        loaded = self.modules_loaded_by("_vscode_pyprof.target.agent")

        self.assertEqual(loaded & FEATURE_MODULES, set())
