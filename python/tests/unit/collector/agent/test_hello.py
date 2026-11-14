import unittest

from _vscode_pyprof.collector.agent.hello import AgentHello
from _vscode_pyprof.collector.agent.thread_name import ThreadName
from _vscode_pyprof.wire import WireReader


class TestAgentHello(unittest.TestCase):
    def test_from_wire_reads_process_details(self) -> None:
        message = WireReader({"pid": 12, "executable": "/usr/bin/python3.15", "argv": ["app.py", "1"], "cwd": "/work"})

        hello = AgentHello.from_wire(message)

        self.assertEqual(hello, AgentHello(12, "/usr/bin/python3.15", ["app.py", "1"], "/work", []))

    def test_from_wire_reads_thread_names(self) -> None:
        message = WireReader({"pid": 12, "threads": [[1, 101, "MainThread"]]})

        self.assertEqual(AgentHello.from_wire(message).threads, [ThreadName(1, 101, "MainThread")])


if __name__ == "__main__":
    unittest.main()
