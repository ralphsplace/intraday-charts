"""Durable backtest queue, shared by all web processes; executed only by app.paper.worker.

Per-run locks serialize deletion and writes. An execution lock is held for the whole computation:
DELETE requests cancellation while it is held, and the worker removes the report only after unwinding.
"""
from __future__ import annotations

import time
import traceback
import uuid
from pathlib import Path

from .. import jsonfile, store
from . import backtest, fetching, rules, strategies

MAX_LOG = 20_000
MAX_QUEUED = 50
ACTIVE = {"fetching", "running", "deleting"}


class QueueFull(Exception):
    """The durable waiting queue is full."""


class Cancelled(Exception):
    """Delete requested, or the report no longer exists."""


class Interrupted(Exception):
    """The runner is shutting down."""


def folder() -> Path:
    return store.DATA_DIR / "user" / "paper" / "backtests"


def path(run_id: str) -> Path:
    if not run_id.isalnum():
        raise KeyError("No such backtest")
    return folder() / f"{run_id}.json"


def execution_path(run_id: str) -> Path:
    return folder() / "locks" / f"{run_id}.execution"


def cancellation_path(run_id: str) -> Path:
    return folder() / "locks" / f"{run_id}.cancel"


def _write(run_id: str, **fields) -> None:
    p = path(run_id)
    with jsonfile.locked(p):
        d = jsonfile._load(p)
        if not d or d.get("delete_requested"):
            raise Cancelled()
        d.update(fields)
        jsonfile.replace(p, d)


def start(strategy: dict, name: str, symbol: str, start_day: str, end_day: str, missing: str, cash: float, settings: dict,
          baseline_runs: int = 5) -> dict:
    """Validate and persist a complete, immutable request. The runner owns execution, not the HTTP process."""
    rule = strategies.prepare(strategy)
    days, gaps = backtest.trading_days(symbol, start_day, end_day)
    fetch = bool(gaps) and missing == "fetch"
    if gaps and missing == "stop":
        raise ValueError(f"No cached bars for {len(gaps)} trading day(s): {', '.join(gaps[:8])}"
                         + (" …" if len(gaps) > 8 else "") + ". Fetch them from TWS, or skip them.")
    if fetch and (why := fetching.collector_ready()):
        raise ValueError(f"No cached bars for {len(gaps)} trading day(s), and {why}")
    if not days and not fetch:
        raise ValueError("No cached days in that range")
    if days:
        rules.check_no_repaint(symbol, days[0], rule["tf"], strategies.studies(rule))
    run_id = uuid.uuid4().hex
    head = {"id": run_id, "strategy_name": name, "strategy": rule, "symbol": symbol, "start": start_day, "end": end_day,
            "skipped": [] if fetch else gaps, "status": "queued", "done": 0,
            "total": len(days) * (1 + baseline_runs), "submitted": time.time(), "started": None,
            "inputs": {"days": days, "gaps": gaps, "missing": missing, "cash": cash, "settings": settings,
                       "baseline_runs": baseline_runs, "seed": 1}}
    if fetch:
        head["fetch"] = {"got": 0, "wanted": len(gaps)}
    span = f"{len(days) + len(gaps)} trading day(s) from {start_day} to {end_day}"
    head["log"] = [{"t": 0, "day": None, "level": "info", "text": f'"{name}" on {symbol}, {span}, ${cash:,.0f} to start'}]
    with jsonfile.locked(folder() / "locks" / "queue"):
        if len(queued()) >= MAX_QUEUED:
            raise QueueFull(f"The backtest queue is full ({MAX_QUEUED} waiting jobs); try again after a job starts")
        with jsonfile.editing(path(run_id)) as d:
            d.update(head)
    return head


def queued() -> list[str]:
    return [r["id"] for r in sorted(listing(), key=lambda r: (r.get("submitted") or 0, r["id"]))
            if r["status"] == "queued"]


def execute(run_id: str, stop, owner: str, pool=None) -> None:
    """One worker, one complete run. A deleted queued job is never recreated. pool (days.DayPool): its days are
    worked on at the same time; the run's "days" says which are going and which are done (with their P/L)."""
    with jsonfile.locked(execution_path(run_id)):
        try:
            head = read(run_id)
        except KeyError:
            return
        if head.get("delete_requested"):
            with jsonfile.locked(path(run_id)):
                path(run_id).unlink(missing_ok=True)
            return
        if head.get("status") != "queued":
            return
        lines = head.get("log", [])
        started = time.time()
        last_check = [0.0]

        def check():
            if stop.is_set():
                raise Interrupted()
            now = time.monotonic()
            if now - last_check[0] >= 0.1:
                last_check[0] = now
                if cancellation_path(run_id).exists() or not path(run_id).exists():
                    raise Cancelled()

        def log(day, text, level="info"):
            if len(lines) < MAX_LOG:
                lines.append({"t": round(time.time() - started, 1), "day": day, "level": level, "text": text})
            elif len(lines) == MAX_LOG:
                lines.append({"t": round(time.time() - started, 1), "day": None, "level": "warn",
                              "text": f"the log keeps the first {MAX_LOG} lines; the run carries on"})
        last_progress = [0.0]
        going = {"running": [], "worked": [], "done": {}, "workers": pool.limit() if pool else 1}
        steps = {}                                  # the latest done / total, in every write

        def flush(force=False):
            if force or time.monotonic() - last_progress[0] > 0.5:
                last_progress[0] = time.monotonic()
                going["workers"] = pool.limit() if pool else 1
                _write(run_id, days=going, log=lines, **steps)

        def progress(done, total):
            check()
            steps.update(done=done, total=total)
            flush(done == total)

        def on_day(day, what, pnl=None):
            if what == "running":
                going["running"].append(day)
            elif what == "worked":                  # its process is done: it waits for the days before it
                going["running"] = [d for d in going["running"] if d != day]
                going["worked"].append(day)
            else:
                going["running"] = [d for d in going["running"] if d != day]
                going["worked"] = [d for d in going["worked"] if d != day]
                going["done"][day] = pnl
            flush(what == "running")              # a day starting shows at once (once a day at most)
        terminal = {}
        try:
            check()
            args, rule, symbol = head["inputs"], head["strategy"], head["symbol"]
            days, gaps = args["days"], args["gaps"]
            fetch = bool(gaps) and args["missing"] == "fetch"
            _write(run_id, status="fetching" if fetch else "running", started=started, owner=owner)
            if fetch:
                log(None, f"fetching {len(gaps)} day(s) without cached bars from TWS: {_some(gaps)}")
                days = _fetch_first(run_id, rule, symbol, head["start"], head["end"], gaps,
                                    args["baseline_runs"], log, lines, check)
            elif gaps:
                log(None, f"skipped {len(gaps)} day(s) without cached bars: {_some(gaps)}", "warn")
            going["all"] = days
            report = backtest.run(rule, symbol, days, args["cash"], args["settings"], seed=args["seed"],
                                  baseline_runs=args["baseline_runs"], progress=progress, log=log, check=check,
                                  pool=pool, on_day=on_day)
            check()
            log(None, f"done: {report['stats']['trades']} trade(s), P/L {report['stats']['total']:+,.2f}")
            terminal = {"status": "done", "report": report}
        except Cancelled:
            pass
        except Interrupted:
            terminal = {"status": "interrupted", "error": "The paper worker stopped. Submit a new run to retry."}
        except Exception as e:  # any job failure is recorded without stopping the other workers
            log(None, f"failed: {type(e).__name__}: {e}", "error")
            terminal = {"status": "failed", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
        finally:
            # The computation has unwound. Deletion wins over completion, failure and shutdown.
            p = path(run_id)
            with jsonfile.locked(p):
                d = jsonfile._load(p)
                if d.get("delete_requested"):
                    p.unlink()
                elif d and terminal:
                    d.update(**terminal, finished=time.time(), log=lines)
                    jsonfile.replace(p, d)


def _some(days: list[str], n: int = 20) -> str:
    return ", ".join(days[:n]) + (" …" if len(days) > n else "")


def _fetch_first(run_id, rule, symbol, start_day, end_day, gaps, baseline_runs, log, lines, check) -> list[str]:
    """The fetch before a run: ask TWS for the missing days, wait, and say which never came. The days to run."""
    last = [0.0, -1]

    def progress(got, wanted):
        if got != last[1] or time.time() - last[0] > 5:
            if got > max(last[1], 0):
                log(None, f"fetched {got} of {wanted} day(s)")
            last[0], last[1] = time.time(), got
            _write(run_id, fetch={"got": got, "wanted": wanted}, log=lines)
    unavailable = fetching.fetch(symbol, gaps, progress=progress, check=check)
    check()
    days, _ = backtest.trading_days(symbol, start_day, end_day)
    if unavailable:
        log(None, f"skipped {len(unavailable)} day(s) TWS had no bars for: {_some(unavailable)}", "warn")
    if not days:
        raise ValueError("TWS had no bars for any day in that range")
    check()
    rules.check_no_repaint(symbol, days[0], rule["tf"], strategies.studies(rule))
    check()
    _write(run_id, status="running", skipped=unavailable, total=len(days) * (1 + baseline_runs), log=lines)
    return days


def read(run_id: str) -> dict:
    d = jsonfile.read(path(run_id))
    if not d:
        raise KeyError("No such backtest")
    return {**d, "strategy_name": d.get("strategy_name") or d.get("rule_name")}


def listing() -> list[dict]:
    """Every run, newest first, without the trades. Files may disappear during this scan."""
    out = []
    for p in folder().glob("*.json"):
        d = jsonfile.read(p)
        if d:
            rep = d.get("report") or {}
            out.append({k: d.get(k) for k in ("id", "symbol", "start", "end", "status", "done", "total", "fetch",
                                             "submitted", "started", "finished", "error")}
                       | {"strategy_name": d.get("strategy_name") or d.get("rule_name"),
                          "stats": rep.get("stats"), "baseline": rep.get("baseline"),
                          "days": {"running": (d.get("days") or {}).get("running", [])} if d.get("status") == "running" else None})
    return sorted(out, key=lambda r: r.get("submitted") or r.get("started") or 0, reverse=True)


def delete(run_id: str) -> bool:
    """True: stopped and deleted. False: cancellation persisted; worker will remove after it stops (HTTP 202)."""
    p = path(run_id)
    with jsonfile.locked(p):
        d = jsonfile._load(p)
        if not d:
            raise KeyError("No such backtest")
        if d.get("status") not in ACTIVE | {"queued"}:
            p.unlink()                 # finalization already committed; no computation or writes remain
            return True
        try:
            with jsonfile.locked(execution_path(run_id), blocking=False):
                p.unlink()             # no worker owns it: queued, terminal, or abandoned after a crash
                return True
        except BlockingIOError:
            d.update(status="deleting", delete_requested=True)
            jsonfile.replace(p, d)
            cancellation_path(run_id).touch()     # cheap polling: never reread a growing report on every bar
            return False


def recover() -> None:
    """Called only after acquiring the singleton runner lock; no previous worker can still be executing."""
    for row in listing():
        p = path(row["id"])
        with jsonfile.locked(p):
            d = jsonfile._load(p)
            if d.get("delete_requested"):
                p.unlink()
            elif d.get("status") in ACTIVE:
                d.update(status="interrupted", finished=time.time(),
                         error="The paper worker was interrupted. Submit a new run to retry.")
                jsonfile.replace(p, d)
