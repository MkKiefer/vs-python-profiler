"""Collector session: owns the sampler, the agent connection and the store.

One collector process serves exactly one profiling session. It always runs
with the *target's* interpreter (Tachyon's remote unwinder is tied to the
target's CPython version and build).
"""

import gzip
import itertools
import json
import os
import sys
import threading

from _vscode_pyprof import PACKAGE_DIR, PROTOCOL_VERSION
from _vscode_pyprof.agent_injector import AgentInjectionError, AgentInjector
from _vscode_pyprof.agent_server import AgentConnection, AgentError, AgentListener, AgentServer
from _vscode_pyprof.funcresolver import FuncResolver
from _vscode_pyprof.options import CollectorOptions
from _vscode_pyprof.records import AllocationSite, MemorySnapshot
from _vscode_pyprof.rpc import RpcError, RpcServer
from _vscode_pyprof.sampler import Sampler, SamplerFactory, SamplerListener
from _vscode_pyprof.store import FrameKey, Store
from _vscode_pyprof.tachyon import Tachyon, TachyonError
from _vscode_pyprof.wire import JsonObject, WireReader


class Collector(AgentListener, SamplerListener):
    _FLUSH_INTERVAL = 0.25  # seconds between live deltas
    _EXIT_DELAY = 0.2  # lets the shutdown response reach the extension
    _SLOW_AGENT_TIMEOUT = 120.0  # snapshots and object counts walk the whole heap

    def __init__(
        self,
        rpc: RpcServer,
        store: Store,
        agent_server: AgentServer,
        injector: AgentInjector,
        sampler_factory: SamplerFactory,
        resolver: FuncResolver,
    ) -> None:
        self._rpc = rpc
        self._store = store
        self._agent_server = agent_server
        self._injector = injector
        self._sampler_factory = sampler_factory
        self._resolver = resolver
        self._options = CollectorOptions()
        self._sampler: Sampler | None = None
        self._agent: AgentConnection | None = None
        self._state = "idle"
        self._lock = threading.RLock()
        self._snapshot_ids = itertools.count(1)
        self._pump_stop = threading.Event()
        self._pump_started = False

    def start(self) -> None:
        """Register the RPC API and start accepting agents."""
        handlers = {
            "initialize": self._rpc_initialize,
            "attach": self._rpc_attach,
            "stop": self._rpc_stop,
            "status": self._rpc_status,
            "tracemalloc": self._rpc_tracemalloc,
            "snapshot": self._rpc_snapshot,
            "objectCounts": self._rpc_object_counts,
            "asyncioDebug": self._rpc_asyncio_debug,
            "mark": self._rpc_mark,
            "save": self._rpc_save,
            "shutdown": self._rpc_shutdown,
        }
        for method, handler in handlers.items():
            self._rpc.register(method, handler)
        self._agent_server.start(self)

    # ================================================================ RPC API
    def _rpc_initialize(self, params: WireReader) -> JsonObject:
        Tachyon.require()
        self._options = CollectorOptions.from_wire(params.get_object("options"))
        self._store.configure(strip_launcher=self._options.strip_launcher)
        self._store.set_meta(options=self._options.to_wire(), label=params.get_optional_str("label"))
        with self._lock:
            if not self._pump_started:
                self._pump_started = True
                threading.Thread(target=self._pump, name="pyprof-pump", daemon=True).start()
        return {
            "protocol": PROTOCOL_VERSION,
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": sys.platform,
            "pid": os.getpid(),
            "agentAddress": self._agent_server.address,
            "packageDir": PACKAGE_DIR,
            "features": {
                "gcStats": Tachyon.supports_gc_stats(),
                "remoteExec": self._injector.is_supported(),
                "asyncAware": Tachyon.supports_async_stacks(),
            },
        }

    def _rpc_attach(self, params: WireReader) -> JsonObject:
        pid = params.get_int("pid")
        sampler = self._start_sampler(pid)
        injected = False
        inject_error: str | None = None
        if params.get_bool("inject", True) and self._agent is None:
            try:
                self._injector.inject(pid, self._agent_server.address, self._options.agent_options())
                injected = True
            except AgentInjectionError as error:  # sampling still works without the agent
                inject_error = str(error)
                self._store.add_event("agent", f"Agent injection failed: {error}")
        return {"pid": sampler.pid, "injected": injected, "injectError": inject_error}

    def _rpc_stop(self, params: WireReader) -> JsonObject:
        with self._lock:
            if self._sampler is not None:
                self._sampler.stop()
            agent, self._agent = self._agent, None
            self._state = "stopped"
        if agent is not None:
            agent.close()
        self._flush()
        self._rpc.notify("state", {"state": "stopped", "reason": params.get_str("reason", "user")})
        return {"ok": True}

    def _rpc_status(self, _params: WireReader) -> JsonObject:
        return {
            "state": self._state,
            "pid": self._sampler.pid if self._sampler else None,
            "agent": self._agent is not None,
            "stats": self._store.stats(),
        }

    def _rpc_tracemalloc(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        enabled = params.get_bool("enabled", True)
        self._options = self._options.with_tracemalloc(enabled)
        if not enabled:
            return self._ask(agent, "tracemalloc_stop").to_dict()
        frames = params.get_int("frames", self._options.tracemalloc_frames)
        return self._ask(agent, "tracemalloc_start", {"frames": frames}).to_dict()

    def _rpc_snapshot(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        reply = self._ask(agent, "snapshot", {"limit": params.get_int("limit", 3000)}, self._SLOW_AGENT_TIMEOUT)
        sites: list[AllocationSite] = []
        for entry in reply.get_list("top"):
            site = self._allocation_site(entry)
            if site is not None:
                sites.append(site)
        snapshot_id = next(self._snapshot_ids)
        take_ms = reply.get_float("takeMs") if reply.has("takeMs") else None
        snapshot = MemorySnapshot(
            snapshot_id=snapshot_id,
            label=params.get_optional_str("label") or f"Snapshot {snapshot_id}",
            t=round(self._store.to_session_ms(reply.get_float("t")), 2),
            total_size=reply.get_int("totalSize"),
            total_count=reply.get_int("totalCount"),
            other_size=reply.get_int("otherSize"),
            other_count=reply.get_int("otherCount"),
            traced=reply.get_int("traced"),
            peak=reply.get_int("peak"),
            take_ms=take_ms,
            sites=tuple(sites),
        )
        self._store.add_snapshot(snapshot)
        self._store.add_marker(snapshot.label, snapshot.t)
        return {"id": snapshot.snapshot_id, "totalSize": snapshot.total_size, "entries": len(sites)}

    def _rpc_object_counts(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        reply = self._ask(agent, "object_counts", {"limit": params.get_int("limit", 60)}, self._SLOW_AGENT_TIMEOUT)
        t = self._store.to_session_ms(reply.get_float("t"))
        counts = reply.get_list("counts")
        self._store.add_object_counts(t, counts)
        return {"t": t, "counts": counts}

    def _rpc_asyncio_debug(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        enabled = params.get_bool("enabled", True)
        self._options = self._options.with_asyncio_debug(enabled)
        slow_ms = params.get_float("slowMs", self._options.slow_callback_ms)
        return self._ask(agent, "asyncio_debug", {"enabled": enabled, "slowMs": slow_ms}).to_dict()

    def _rpc_mark(self, params: WireReader) -> JsonObject:
        self._store.add_marker(params.get_str("name", "marker"))
        return {"ok": True}

    def _rpc_save(self, params: WireReader) -> JsonObject:
        path = params.get_str("path")
        self._flush()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temporary = path + ".tmp"
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(self._store.full(), f, separators=(",", ":"), default=str)
        os.replace(temporary, path)
        return {"path": path, "bytes": os.path.getsize(path)}

    def _rpc_shutdown(self, _params: WireReader) -> JsonObject:
        try:
            self._rpc_stop(WireReader({"reason": "shutdown"}))
        finally:
            self._agent_server.close()
            self._pump_stop.set()
            timer = threading.Timer(self._EXIT_DELAY, os._exit, args=(0,))
            timer.daemon = True
            timer.start()
        return {"ok": True}

    # ========================================================== agent events
    def on_agent_hello(self, connection: AgentConnection) -> None:
        hello = connection.hello
        self._agent = connection
        self._injector.cleanup()
        self._store.set_meta(agent=True, executable=hello.executable, argv=hello.argv, cwd=hello.cwd)
        self._apply_thread_names(hello.threads)
        self._store.add_event("agent", f"Agent connected (pid {hello.pid})")
        self._rpc.notify("agent", {"connected": True, "pid": hello.pid, "argv": hello.argv, "cwd": hello.cwd})
        # launch mode: the launcher's agent tells us which pid to sample
        if self._sampler is None:
            try:
                self._start_sampler(hello.pid)
            except RpcError as error:
                self._rpc.notify("error", {"message": str(error)})

    def on_agent_message(self, connection: AgentConnection, message: WireReader) -> None:
        if message.get_optional_str("type") != "metrics":
            return
        store = self._store
        t = store.now()
        self._apply_thread_names(message.get_list("threads"))
        if message.has("traced"):
            store.add_track("traced", t, message.get_int("traced"))
            store.add_track("tracedPeak", t, message.get_int("tracedPeak"))
        loops = [WireReader.of(loop) for loop in message.get_list("loops")]
        if loops:
            store.add_track("loopLag", t, round(max(loop.get_float("lagMs") for loop in loops), 3))
            task_counts = [loop.get_int("tasks") for loop in loops if loop.has("tasks")]
            if task_counts:
                store.add_track("loopTasks", t, sum(task_counts))
        for raw_event in message.get_list("events"):
            if isinstance(raw_event, dict):
                self._add_agent_event(raw_event, t)

    def on_agent_close(self, connection: AgentConnection) -> None:
        if self._agent is connection:
            self._agent = None
            self._store.add_event("agent", "Agent disconnected")
            self._rpc.notify("agent", {"connected": False})

    # ======================================================== sampler events
    def on_target_exit(self, reason: str) -> None:
        self._state = "exited"
        self._agent = None
        self._flush()
        self._rpc.notify("state", {"state": "exited", "reason": reason})

    def on_children(self, pids: list[int]) -> None:
        self._rpc.notify("children", {"pids": pids})

    # ============================================================== internals
    def _require_agent(self) -> AgentConnection:
        agent = self._agent
        if agent is None or not agent.alive:
            raise RpcError(
                "The in-process agent is not connected. Memory and asyncio-debug features need it; "
                "CPU sampling works without it."
            )
        return agent

    @staticmethod
    def _ask(
        agent: AgentConnection, method: str, params: JsonObject | None = None, timeout: float = 60.0
    ) -> WireReader:
        try:
            return agent.request(method, params, timeout)
        except AgentError as error:
            raise RpcError(str(error)) from error

    def _start_sampler(self, pid: int) -> Sampler:
        with self._lock:
            if self._sampler is not None:
                return self._sampler
            try:
                sampler = self._sampler_factory.create(pid, self._store, self._options, self)
            except TachyonError as error:
                raise RpcError(str(error)) from None
            self._sampler = sampler
            self._store.set_meta(pid=sampler.pid)
            sampler.start()
            self._state = "running"
        self._rpc.notify("state", {"state": "running", "pid": sampler.pid})
        return sampler

    def _allocation_site(self, entry: object) -> AllocationSite | None:
        """Turn one ``[[[file, line], ...] oldest first, size, count]`` agent entry into a site."""
        if not isinstance(entry, list) or len(entry) != 3:
            return None
        raw_frames, size, count = entry
        if not isinstance(raw_frames, list) or not isinstance(size, int) or not isinstance(count, int):
            return None
        frames: list[FrameKey] = []
        for raw_frame in raw_frames:
            if isinstance(raw_frame, list) and len(raw_frame) == 2:
                filename, line = str(raw_frame[0]), int(raw_frame[1])
                frames.append((filename, self._resolver.resolve(filename, line), line))
        stack = self._store.intern_traceback(frames)
        if stack == Store.NO_STACK:
            return None  # allocated by the launcher itself
        return AllocationSite(stack, size, count)

    def _add_agent_event(self, raw_event: dict[object, object], fallback_t: float) -> None:
        event: JsonObject = {str(key): value for key, value in raw_event.items()}
        raw_t = event.pop("t", None)
        t = self._store.to_session_ms(raw_t) if isinstance(raw_t, (int, float)) else fallback_t
        kind = str(event.pop("kind", "asyncio"))
        message = str(event.pop("message", ""))
        self._store.add_event(kind, message, t, event)

    def _apply_thread_names(self, threads: list[object]) -> None:
        """``threads`` is ``[[ident, native_id, name], ...]``; samples may carry either id."""
        for thread in threads:
            if not isinstance(thread, list) or len(thread) != 3:
                continue
            ident, native_id, name = thread
            for thread_id in (native_id, ident):
                if isinstance(thread_id, int):
                    self._store.set_thread_name(thread_id, str(name))

    # -- streaming -----------------------------------------------------------
    def _flush(self) -> None:
        self._rpc.notify("delta", self._store.delta())

    def _pump(self) -> None:
        while not self._pump_stop.wait(self._FLUSH_INTERVAL):
            if self._rpc.closed:
                break
            self._flush()
