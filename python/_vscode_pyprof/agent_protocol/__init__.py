"""The contract between the collector and the in-process agent.

Both ends build and read their messages through the classes in this package,
so they cannot drift apart: the side that sends calls ``to_wire()``, the side
that receives calls ``from_wire()`` on the same class. The package is loaded
into the profiled program: it is stdlib-only and imports nothing the agent
does not need anyway.
"""
