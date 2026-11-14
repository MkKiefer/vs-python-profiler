"""Code that runs inside the profiled program.

``launcher`` starts the user's program ("Run with Profiler") and ``agent`` is the
in-process agent, started by the launcher or injected into a running program
with ``sys.remote_exec``. Both import as little as possible: whatever they import
would slow the program down and show up in its profile. They share only
``_vscode_pyprof.wire`` with the collector.
"""
