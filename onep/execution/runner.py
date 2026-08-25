"""Command-line entry point for the durable local worker."""

from __future__ import annotations

import argparse
import signal
from threading import Event

from onep.application.studio_defaults import build_application
from onep.execution.worker import Worker


def run_worker(path: str | None = None, poll_seconds: float = 0.5) -> None:
    application = build_application(path)
    worker = Worker(application.registry, application.store)
    stopped = Event()

    def stop(*_args) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopped.is_set():
        worker.touch()
        if worker.run_once() is None:
            stopped.wait(max(0.05, poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OnePTeam V2 worker")
    parser.add_argument("--db", default=None, help="Control database path")
    parser.add_argument("--poll", type=float, default=0.5)
    args = parser.parse_args()
    run_worker(args.db, args.poll)


if __name__ == "__main__":
    main()
