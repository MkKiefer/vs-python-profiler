"""Collector entry point.

The extension starts the collector with the target's interpreter in isolated
mode so nothing from the user's environment can interfere::

    python -I -c "import sys; sys.path.insert(0, sys.argv.pop(1)); \
                  from _vscode_pyprof.cli import main; main()" <dir> serve

This module must stay importable on older interpreters (Python 3.10+) so it can
report a clear version error; everything that needs Python 3.15 is imported
after the check.
"""

import os
import sys

from _vscode_pyprof import MIN_PYTHON


class CollectorCli:
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
        from _vscode_pyprof.agent_injector import AgentInjector
        from _vscode_pyprof.agent_server import AgentServer
        from _vscode_pyprof.collector import Collector
        from _vscode_pyprof.frame_classifier import FrameClassifier
        from _vscode_pyprof.funcresolver import FuncResolver
        from _vscode_pyprof.rpc import RpcServer
        from _vscode_pyprof.sampler import SamplerFactory
        from _vscode_pyprof.store import Store

        out = sys.stdout.buffer
        sys.stdout = sys.stderr  # nothing may print to the RPC channel
        rpc = RpcServer(sys.stdin.buffer, out)
        collector = Collector(
            rpc=rpc,
            store=Store(FrameClassifier.for_running_interpreter()),
            agent_server=AgentServer(),
            injector=AgentInjector(),
            sampler_factory=SamplerFactory(),
            resolver=FuncResolver(),
        )
        collector.start()
        rpc.serve()
        # stdin closed: the extension went away
        os._exit(0)


def main() -> None:
    CollectorCli().run(sys.argv[1:])  # the bootstrap already popped <dir>


if __name__ == "__main__":
    main()
