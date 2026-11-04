"""A backtest's days worked on at the same time (#81): one-day chunks (backtest.day_chunk) handed to a pool of worker
processes, and given back in day order for backtest.run to put together.

Processes, not threads: a day is Python code, and Python runs one thread of it at a time, so threads made a run no
faster, while two processes made it about twice as fast on two cores. One pool serves every run the paper worker
(worker.py) has going: Config, Backtests, Workers is how many days are worked on at once in all, read as each day
is handed out, so a change applies to runs already going. The processes start as they're first needed.
"""
from __future__ import annotations

import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from .. import store
from . import backtest

WAIT_SECONDS = 0.2           # how often a run waiting for a day or a free worker checks whether it was stopped


def _chunk(data_dir: str, fn, args: tuple):
    """In a worker process: the day, from the same data folder as the run."""
    store.DATA_DIR = Path(data_dir)
    return fn(*args)


class DayPool:
    def __init__(self, limit=lambda: backtest.defaults()["workers"], max_workers: int = backtest.MAX_WORKERS):
        self._limit = limit
        self._max = max_workers
        self._busy = 0
        self._room = threading.Condition()
        self._pool = self._new_pool()

    def _new_pool(self) -> ProcessPoolExecutor:
        # not fork: the paper worker has threads going, and forked processes would copy their locks mid-use
        return ProcessPoolExecutor(self._max, mp_context=multiprocessing.get_context("forkserver"))

    def _renew(self, broken: ProcessPoolExecutor) -> None:
        """A process died (out of memory, killed): the pool can't be used again, so a new one takes its place for
        the runs after (once, however many runs saw it break)."""
        with self._room:
            if self._pool is broken:
                self._pool = self._new_pool()
                broken.shutdown(wait=False, cancel_futures=True)

    def limit(self) -> int:
        try:
            n = int(self._limit())
        except (ValueError, TypeError, OSError):
            n = 1
        return max(1, min(self._max, n))

    def _take(self, check, wait: bool) -> bool:
        with self._room:
            while self._busy >= self.limit():
                if not wait:
                    return False
                check()
                self._room.wait(WAIT_SECONDS)
            self._busy += 1
            return True

    def _give(self, _future=None) -> None:
        with self._room:
            self._busy -= 1
            self._room.notify_all()

    def in_order(self, fn, args_list: list[tuple], check, started=None, finished=None):
        """fn(*args) for each args in other processes, as many at a time as the limit allows across every run;
        the results in the order given. started(args[2]) as each is handed out, finished(args[2]) as its process
        is done with it, before it's given back (args[2]: the day, for backtest.run's callers). check() raises to
        stop: the days not started yet are dropped."""
        data_dir, futures, nxt, n = str(store.DATA_DIR), {}, 0, len(args_list)
        pool, told = self._pool, set()

        def tell_finished():                      # in this thread: days whose processes are done, in any order
            for k, fut in futures.items():
                if k not in told and fut.done():
                    told.add(k)
                    if finished:
                        finished(args_list[k][2])
        try:
            for i in range(n):
                while nxt < n and self._take(check, wait=nxt == i):    # the one needed now waits for room; later ones only if there's room
                    tell_finished()                   # a slot freed here: the day that freed it shows as worked first
                    try:
                        f = pool.submit(_chunk, data_dir, fn, args_list[nxt])
                    except BrokenProcessPool:
                        self._give()
                        raise
                    f.add_done_callback(self._give)
                    futures[nxt] = f
                    if started:
                        started(args_list[nxt][2])
                    nxt += 1
                while True:
                    check()
                    try:
                        result = futures[i].result(timeout=WAIT_SECONDS)
                        break
                    except FutureTimeout:
                        tell_finished()
                tell_finished()
                del futures[i]
                yield result
        except BrokenProcessPool:
            self._renew(pool)
            raise RuntimeError("A worker process working on a day stopped unexpectedly (out of memory?). "
                               "Run it again; fewer Workers (Config, Backtests) use less memory.") from None
        finally:
            for f in futures.values():
                f.cancel()

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
