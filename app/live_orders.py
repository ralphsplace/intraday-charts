"""Orders to the IBKR paper account (#84): the server's side. The trade panel's Buy / Sell / cancel / flatten become
requests the TWS collector's trader (tools/trader.py) carries out on a TWS logged into a paper account; what TWS
says (the account, positions, working orders, today's fills) comes back in a status file. No TWS here.

Guarded, as it's the only part of the app that places orders:
  - off unless LIVE_ORDERS=paper in .env (both here and in the collector);
  - the trader connects to the paper TWS (TRADE_PORT, 7497 by default) on a connection of its own, and sends an
    order only while every account TWS reports is a paper one (IDs start DU), checked before each order;
  - at most LIVE_MAX_SHARES shares an order (1,000 by default); stocks and ETFs only.
Everything else in the app, the collector's market data connection included, stays read-only.

Files (data/control/trade/):
    requests/<id>.json  {"id", "action": order | bracket | cancel | flatten, "symbol", "order", "stop", "target",
                         "order_id" (cancel: TWS's id of the order), "created"}
    results/<id>.json   {"id", "ok": bool, "message", "done"}
    status.json         {"connected", "port", "account" (masked), "paper", "refused", "positions": [...],
                         "orders": [...], "fills": [...], "heartbeat"}
"""
from __future__ import annotations

import contextlib
import os
import time
import uuid
from pathlib import Path

from . import control, positions, store

SWITCH = "LIVE_ORDERS"
PAPER_PREFIX = "DU"                   # IBKR paper account IDs
STALE_SECONDS = 30                    # the trader writes its status every few seconds
WAIT_SECONDS = 8.0                    # how long a request waits for the trader's answer
ACTIONS = ("order", "bracket", "cancel", "flatten")
TYPES = ("market", "limit", "stop", "trail")


def turned_on() -> bool:
    return os.environ.get(SWITCH, "").strip().lower() == "paper"


def max_shares() -> int:
    try:
        return max(1, int(os.environ.get("LIVE_MAX_SHARES", "1000")))
    except ValueError:
        return 1000


def is_paper(account: str) -> bool:
    return str(account or "").upper().startswith(PAPER_PREFIX)


def folder() -> Path:
    return store.DATA_DIR / "control" / "trade"


# ---------------------------------------------------------------- checking an action (here, and again in the trader)
def _price(x, what: str) -> float:
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not 0 < x < 1_000_000:
        raise ValueError(f"{what} is a price above $0")
    return round(float(x), 2)


def _order(o: dict) -> dict:
    if not isinstance(o, dict):
        raise ValueError("an order is an object")
    if o.get("side") not in ("buy", "sell"):
        raise ValueError("an order's side is buy or sell")
    q = o.get("qty")
    if not isinstance(q, int) or isinstance(q, bool) or not 1 <= q <= max_shares():
        raise ValueError(f"an order is 1 to {max_shares():,} shares (LIVE_MAX_SHARES)")
    t = o.get("type")
    if t not in TYPES:
        raise ValueError("an order is market, limit, stop or trail")
    out = {"side": o["side"], "qty": q, "type": t}
    if t in ("limit", "stop"):
        out["price"] = _price(o.get("price"), f"a {t} order's price")
    if t == "trail":
        tr = o.get("trail") or {}
        if "amount" in tr:
            out["trail"] = {"amount": _price(tr["amount"], "a trailing distance")}
        elif "pct" in tr and isinstance(tr["pct"], (int, float)) and 0 < tr["pct"] < 50:
            out["trail"] = {"pct": float(tr["pct"])}
        else:
            raise ValueError("a trailing stop trails by an amount or a percentage")
    return out


def check(action: dict) -> dict:
    """An action from the trade panel, checked; ValueError says what's wrong. ATR trailing distances are worked
    out before this (resolve_atr)."""
    k = action.get("action")
    if k not in ACTIONS:
        raise ValueError("action is order, bracket, cancel or flatten")
    sym = control.clean_symbol(action.get("symbol") or "")
    if not sym or sym.endswith("-DEMO") or control.is_index(sym):
        raise ValueError("orders are for stocks and ETFs")
    out = {"action": k, "symbol": sym}
    if k in ("order", "bracket"):
        out["order"] = _order(action.get("order"))
    if k == "bracket":
        stop, target = action.get("stop") or {}, action.get("target") or {}
        out["stop"] = {"trail": {"amount": _price((stop.get("trail") or {}).get("amount"), "a trailing distance")}} \
            if stop.get("trail") else {"price": _price(stop.get("price"), "the stop")}
        out["target"] = {"price": _price(target.get("price"), "the target")}
    if k == "cancel":
        if not isinstance(action.get("order_id"), int) or isinstance(action.get("order_id"), bool):
            raise ValueError("cancel needs the order's id")
        out["order_id"] = action["order_id"]
    return out


def resolve_atr(action: dict, day: str, minute: int) -> dict:
    """An order or stop trailing by N x ATR ({"atr", "length", "tf"}) with its distance in dollars, from today's
    cached bars before `minute` (as a backtest works it out)."""
    from .backtesting import orders
    out = dict(action)
    for key in ("order", "stop"):
        part = out.get(key)
        tr = (part or {}).get("trail")
        if tr and "atr" in tr:
            out[key] = {**part, "trail": {"amount": orders.atr_distance(action["symbol"], day, tr, minute)}}
    return out


# ---------------------------------------------------------------- requests and status
def submit(action: dict) -> dict:
    req = {**action, "id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}", "created": time.time()}
    control.write_json(folder() / "requests" / f"{req['id']}.json", req)
    return req


def take_requests() -> list[dict]:
    """The trader's side: every waiting request, oldest first, removed."""
    d = folder() / "requests"
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        r = control.read_json(p)
        with contextlib.suppress(OSError):
            p.unlink()
        if isinstance(r, dict):
            out.append(r)
    return out


def answer(req_id: str, ok: bool, message: str) -> None:
    control.write_json(folder() / "results" / f"{req_id}.json", {"id": req_id, "ok": ok, "message": message, "done": time.time()})


def result(req_id: str) -> dict | None:
    p = folder() / "results" / f"{req_id}.json"
    r = control.read_json(p)
    if r is not None:
        with contextlib.suppress(OSError):
            p.unlink()
    return r


def wait(req_id: str, seconds: float = WAIT_SECONDS, sleep=time.sleep, clock=time.monotonic) -> dict | None:
    end = clock() + seconds
    while clock() < end:
        r = result(req_id)
        if r is not None:
            return r
        sleep(0.1)
    return None


def write_status(status: dict) -> None:
    control.write_json(folder() / "status.json", {**status, "heartbeat": time.time()})


def read_status() -> dict:
    s = control.read_json(folder() / "status.json", {}) or {}
    age = time.time() - s["heartbeat"] if "heartbeat" in s else None
    s["running"] = age is not None and age < STALE_SECONDS
    return s


def why_not() -> str | None:
    """Why orders can't be sent now, in words; None when they can."""
    if not turned_on():
        return "Orders are off. Set LIVE_ORDERS=paper in .env (and restart) to place orders on your IBKR paper account."
    s = read_status()
    if not s.get("running"):
        return "The TWS collector's trader isn't running (start the collector with LIVE_ORDERS=paper)."
    if not s.get("connected"):
        return s.get("message") or f"The trader isn't connected to the paper TWS (port {s.get('port', 7497)})."
    if s.get("refused"):
        return s["refused"]
    if not s.get("paper"):
        return "TWS isn't logged into a paper account: no orders are sent."
    return None


def view(symbol: str) -> dict:
    """The trade panel's view of one symbol: whether orders can be sent, the account, its position, working orders
    and today's fills in that symbol."""
    s = read_status()
    sym = symbol.upper()
    return {"on": turned_on(), "ready": why_not() is None, "why_not": why_not(), "account": s.get("account"),
            "paper": bool(s.get("paper")), "max_shares": max_shares(), "symbol": sym,
            "position": next((p for p in s.get("positions") or [] if p.get("symbol") == sym), {"symbol": sym, "qty": 0, "avg": None}),
            "orders": [o for o in s.get("orders") or [] if o.get("symbol") == sym],
            "fills": [f for f in s.get("fills") or [] if f.get("symbol") == sym],
            "updated": s.get("heartbeat")}


mask = positions.mask
