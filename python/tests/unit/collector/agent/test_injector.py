import os
import sys
import unittest
from unittest import mock

from _vscode_pyprof.collector.agent.injector import AgentInjectionError, AgentInjector


@unittest.skipUnless(AgentInjector.is_supported(), "needs sys.remote_exec")
class TestAgentInjector(unittest.TestCase):
    def setUp(self) -> None:
        self.injector = AgentInjector()
        self.addCleanup(self.injector.cleanup)
        self.scripts: list[str] = []
        self.script_sources: list[str] = []

    def record_script(self, _pid: int, path: str) -> None:
        self.scripts.append(path)
        with open(path, encoding="utf-8") as f:
            self.script_sources.append(f.read())

    def test_inject_runs_script_that_starts_agent_with_address_and_options(self) -> None:
        with mock.patch.object(sys, "remote_exec", side_effect=self.record_script):
            self.injector.inject(4242, "127.0.0.1:5123:abc", {"tracemalloc": True})

        compile(self.script_sources[0], self.scripts[0], "exec")
        self.assertIn("agent.start('127.0.0.1:5123:abc', {'tracemalloc': True})", self.script_sources[0])

    def test_inject_when_remote_exec_fails_raises_injection_error_and_removes_script(self) -> None:
        def fail(pid: int, path: str) -> None:
            self.record_script(pid, path)
            raise RuntimeError("Remote debugging is disabled")

        with mock.patch.object(sys, "remote_exec", side_effect=fail), self.assertRaises(AgentInjectionError) as ctx:
            self.injector.inject(4242, "127.0.0.1:5123:abc", {})

        self.assertIn("PYTHON_DISABLE_REMOTE_DEBUG", str(ctx.exception))
        self.assertFalse(os.path.exists(self.scripts[0]))

    def test_cleanup_deletes_script(self) -> None:
        with mock.patch.object(sys, "remote_exec", side_effect=self.record_script):
            self.injector.inject(4242, "127.0.0.1:5123:abc", {})

        self.injector.cleanup()

        self.assertFalse(os.path.exists(self.scripts[0]))


if __name__ == "__main__":
    unittest.main()
