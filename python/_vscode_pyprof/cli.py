"""Collector entry point.

The extension starts the collector with the target's interpreter in isolated
mode so nothing from the user's environment can interfere::

    python -I -c "import sys; sys.path.insert(0, sys.argv.pop(1)); \
                  from _vscode_pyprof.cli import main; main()" <dir> serve
"""

from __future__ import annotations

import json
import sys


def main():
    args = sys.argv[1:]  # the bootstrap already popped <dir>
    cmd = args[0] if args else "serve"
    if cmd == "serve":
        from . import MIN_PYTHON

        if sys.version_info < MIN_PYTHON:
            sys.stderr.write(f"Python {'.'.join(map(str, MIN_PYTHON))}+ required, got {sys.version}\n")
            sys.exit(3)
        from .collector import serve

        serve()
    elif cmd == "processes":
        from .processes import list_processes

        json.dump(list_processes(), sys.stdout)
    elif cmd == "version":
        print(json.dumps({"version": sys.version.split()[0], "executable": sys.executable}))
    else:
        sys.stderr.write(f"unknown command {cmd!r}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
