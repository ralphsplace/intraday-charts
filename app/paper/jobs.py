"""Backtests as background runs: started by a request, run on a thread of the server process, followed and read
back by id. Progress and results are files (data/user/paper/backtests/<id>.json, written through jsonfile), so
any of the server's worker processes can answer, and a run survives the page being closed."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from pathlib import Path

from .. import jsonfile, store
from . import backtest, fetching, rules, strategies


def folder() -> Path:
    return store.DATA_DIR / "user" / "paper" / "backtests"


def path(run_id: str) -> Path:
    return folder() / f"{run_id}.json"


def _write(run_id: str, **fields) -> None:
    with jsonfile.editing(path(run_id)) as d:
        d.update(fields)


MAX_LOG = 20_000


def start(strategy: dict, name: str, symbol: str, start_day: str, end_day: str, missing: str, cash: float, settings: dict,
          baseline_runs: int = 5) -> dict:
    """Check everything now (so mistakes come back at once), then run on a thread. missing: what to do about trading
    days without cached bars: "fetch" them from TWS first (fetching.py), "skip" them, or "stop" (refuse the run).
    The strategy's rules are read now: the run keeps what they said (its "strategy", expanded)."""
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
    run_id = uuid.uuid4().hex[:10]
    head = {"id": run_id, "strategy_name": name, "strategy": rule, "symbol": symbol, "start": start_day, "end": end_day,
            "skipped": [] if fetch else gaps, "status": "fetching" if fetch else "running", "done": 0,
            "total": len(days) * (1 + baseline_runs), "started": time.time()}
    if fetch:
        head["fetch"] = {"got": 0, "wanted": len(gaps)}
    lines: list[dict] = []

    def log(day, text, level="info"):
        """A line of the run's log: {"t": seconds since it started, "day", "level": info | warn | day | error, "text"}."""
        if len(lines) < MAX_LOG:
            lines.append({"t": round(time.time() - head["started"], 1), "day": day, "level": level, "text": text})
        elif len(lines) == MAX_LOG:
            lines.append({"t": round(time.time() - head["started"], 1), "day": None, "level": "warn",
                          "text": f"the log keeps the first {MAX_LOG} lines; the run carries on"})
    span = f"{len(days) + len(gaps)} trading day(s) from {start_day} to {end_day}"
    log(None, f'"{name}" on {symbol}, {span}, ${cash:,.0f} to start')
    if fetch:
        log(None, f"fetching {len(gaps)} day(s) without cached bars from TWS: {_some(gaps)}")
    elif gaps:
        log(None, f"skipped {len(gaps)} day(s) without cached bars: {_some(gaps)}", "warn")
    folder().mkdir(parents=True, exist_ok=True)
    _write(run_id, **head, log=lines)

    def work():
        last = [0.0]

        def progress(done, total):
            if time.time() - last[0] > 0.5 or done == total:
                last[0] = time.time()
                _write(run_id, done=done, total=total, log=lines)
        try:
            run_days = days
            if fetch:
                run_days = _fetch_first(run_id, rule, symbol, start_day, end_day, gaps, baseline_runs, log, lines)
            report = backtest.run(rule, symbol, run_days, cash, settings, baseline_runs=baseline_runs, progress=progress, log=log)
            log(None, f"done: {report['stats']['trades']} trade(s), P/L {report['stats']['total']:+,.2f}")
            _write(run_id, status="done", report=report, finished=time.time(), log=lines)
        except Exception as e:  # noqa: BLE001  (any failure: the run says so, the server carries on)
            log(None, f"failed: {type(e).__name__}: {e}", "error")
            _write(run_id, status="failed", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:], log=lines)
    threading.Thread(target=work, name=f"backtest-{run_id}", daemon=True).start()
    return head


def _some(days: list[str], n: int = 20) -> str:
    return ", ".join(days[:n]) + (" …" if len(days) > n else "")


def _fetch_first(run_id, rule, symbol, start_day, end_day, gaps, baseline_runs, log, lines) -> list[str]:
    """The fetch before a run: ask TWS for the missing days, wait, and say which never came. The days to run."""
    last = [0.0, -1]

    def progress(got, wanted):
        if got != last[1] or time.time() - last[0] > 5:
            if got > max(last[1], 0):
                log(None, f"fetched {got} of {wanted} day(s)")
            last[0], last[1] = time.time(), got
            _write(run_id, fetch={"got": got, "wanted": wanted}, log=lines)
    unavailable = fetching.fetch(symbol, gaps, progress=progress)
    days, _ = backtest.trading_days(symbol, start_day, end_day)
    if unavailable:
        log(None, f"skipped {len(unavailable)} day(s) TWS had no bars for: {_some(unavailable)}", "warn")
    if not days:
        raise ValueError("TWS had no bars for any day in that range")
    rules.check_no_repaint(symbol, days[0], rule["tf"], strategies.studies(rule))
    _write(run_id, status="running", skipped=unavailable, total=len(days) * (1 + baseline_runs), log=lines)
    return days


def read(run_id: str) -> dict:
    if not run_id.isalnum():
        raise KeyError("No such backtest")
    p = path(run_id)
    if not p.exists():
        raise KeyError("No such backtest")
    d = jsonfile.read(p)
    return {**d, "strategy_name": d.get("strategy_name") or d.get("rule_name")}        # runs from before #67 ran a rule


def listing() -> list[dict]:
    """Every run, newest first, without the trades."""
    out = []
    for p in sorted(folder().glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True) if folder().exists() else []:
        d = jsonfile.read(p)
        if d:
            rep = d.get("report") or {}
            out.append({k: d.get(k) for k in ("id", "symbol", "start", "end", "status", "done", "total", "fetch", "started", "error")}
                       | {"strategy_name": d.get("strategy_name") or d.get("rule_name"),      # runs from before #67 ran a rule
                          "stats": rep.get("stats"), "baseline": rep.get("baseline")})
    return out


def delete(run_id: str) -> None:
    read(run_id)
    path(run_id).unlink()
