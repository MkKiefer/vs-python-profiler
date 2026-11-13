import gzip
import io
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, create_autospec

from _vscode_pyprof.agent_injector import AgentInjectionError, AgentInjector
from _vscode_pyprof.agent_server import AgentConnection, AgentHello, AgentServer
from _vscode_pyprof.collector import Collector
from _vscode_pyprof.frame_classifier import FrameClassifier
from _vscode_pyprof.funcresolver import FuncResolver
from _vscode_pyprof.rpc import RpcServer
from _vscode_pyprof.sampler import Sampler, SamplerFactory
from _vscode_pyprof.store import Store
from _vscode_pyprof.tachyon import TachyonError
from _vscode_pyprof.wire import JsonObject, WireReader


class TestCollector(unittest.TestCase):
    def setUp(self) -> None:
        self.output = io.BytesIO()
        self.rpc = RpcServer(io.BytesIO(), self.output)
        self.store = Store(FrameClassifier.for_running_interpreter())
        self.agent_server = AgentServer()
        self.addCleanup(self.agent_server.close)
        self.injector = AgentInjector()
        self.sampler_factory = SamplerFactory()
        self.collector = Collector(
            rpc=self.rpc,
            store=self.store,
            agent_server=self.agent_server,
            injector=self.injector,
            sampler_factory=self.sampler_factory,
            resolver=FuncResolver(),
        )
        self.collector.start()
        self._next_id = 0

    # ---------------------------------------------------------------- helpers
    def messages(self) -> list[WireReader]:
        return [WireReader.of(json.loads(line)) for line in self.output.getvalue().splitlines()]

    def call(self, method: str, params: JsonObject | None = None) -> WireReader:
        """Send one request and return its response."""
        self._next_id += 1
        self.rpc.handle(WireReader({"id": self._next_id, "method": method, "params": params or {}}))
        responses = [m for m in self.messages() if m.get_raw("id") == self._next_id]
        self.assertEqual(len(responses), 1, msg=f"no response to {method}")
        return responses[0]

    def notifications(self, method: str) -> list[WireReader]:
        return [m.get_object("params") for m in self.messages() if m.get_optional_str("method") == method]

    def connect_agent(self) -> AgentConnection:
        """A real connection object on a mocked socket, registered without starting a sampler."""
        self.sampler_factory.create = MagicMock(side_effect=TachyonError("no such process"))
        connection = AgentConnection(MagicMock(), AgentHello(4242, "python", ["app.py"], "/work", []), self.collector)
        self.collector.on_agent_hello(connection)
        return connection

    # ------------------------------------------------------------------ tests
    def test_initialize_returns_agent_address_and_protocol(self) -> None:
        result = self.call("initialize", {"options": {"rateHz": 200}}).get_object("result")

        self.assertEqual(result.get_str("agentAddress"), self.agent_server.address)
        self.assertEqual(result.get_int("protocol"), 1)
        self.assertEqual(result.get_int("pid"), os.getpid())

    def test_initialize_stores_options_in_profile_meta(self) -> None:
        self.call("initialize", {"options": {"rateHz": 200}, "label": "app.py"})

        meta = WireReader(self.store.full()).get_object("meta")

        self.assertEqual(meta.get_object("options").get_int("rateHz"), 200)
        self.assertEqual(meta.get_str("label"), "app.py")

    def test_attach_when_process_cannot_be_read_returns_error(self) -> None:
        self.sampler_factory.create = MagicMock(side_effect=TachyonError("Process 1 does not exist"))

        response = self.call("attach", {"pid": 1})

        self.assertEqual(response.get_object("error").get_str("message"), "Process 1 does not exist")

    def test_attach_without_pid_returns_error(self) -> None:
        response = self.call("attach", {})

        self.assertEqual(response.get_object("error").get_str("type"), "WireError")

    def test_attach_when_injection_fails_still_reports_sampling(self) -> None:
        sampler = create_autospec(Sampler, instance=True, pid=77)
        self.sampler_factory.create = MagicMock(return_value=sampler)
        self.injector.inject = MagicMock(side_effect=AgentInjectionError("remote debugging disabled"))

        result = self.call("attach", {"pid": 77}).get_object("result")

        self.assertEqual(
            (result.get_int("pid"), result.get_bool("injected", True), result.get_str("injectError")),
            (77, False, "remote debugging disabled"),
        )
        self.assertEqual(self.notifications("state")[0].to_dict(), {"state": "running", "pid": 77})

    def test_attach_with_inject_disabled_does_not_inject(self) -> None:
        sampler = create_autospec(Sampler, instance=True, pid=77)
        self.sampler_factory.create = MagicMock(return_value=sampler)
        inject = MagicMock()
        self.injector.inject = inject

        self.call("attach", {"pid": 77, "inject": False})

        inject.assert_not_called()

    def test_snapshot_without_agent_returns_explanatory_error(self) -> None:
        response = self.call("snapshot")

        self.assertIn("in-process agent is not connected", response.get_object("error").get_str("message"))

    def test_snapshot_with_agent_stores_resolved_allocation_sites(self) -> None:
        connection = self.connect_agent()
        reply = {
            "t": 0.0,
            "totalSize": 300,
            "totalCount": 3,
            "otherSize": 0,
            "otherCount": 0,
            "traced": 400,
            "peak": 500,
            "takeMs": 1.0,
            "top": [[[[__file__, 1]], 300, 3]],
        }
        connection.request = MagicMock(return_value=WireReader(reply))

        result = self.call("snapshot", {"label": "A"}).get_object("result")

        snapshot = WireReader.of(WireReader(self.store.full()).get_list("snapshots")[0])
        self.assertEqual((result.get_int("id"), result.get_int("entries")), (1, 1))
        self.assertEqual((snapshot.get_str("label"), snapshot.get_int("totalSize")), ("A", 300))
        self.assertEqual(snapshot.get_list("entries"), [[0, 300, 3]])

    def test_tracemalloc_enable_asks_agent_to_start_tracing(self) -> None:
        connection = self.connect_agent()
        request = MagicMock(return_value=WireReader({"tracing": True}))
        connection.request = request

        self.call("tracemalloc", {"enabled": True, "frames": 8})

        request.assert_called_once_with("tracemalloc_start", {"frames": 8}, 60.0)

    def test_asyncio_debug_passes_slow_callback_threshold_to_agent(self) -> None:
        connection = self.connect_agent()
        request = MagicMock(return_value=WireReader({"enabled": True}))
        connection.request = request

        self.call("asyncioDebug", {"enabled": True, "slowMs": 50})

        request.assert_called_once_with("asyncio_debug", {"enabled": True, "slowMs": 50.0}, 60.0)

    def test_agent_hello_notifies_extension(self) -> None:
        self.connect_agent()

        agent = self.notifications("agent")[0]

        self.assertEqual((agent.get_bool("connected", False), agent.get_int("pid")), (True, 4242))

    def test_agent_hello_when_sampling_cannot_start_reports_error(self) -> None:
        self.connect_agent()

        self.assertEqual(self.notifications("error")[0].get_str("message"), "no such process")

    def test_agent_metrics_are_recorded_as_tracks_and_events(self) -> None:
        connection = self.connect_agent()
        metrics = {
            "type": "metrics",
            "threads": [[1, 101, "MainThread"]],
            "traced": 1000,
            "tracedPeak": 2000,
            "loops": [{"lagMs": 3.5, "tasks": 4}, {"lagMs": 120.0, "tasks": 1}],
            "events": [{"kind": "slow-callback", "message": "took 0.2s", "seconds": 0.2}],
        }

        self.collector.on_agent_message(connection, WireReader(metrics))

        full = WireReader(self.store.full())
        tracks = full.get_object("tracks")
        self.assertEqual(sorted(tracks.to_dict()), ["loopLag", "loopTasks", "traced", "tracedPeak"])
        self.assertEqual(WireReader.of({"p": tracks.get_list("loopLag")[0]}).get_list("p")[1], 120.0)
        self.assertEqual(full.get_raw("threads"), {"101": "MainThread", "1": "MainThread"})
        self.assertIn("slow-callback", [WireReader.of(e).get_str("kind") for e in full.get_list("events")])

    def test_agent_close_notifies_extension(self) -> None:
        connection = self.connect_agent()

        self.collector.on_agent_close(connection)

        self.assertFalse(self.notifications("agent")[-1].get_bool("connected", True))

    def test_mark_then_save_writes_marker_to_profile_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nested", "run.pyprof")
            self.call("mark", {"name": "deploy"})

            result = self.call("save", {"path": path}).get_object("result")

            with gzip.open(path, "rt", encoding="utf-8") as f:
                profile = WireReader.of(json.load(f))
        self.assertEqual(result.get_str("path"), path)
        self.assertEqual(profile.get_str("format"), "pyprof")
        self.assertEqual([m[1] for m in profile.get_list("markers") if isinstance(m, list)], ["deploy"])

    def test_stop_notifies_stopped_state(self) -> None:
        self.call("stop", {"reason": "user"})

        self.assertEqual(self.notifications("state")[-1].to_dict(), {"state": "stopped", "reason": "user"})

    def test_status_reports_idle_state_before_attach(self) -> None:
        result = self.call("status").get_object("result")

        self.assertEqual((result.get_str("state"), result.get_bool("agent", True)), ("idle", False))

    def test_on_target_exit_notifies_exited_state(self) -> None:
        self.collector.on_target_exit("exited")

        self.assertEqual(self.notifications("state")[-1].to_dict(), {"state": "exited", "reason": "exited"})

    def test_on_children_notifies_child_pids(self) -> None:
        self.collector.on_children([11, 12])

        self.assertEqual(self.notifications("children")[0].get_list("pids"), [11, 12])


if __name__ == "__main__":
    unittest.main()
