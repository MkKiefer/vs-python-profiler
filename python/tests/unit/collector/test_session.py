import gzip
import io
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, create_autospec

from _vspyprof import PROTOCOL_VERSION
from _vspyprof.agent_protocol import commands
from _vspyprof.agent_protocol.hello import AgentHello, ThreadName
from _vspyprof.agent_protocol.messages import FROM_AGENT, TO_AGENT
from _vspyprof.agent_protocol.metrics import AgentEvent, AgentMetrics, EventDetails, LoopMetrics, TracedMemory
from _vspyprof.agent_protocol.options import AgentOptions
from _vspyprof.agent_protocol.replies import (
    Allocation,
    AsyncioDebugStatus,
    HeapSnapshot,
    SourceLine,
    TracingStatus,
)
from _vspyprof.collector import requests
from _vspyprof.collector.agent.connection import AgentConnection
from _vspyprof.collector.agent.injector import AgentInjectionError, AgentInjector
from _vspyprof.collector.agent.server import AgentServer
from _vspyprof.collector.frames.frame_classifier import FrameClassifier
from _vspyprof.collector.frames.func_resolver import FuncResolver
from _vspyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
from _vspyprof.collector.messages import FROM_EXTENSION
from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.profile_writer import ProfileWriter
from _vspyprof.collector.protocol import StopReason
from _vspyprof.collector.rpc import RpcError, RpcServer
from _vspyprof.collector.rpc_results import (
    AttachResult,
    InitializeResult,
    SaveResult,
    SnapshotResult,
    StatusResult,
)
from _vspyprof.collector.sampling.process_stats_reader_factory import ProcessStatsReaderFactory
from _vspyprof.collector.sampling.sampler import Sampler
from _vspyprof.collector.sampling.sampler_factory import SamplerFactory
from _vspyprof.collector.sampling.tachyon import TachyonError
from _vspyprof.collector.session import CollectorSession
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.stack_table import StackTable
from _vspyprof.collector.store.store import Store
from _vspyprof.wire import JsonObject, LineBuffer, WireDecoder, WireEncoder
from tests.unit.json_view import JsonView


class TestCollectorSession(unittest.TestCase):
    def setUp(self) -> None:
        self.output = io.BytesIO()
        encoder = WireEncoder()
        self.rpc = RpcServer(io.BytesIO(), self.output, encoder, WireDecoder(FROM_EXTENSION))
        clock = SessionClock()
        self.store = Store(clock, StackTable(FrameClassifier.for_running_interpreter()))
        self.agent_server = AgentServer(encoder, WireDecoder(FROM_AGENT))
        self.addCleanup(self.agent_server.close)
        self.injector = AgentInjector()
        self.sampler_factory = SamplerFactory(self.store, clock, ProcessStatsReaderFactory())
        self.session = CollectorSession(
            rpc=self.rpc,
            store=self.store,
            clock=clock,
            agent_server=self.agent_server,
            injector=self.injector,
            sampler_factory=self.sampler_factory,
            snapshot_builder=MemorySnapshotBuilder(self.store, clock, FuncResolver()),
            profile_writer=ProfileWriter(),
            encoder=encoder,
        )
        self.session.start()

    # ---------------------------------------------------------------- helpers
    def notifications(self, notification_type: str) -> list[JsonObject]:
        """The notifications of one type the session wrote, without their ``type``."""
        messages = [json.loads(line) for line in self.output.getvalue().splitlines()]
        return [
            {key: value for key, value in message.items() if key != "type"}
            for message in messages
            if message["type"] == notification_type
        ]

    def connect_agent(self) -> AgentConnection:
        """A real connection object on a mocked socket, registered without starting a sampler."""
        self.sampler_factory.create = MagicMock(side_effect=TachyonError("no such process"))
        connection = AgentConnection(
            MagicMock(),
            AgentHello("token", 4242, "python", ["app.py"], "/work", "3.15.2", []),
            self.session,
            LineBuffer(),
            WireEncoder(),
            WireDecoder(FROM_AGENT),
        )
        self.session.on_agent_hello(connection)
        return connection

    # ------------------------------------------------------------------ tests
    def test_initialize_returns_agent_address_options_and_protocol(self) -> None:
        options = CollectorOptions(rate_hz=200, tracemalloc=True, tracemalloc_frames=4)

        result = self.session.run(requests.Initialize(options))

        assert isinstance(result, InitializeResult)
        self.assertEqual(
            (result.agent_address, result.protocol, result.pid),
            (self.agent_server.address, PROTOCOL_VERSION, os.getpid()),
        )
        self.assertEqual(
            WireDecoder(TO_AGENT).decode(result.agent_options), AgentOptions(tracemalloc=True, tracemalloc_frames=4)
        )

    def test_initialize_stores_options_in_profile_meta(self) -> None:
        self.session.run(requests.Initialize(CollectorOptions(rate_hz=200), label="app.py"))

        meta = JsonView(self.store.full()).get_object("meta")

        self.assertEqual(meta.get_object("options").get_int("rateHz"), 200)
        self.assertEqual(meta.get_str("label"), "app.py")

    def test_attach_when_process_cannot_be_read_raises_rpc_error(self) -> None:
        self.sampler_factory.create = MagicMock(side_effect=TachyonError("Process 1 does not exist"))

        with self.assertRaisesRegex(RpcError, "Process 1 does not exist"):
            self.session.run(requests.Attach(pid=1))

    def test_attach_when_injection_fails_still_reports_sampling(self) -> None:
        sampler = create_autospec(Sampler, instance=True, pid=77)
        self.sampler_factory.create = MagicMock(return_value=sampler)
        self.injector.inject = MagicMock(side_effect=AgentInjectionError("remote debugging disabled"))

        result = self.session.run(requests.Attach(pid=77))

        self.assertEqual(result, AttachResult(77, False, "remote debugging disabled"))
        self.assertEqual(self.notifications("StateChanged"), [{"state": "running", "pid": 77, "reason": None}])

    def test_attach_injects_agent_with_the_session_options(self) -> None:
        sampler = create_autospec(Sampler, instance=True, pid=77)
        self.sampler_factory.create = MagicMock(return_value=sampler)
        inject = MagicMock()
        self.injector.inject = inject
        self.session.run(requests.Initialize(CollectorOptions(asyncio_debug=True)))

        self.session.run(requests.Attach(pid=77))

        options = WireDecoder(TO_AGENT).decode(inject.call_args.args[2])
        self.assertEqual(options, AgentOptions(asyncio_debug=True))

    def test_attach_to_launcher_injects_agent_into_sampled_interpreter(self) -> None:
        sampler = create_autospec(Sampler, instance=True, pid=78)  # the launcher 77 started interpreter 78
        self.sampler_factory.create = MagicMock(return_value=sampler)
        inject = MagicMock()
        self.injector.inject = inject

        result = self.session.run(requests.Attach(pid=77))

        self.assertEqual(inject.call_args.args[0], 78)
        self.assertEqual(result, AttachResult(78, True, None))

    def test_attach_with_inject_disabled_does_not_inject(self) -> None:
        sampler = create_autospec(Sampler, instance=True, pid=77)
        self.sampler_factory.create = MagicMock(return_value=sampler)
        inject = MagicMock()
        self.injector.inject = inject

        self.session.run(requests.Attach(pid=77, inject=False))

        inject.assert_not_called()

    def test_take_snapshot_without_agent_raises_explanatory_rpc_error(self) -> None:
        with self.assertRaisesRegex(RpcError, "in-process agent is not connected"):
            self.session.run(requests.TakeSnapshot())

    def test_take_snapshot_with_agent_stores_resolved_allocation_sites(self) -> None:
        connection = self.connect_agent()
        heap = HeapSnapshot(0.0, 300, 3, 0, 0, 400, 500, 1.0, [Allocation([SourceLine(__file__, 1)], 300, 3)])
        connection.request = MagicMock(return_value=heap)

        result = self.session.run(requests.TakeSnapshot(label="A"))

        snapshot = JsonView.of(JsonView(self.store.full()).get_list("snapshots")[0])
        self.assertEqual(result, SnapshotResult(snapshot_id=1, total_size=300, entries=1))
        self.assertEqual((snapshot.get_str("label"), snapshot.get_int("totalSize")), ("A", 300))
        self.assertEqual(snapshot.get_list("entries"), [[0, 300, 3]])

    def test_set_tracemalloc_enable_asks_agent_to_start_tracing(self) -> None:
        connection = self.connect_agent()
        request = MagicMock(return_value=TracingStatus(True, 8))
        connection.request = request

        self.session.run(requests.SetTracemalloc(enabled=True, frames=8))

        request.assert_called_once_with(commands.StartTracing(8), TracingStatus, 60.0)

    def test_set_asyncio_debug_passes_slow_callback_threshold_to_agent(self) -> None:
        connection = self.connect_agent()
        request = MagicMock(return_value=AsyncioDebugStatus(True, 1))
        connection.request = request

        self.session.run(requests.SetAsyncioDebug(enabled=True, slow_ms=50))

        request.assert_called_once_with(commands.SetAsyncioDebug(True, 50), AsyncioDebugStatus, 60.0)

    def test_set_asyncio_debug_without_threshold_sends_the_session_one(self) -> None:
        connection = self.connect_agent()
        request = MagicMock(return_value=AsyncioDebugStatus(True, 1))
        connection.request = request
        self.session.run(requests.Initialize(CollectorOptions(slow_callback_ms=30)))

        self.session.run(requests.SetAsyncioDebug(enabled=True))

        request.assert_called_once_with(commands.SetAsyncioDebug(True, 30.0), AsyncioDebugStatus, 60.0)

    def test_agent_hello_notifies_extension(self) -> None:
        self.connect_agent()

        self.assertEqual(self.notifications("AgentConnected"), [{"pid": 4242, "argv": ["app.py"], "cwd": "/work"}])

    def test_agent_hello_when_sampling_cannot_start_reports_error(self) -> None:
        self.connect_agent()

        self.assertEqual(self.notifications("ErrorOccurred"), [{"message": "no such process"}])

    def test_agent_metrics_are_recorded_as_tracks_and_events(self) -> None:
        connection = self.connect_agent()
        metrics = AgentMetrics(
            threads=[ThreadName(1, 101, "MainThread")],
            traced=TracedMemory(1000, 2000),
            loops=[LoopMetrics(1, "MainThread", 3.5, 4), LoopMetrics(2, "worker", 120.0, 1)],
            events=[AgentEvent("slow-callback", "took 0.2s", details=EventDetails(seconds=0.2))],
        )

        self.session.on_agent_metrics(connection, metrics)

        full = JsonView(self.store.full())
        tracks = full.get_object("tracks")
        self.assertEqual(sorted(tracks.to_dict()), ["loopLag", "loopTasks", "traced", "tracedPeak"])
        first_lag = tracks.get_list("loopLag")[0]
        assert isinstance(first_lag, list)
        self.assertEqual(first_lag[1], 120.0)
        self.assertEqual(full.get_raw("threads"), {"101": "MainThread", "1": "MainThread"})
        self.assertIn("slow-callback", [JsonView.of(e).get_str("kind") for e in full.get_list("events")])

    def test_agent_close_notifies_extension(self) -> None:
        connection = self.connect_agent()

        self.session.on_agent_close(connection)

        self.assertEqual(self.notifications("AgentDisconnected"), [{}])

    def test_mark_then_save_writes_marker_to_profile_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nested", "run.vspyprof")
            self.session.run(requests.Mark(name="deploy"))

            result = self.session.run(requests.Save(path))

            with gzip.open(path, "rt", encoding="utf-8") as f:
                profile = JsonView.of(json.load(f))
            self.assertEqual(result, SaveResult(path, os.path.getsize(path)))
        self.assertEqual(profile.get_str("format"), "vspyprof")
        self.assertEqual([m[1] for m in profile.get_list("markers") if isinstance(m, list)], ["deploy"])

    def test_stop_notifies_stopped_state(self) -> None:
        self.session.run(requests.Stop(reason="user"))

        self.assertEqual(self.notifications("StateChanged")[-1], {"state": "stopped", "pid": None, "reason": "user"})

    def test_get_status_reports_idle_state_before_attach(self) -> None:
        result = self.session.run(requests.GetStatus())

        assert isinstance(result, StatusResult)
        self.assertEqual((result.state, result.agent), ("idle", False))

    def test_run_with_unknown_request_raises_rpc_error(self) -> None:
        with self.assertRaisesRegex(RpcError, "unknown request AgentOptions"):
            self.session.run(AgentOptions())

    def test_on_target_exit_notifies_exited_state(self) -> None:
        self.session.on_target_exit(StopReason.EXITED)

        self.assertEqual(self.notifications("StateChanged")[-1], {"state": "exited", "pid": None, "reason": "exited"})

    def test_on_sampler_error_reports_error_and_stopped_state(self) -> None:
        self.session.on_sampler_error("Sampling stopped: RuntimeError: boom")

        events = JsonView(self.store.full()).get_list("events")
        self.assertEqual(self.notifications("ErrorOccurred"), [{"message": "Sampling stopped: RuntimeError: boom"}])
        self.assertEqual(self.notifications("StateChanged")[-1], {"state": "stopped", "pid": None, "reason": "error"})
        status = self.session.run(requests.GetStatus())
        assert isinstance(status, StatusResult)
        self.assertEqual(status.state, "stopped")
        self.assertIn("sampler", [event["kind"] for event in events if isinstance(event, dict)])

    def test_on_children_notifies_child_pids(self) -> None:
        self.session.on_children([11, 12])

        self.assertEqual(self.notifications("ChildrenFound"), [{"pids": [11, 12]}])


if __name__ == "__main__":
    unittest.main()
