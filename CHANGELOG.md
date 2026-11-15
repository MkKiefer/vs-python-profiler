# Changelog

All notable changes to the Python Profiler extension. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

First release.

### Added

- CPU profiling for Python 3.15+ with CPython's built-in sampling profiler (Tachyon, PEP 799):
  start a program with the profiler, or attach to a running one, on Windows, Linux and macOS.
- Starting points: the current file, existing `debugpy` launch configurations, dedicated
  `python-profiler` launch configurations, the test at the cursor, and the Python Processes view.
- Live dashboard: overview with insights, flame graph, call tree, bottom-up view, top functions,
  callers and callees, and wall / CPU / GIL views from one recording.
- Timeline of threads (on-CPU and GIL waits), GC, CPU, memory and event-loop lag on one time
  axis; dragging zooms every view.
- Memory: RSS and traced memory over time, tracemalloc snapshots, snapshot diff, allocation
  flame graph, live object counts and GC pauses.
- asyncio: task timeline, async-aware flame graph, event-loop lag and asyncio debug mode
  (slow callbacks, never-awaited coroutines).
- Editor integration: per-line heat in the gutter, inline timings and CodeLens, following the
  dashboard's time range, mode and thread filter.
- Saved `.vspyprof` profiles open in the dashboard; export to speedscope and collapsed stacks.
- Workspace Trust: profiling and attaching need a trusted workspace; saved profiles open in
  Restricted Mode.

[Unreleased]: https://github.com/MkKiefer/vs-python-profiler/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MkKiefer/vs-python-profiler/releases/tag/v0.1.0
