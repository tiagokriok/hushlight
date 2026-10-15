#!/usr/bin/env python3
"""Entry point: stream Hushlight status snapshots as newline-delimited JSON.

Runs until SIGINT/SIGTERM. Invoked by the QML widget through an owned
Quickshell Process; also runnable directly for validation:

    python3 backend/main.py
"""

import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import runtime  # noqa: E402  (path setup must precede import)


def main():
    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    runtime.run(sys.stdout, stop_event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
