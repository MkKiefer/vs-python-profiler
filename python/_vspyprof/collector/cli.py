"""Collector entry point.

The extension starts the collector with the target's interpreter in isolated
mode so nothing from the user's environment can interfere::

    python -I -c "import sys; sys.path.insert(0, sys.argv.pop(1)); \
                  from _vspyprof.collector.cli import main; main()" <dir> serve

This module must stay importable on older interpreters (Python 3.10+) so it can
report a clear version error; everything that needs Python 3.15 is imported
after the check.
"""

import os
import sys

from _vspyprof import MIN_PYTHON


class CollectorCli:
    """Command line of the collector process and the place where a session is assembled."""

    EXIT_USAGE = 2
    EXIT_UNSUPPORTED_PYTHON = 3

    def run(self, args: list[str]) -> None:
        command = args[0] if args else "serve"
        if command != "serve":
            sys.stderr.write(f"unknown command {command!r}\n")
            sys.exit(self.EXIT_USAGE)
        self._serve()

    def _serve(self) -> None:
        if sys.version_info < MIN_PYTHON:
            wanted = ".".join(map(str, MIN_PYTHON))
            sys.stderr.write(f"Python {wanted}+ required, got {sys.version}\n")
            sys.exit(self.EXIT_UNSUPPORTED_PYTHON)
        # Deliberately imported here: these modules use Python 3.15 syntax and APIs.
        from _vspyprof.agent_protocol.messages import FROM_AGENT
        from _vspyprof.collector.agent.injector import AgentInjector
        from _vspyprof.collector.agent.server import AgentServer
        from _vspyprof.collector.frames.frame_classifier import FrameClassifier
        from _vspyprof.collector.frames.func_resolver import FuncResolver
        from _vspyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
        from _vspyprof.collector.messages import FROM_EXTENSION
        from _vspyprof.collector.profile_writer import ProfileWriter
        from _vspyprof.collector.rpc import RpcServer
        from _vspyprof.collector.sampling.process_stats_reader_factory import ProcessStatsReaderFactory
        from _vspyprof.collector.sampling.sampler_factory import SamplerFactory
        from _vspyprof.collector.session import CollectorSession
        from _vspyprof.collector.store.session_clock import SessionClock
        from _vspyprof.collector.store.stack_table import StackTable
        from _vspyprof.collector.store.store import Store
        from _vspyprof.wire import WireDecoder, WireEncoder

        out = sys.stdout.buffer
        sys.stdout = sys.stderr  # nothing may print to the RPC channel
        encoder = WireEncoder()
        rpc = RpcServer(sys.stdin.buffer, out, encoder, WireDecoder(FROM_EXTENSION))
        clock = SessionClock()
        store = Store(clock, StackTable(FrameClassifier.for_running_interpreter()))
        session = CollectorSession(
            rpc=rpc,
            store=store,
            clock=clock,
            agent_server=AgentServer(encoder, WireDecoder(FROM_AGENT)),
            injector=AgentInjector(),
            sampler_factory=SamplerFactory(store, clock, ProcessStatsReaderFactory()),
            snapshot_builder=MemorySnapshotBuilder(store, clock, FuncResolver()),
            profile_writer=ProfileWriter(),
            encoder=encoder,
        )
        session.start()
        rpc.serve(session.run)
        # stdin closed: the extension went away
        os._exit(0)


def main() -> None:
    CollectorCli().run(sys.argv[1:])  # the bootstrap already popped <dir>


if __name__ == "__main__":
    main()
