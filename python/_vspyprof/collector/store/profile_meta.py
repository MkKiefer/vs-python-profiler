"""Facts about the session a profile was recorded in."""

import sys
import sysconfig
import time
from dataclasses import dataclass

from _vspyprof.collector.options import CollectorOptions
from _vspyprof.wire import JsonObject


@dataclass(frozen=True, slots=True)
class ProfileMeta:
    """Mirror of ``ProfileMeta`` in ``src/shared/model.ts``.

    The interpreter facts are known from the start; the others are filled in as
    the session learns them and are left out of the profile until then (the
    dashboard merges ``meta`` objects, so a ``null`` would erase a known value).
    """

    python: str
    implementation: str
    free_threaded: bool
    platform: str
    started_at: float
    """Wall-clock time (``time.time()``) the session started."""
    options: CollectorOptions | None = None
    label: str | None = None
    pid: int | None = None
    """The sampled process."""
    agent: bool = False
    """True once the in-process agent has connected."""
    executable: str | None = None
    argv: list[str] | None = None
    cwd: str | None = None

    @classmethod
    def for_running_interpreter(cls) -> ProfileMeta:
        """Meta of a session that starts now; the collector runs with the target's interpreter."""
        return cls(
            python=sys.version.split()[0],
            implementation=sys.implementation.name,
            free_threaded=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            platform=sys.platform,
            started_at=time.time(),
        )

    def to_profile(self) -> JsonObject:
        meta: JsonObject = {
            "python": self.python,
            "implementation": self.implementation,
            "freeThreaded": self.free_threaded,
            "platform": self.platform,
            "startedAt": self.started_at,
        }
        known_later: JsonObject = {
            "options": self._options_profile(self.options) if self.options is not None else None,
            "label": self.label,
            "pid": self.pid,
            "agent": self.agent or None,
            "executable": self.executable,
            "argv": self.argv,
            "cwd": self.cwd,
        }
        meta.update((key, value) for key, value in known_later.items() if value is not None)
        return meta

    @staticmethod
    def _options_profile(options: CollectorOptions) -> JsonObject:
        return {
            "rateHz": options.rate_hz,
            "native": options.native,
            "gc": options.gc,
            "asyncAware": options.async_aware,
            "tracemalloc": options.tracemalloc,
            "tracemallocFrames": options.tracemalloc_frames,
            "asyncioDebug": options.asyncio_debug,
            "slowCallbackMs": options.slow_callback_ms,
            "stripLauncher": options.strip_launcher,
            "blocking": options.blocking,
        }
