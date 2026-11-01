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
from . import backtest, rules


def folder() -> Path:
    return store.DATA_DIR / "user" / "paper" / "backtests"


def path(run_id: str) -> Path:
    return folder() / f"{run_id}.json"


def _write(run_id: str, **fields) -> None:
    with jsonfile.editing(path(run_id)) as d:
        d.update(fields)


def start(rule: dict, name: str, symbol: str, start_day: str, end_day: str, missing: str, cash: float, settings: dict,
          baseline_runs: int = 5) -> dict:
    """Check everything now (so mistakes come back at once), then run on a thread. missing: "stop" or "skip"."""
    rule = rules.check(rule)
    days, gaps = backtest.trading_days(symbol, start_day, end_day)
    if gaps and missing != "skip":
        raise ValueError(f"No cached bars for {len(gaps)} trading day(s): {', '.join(gaps[:8])}"
                         + (" …" if len(gaps) > 8 else "") + ". Fetch them first, or skip them.")
    if not days:
        raise ValueError("No cached days in that range")
    rules.check_no_repaint(symbol, days[0], rule["tf"], rule)
    run_id = uuid.uuid4().hex[:10]
    head = {"id": run_id, "rule_name": name, "rule": rule, "symbol": symbol, "start": start_day, "end": end_day,
            "skipped": gaps, "status": "running", "done": 0, "total": len(days) * (1 + baseline_runs),
            "started": time.time()}
    folder().mkdir(parents=True, exist_ok=True)
    _write(run_id, **head)

    def work():
        last = [0.0]

        def progress(done, total):
            if time.time() - last[0] > 0.5 or done == total:
                last[0] = time.time()
                _write(run_id, done=done, total=total)
        try:
            report = backtest.run(rule, symbol, days, cash, settings, baseline_runs=baseline_runs, progress=progress)
            _write(run_id, status="done", report=report, finished=time.time())
        except Exception as e:  # noqa: BLE001  (any failure: the run says so, the server carries on)
            _write(run_id, status="failed", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
    threading.Thread(target=work, name=f"backtest-{run_id}", daemon=True).start()
    return head


def read(run_id: str) -> dict:
    if not run_id.isalnum():
        raise KeyError("No such backtest")
    p = path(run_id)
    if not p.exists():
        raise KeyError("No such backtest")
    return jsonfile.read(p)


def listing() -> list[dict]:
    """Every run, newest first, without the trades."""
    out = []
    for p in sorted(folder().glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True) if folder().exists() else []:
        d = jsonfile.read(p)
        if d:
            out.append({k: d.get(k) for k in ("id", "rule_name", "symbol", "start", "end", "status", "done", "total", "started", "error")}
                       | {"stats": (d.get("report") or {}).get("stats"), "baseline": (d.get("report") or {}).get("baseline")})
    return out


def delete(run_id: str) -> None:
    read(run_id)
    path(run_id).unlink()
