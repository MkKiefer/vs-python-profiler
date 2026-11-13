"""VS Code Python Profiler - collector, launcher and in-process agent.

The package name is deliberately private (leading underscore, vendor prefix) so
it can never collide with a user's own modules when it is temporarily placed on
``sys.path`` of a profiled program.
"""

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROTOCOL_VERSION = 1
MIN_PYTHON = (3, 15)
