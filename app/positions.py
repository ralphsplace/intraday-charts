"""Account holdings for a watch list's Holdings list: the stock and ETF positions the TWS collector read
(read-only; tools/positions.py), and each holding's market value and profit/loss at the price on screen.

Off unless HOLDINGS=on in .env: by default no TWS connection reads the account at all. Even when on, only
positions are read (never orders or executions), and account numbers are kept masked (…1234).

One job: the positions file in (data/account/positions.json), rows out. No TWS here.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import quotes, store
from .control import clean_symbol

SWITCH = "HOLDINGS"
STALE_SECONDS = 180          # the collector reads positions every minute in Live; older than this: say so


def turned_on() -> bool:
    return os.environ.get(SWITCH, "").strip().lower() in ("on", "1", "yes", "true")


def mask(account: str) -> str:
    a = str(account or "")
    return "…" + a[-4:] if len(a) > 4 else "…"


def path() -> Path:
    return store.DATA_DIR / "account" / "positions.json"


def read() -> dict | None:
    try:
        d = json.loads(path().read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def write(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(p)


def holdings(data: dict) -> tuple[dict, int]:
    """Stock and ETF positions by symbol, summed over accounts (average cost weighted by shares), and how many
    other positions there are (options, futures, cash, symbols the charts can't show)."""
    out: dict = {}
    others = 0
    for p in data.get("positions") or []:
        sym = clean_symbol(p.get("symbol") or "") if p.get("sec_type") == "STK" else None
        qty = float(p.get("qty") or 0)
        if not sym or not qty:
            others += bool(qty)
            continue
        h = out.setdefault(sym, {"qty": 0.0, "cost": 0.0, "accounts": []})
        h["qty"] += qty
        h["cost"] += qty * float(p.get("avg_cost") or 0)
        if p.get("account") not in h["accounts"]:
            h["accounts"].append(p.get("account"))
    for h in out.values():
        h["avg_cost"] = h["cost"] / h["qty"] if h["qty"] else None
    return {s: h for s, h in out.items() if h["qty"]}, others


def _r(x):
    return round(x, 2) if x is not None else None


def view(day: str, cursor: int | None = None) -> dict:
    """The Holdings list: one row per holding (the watch list's quote columns plus quantity, average cost, cost
    basis, market value, unrealized and day P/L at the price on screen), and the totals."""
    if not turned_on():
        return {"status": "off", "rows": []}
    data = read()
    if not data:
        return {"status": "missing", "rows": []}
    if data.get("error"):
        return {"status": "error", "message": data["error"], "rows": [], "fetched": data.get("fetched")}
    held, others = holdings(data)
    rows, tot = [], {"market_value": 0.0, "cost": 0.0, "unrealized": 0.0, "day_pnl": 0.0}
    for sym in sorted(held, key=lambda s: -abs(held[s]["cost"])):          # biggest positions first
        h = held[sym]
        q = quotes.row(sym, day, cursor)
        r = {**q, "qty": h["qty"], "avg_cost": _r(h["avg_cost"]), "cost": _r(h["cost"]), "accounts": h["accounts"]}
        if q.get("status") == "ok":
            mv = h["qty"] * q["last"]
            unrl = mv - h["cost"]
            r.update(market_value=_r(mv), unrealized=_r(unrl),
                     unrealized_pct=_r(unrl / abs(h["cost"]) * 100) if h["cost"] else None,
                     day_pnl=_r(h["qty"] * q["change"]) if q.get("change") is not None else None)
            for k in tot:
                tot[k] += r.get(k) or 0.0
        rows.append(r)
    age = time.time() - data["fetched"] if data.get("fetched") else None
    return {"status": "ok", "rows": rows, "totals": {k: _r(v) for k, v in tot.items()}, "others": others,
            "accounts": data.get("accounts", []), "fetched": data.get("fetched"),
            "age": round(age) if age is not None else None, "stale": age is None or age > STALE_SECONDS}
