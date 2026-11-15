"""The contract between the collector and the in-process agent.

Every message is a plain dataclass in this package; both ends send them with a
``wire.WireEncoder`` and read them with a ``wire.WireDecoder`` built from the
tuples in ``messages``, so they cannot drift apart. The package is loaded into
the profiled program: it is stdlib-only and imports nothing the agent does not
need anyway.
"""
