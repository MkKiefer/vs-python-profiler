"""The messages the collector receives from the extension; its ``WireDecoder`` is built from them.

What it sends (results in ``rpc_results``, ``notifications``) needs no list: any dataclass can be written.
"""

from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.requests import (
    Attach,
    CountObjects,
    GetStatus,
    Initialize,
    Mark,
    Save,
    SetAsyncioDebug,
    SetTracemalloc,
    Shutdown,
    Stop,
    TakeSnapshot,
)
from _vspyprof.wire import Request

FROM_EXTENSION: tuple[type, ...] = (
    Request,
    Initialize,
    CollectorOptions,
    Attach,
    Stop,
    GetStatus,
    SetTracemalloc,
    TakeSnapshot,
    CountObjects,
    SetAsyncioDebug,
    Mark,
    Save,
    Shutdown,
)
