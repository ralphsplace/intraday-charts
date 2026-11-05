"""One supervised backtest runner with at most five job threads: python -m app.backtesting.worker. The runs' days are worked
on in a shared pool of processes (days.py), as many at once as Config, Backtests, Workers says.

The lifetime lock stays held until every thread has exited. Web workers only enqueue/read/delete;
restarting them cannot interrupt jobs or multiply this pool. Fetch waits also occupy a slot.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .. import jsonfile, upgrade
from . import days, jobs

log = logging.getLogger(__name__)


def run(stop: threading.Event, workers: int = 5, poll_seconds: float = 0.2, ready=None, day_pool=None) -> None:
    """Run the queue until stop is set. day_pool: the pool the runs' days are worked on in (days.DayPool, made
    here and shut down on the way out when not given); False: each run works its days one after another."""
    if not 1 <= workers <= 5:
        raise ValueError("BACKTEST_JOB_WORKERS must be between 1 and 5")
    owner = uuid.uuid4().hex
    with jsonfile.locked(jobs.folder() / "locks" / "runner", blocking=False):
        jobs.recover()
        # No executor backlog: only submit free slots; waiting jobs stay durable on disk.
        days_pool = days.DayPool() if day_pool is None else day_pool or None
        try:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="backtest") as pool:
                pending = {}
                if ready:
                    ready.set()
                try:
                    while not stop.is_set():
                        for run_id, future in list(pending.items()):
                            if future.done():
                                try:
                                    future.result()
                                except Exception:
                                    log.exception("backtest job %s failed outside its execution handler", run_id)
                                del pending[run_id]
                        for run_id in jobs.queued():
                            if len(pending) >= workers or stop.is_set():
                                break
                            if run_id not in pending:
                                pending[run_id] = pool.submit(jobs.execute, run_id, stop, owner, days_pool)
                        with jsonfile.editing(jobs.folder() / "locks" / "status.json") as d:
                            d.update(owner=owner, heartbeat=time.time(), workers=workers, active=len(pending))
                        stop.wait(poll_seconds)
                finally:
                    stop.set()           # cooperative exit; keep runner lock until pool joins
        finally:
            if days_pool and day_pool is None:
                days_pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    upgrade.run()           # data from older versions where this worker looks for it (it may start before the server)
    try:
        run(stop, workers=int(os.environ.get("BACKTEST_JOB_WORKERS") or os.environ.get("PAPER_JOB_WORKERS") or "5"))
    except BlockingIOError:
        raise SystemExit("A backtest worker already owns this data folder") from None


if __name__ == "__main__":
    main()
