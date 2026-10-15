"""Test helper: spawn an owned child, report its pid, then wait.

Used by the parent-death test. Killing this helper with SIGKILL must also take
down the child it spawned, via PR_SET_PDEATHSIG. Not a test module (name does
not match the discovery pattern).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.runtime import PopenChild  # noqa: E402

if __name__ == "__main__":
    child = PopenChild(["sleep", "120"])
    sys.stdout.write("%d\n" % child.pid)
    sys.stdout.flush()
    time.sleep(60)
