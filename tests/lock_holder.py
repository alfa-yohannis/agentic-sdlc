"""Stands in for a running runner, in a process of its own, for the tests.

It takes the runner's lock in the runtime folder given on the command line,
waits for a stop request the way the runner does, then releases the lock and
exits. Run it as

    python lock_holder.py <runtime folder> [--stubborn] [--fail]

With --stubborn, it ignores stop requests and holds the lock for a minute,
so that the test can check that the runner gets killed. With --fail, it
prints an error and exits at once without taking the lock.
"""

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS_PATH = str(HERE.parent / "agents")
sys.path.insert(0, AGENTS_PATH)

import os_support  # noqa: E402
import run_agents  # noqa: E402


def main() -> None:
    """Hold the runner's lock until asked to stop (or for a minute with --stubborn), then release it."""
    if "--fail" in sys.argv:
        print("Something went wrong before the lock.", flush=True)
        sys.exit(1)
    runtime_dir = Path(sys.argv[1])
    platform = os_support.current_platform(runtime_dir)
    lock_path = runtime_dir / "run_agents.pid"
    lock = run_agents.RunnerLock(lock_path, platform)
    if not lock.acquire():
        sys.exit("Another process holds the lock.")
    platform.forget_stop_request()
    if "--stubborn" in sys.argv:
        if os.name != "nt":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
    else:
        stopping = asyncio.Event()
        waiting = platform.handle_stop_requests(stopping)
        asyncio.run(waiting)
    lock.release()


if __name__ == "__main__":
    main()
