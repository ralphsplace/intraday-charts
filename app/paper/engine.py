"""The paper engine: the market model for paper trading. Given an account's working orders and one 1-minute bar,
it fills, cancels and updates them, and keeps the position, cash and P/L. It never sees a later bar, and it never
talks to TWS or IBKR: everything here is simulated from the cached bars (#39, #40).

Replay practice drives it one bar at a time as the cursor moves; rule backtests drive it over every bar of a date
range. Both get the same fills because both call step().

State (a plain dict, saved as JSON):
    cash, position {qty, avg}, realized, orders [...], fills [...], next_id, settings {commission, slippage, shorting}
An order:
    id, side ("buy" | "sell"), qty (shares), type ("market" | "limit" | "stop" | "trail" | "level"),
    price      limit or stop price (a "level" order's price is resolved every bar; a "trail" order's moves)
    trail      {"amount": dollars} or {"pct": percent} for "trail"
    level      {"spec": a study_values spec, "as": "limit" | "stop", "offset": dollars} for "level"
    parent     the entry's id, for a bracket's exits: they work only once the entry has filled
    oco        a group id: when one order of the group fills, the others are cancelled
    exit       True for an order that only reduces the position (a bracket's exits; sized to the position)
    active, placed (minute of day), note

Buying power: no margin is modelled, so a position, long or short, may be worth at most the account's equity.

Fill rules (no look-ahead; prior art tools/backtest_signals.py):
  - market: the open of the next bar after it was placed, plus slippage against the trader;
  - limit: when the bar trades through the limit: at the limit, or at the open when the bar opens past it;
  - stop: when the bar trades through the stop: at the stop, or at the open on a gap; plus slippage;
  - within one bar, stops are checked before limits (a bar touching both a stop and a target exits at the stop);
  - a trailing stop's level follows the bar's best price only after that bar's fill check;
  - a study-level order's price is the study's value at the previous bar's close (resolved by the driver);
  - a bracket's exits become active on the bar after the entry fills;
  - at the last regular-hours bar of the day, working orders are cancelled and the position is closed at its close.
Commission: IBKR Fixed by default: $0.005 a share, at least $1.00, at most 1% of the trade's value.
"""
from __future__ import annotations

import copy
import math

DEFAULT_SETTINGS = {"commission": {"per_share": 0.005, "minimum": 1.0, "max_pct": 1.0},
                    "slippage": 0.01,          # dollars a share, against the trader, on market and stop fills
                    "shorting": True}
TYPES = ("market", "limit", "stop", "trail", "level")
SIDES = ("buy", "sell")


class PaperError(ValueError):
    """An order the account can't take, with the reason in words."""


def new_state(cash: float, settings: dict | None = None) -> dict:
    s = copy.deepcopy(DEFAULT_SETTINGS)
    for k, v in (settings or {}).items():
        s[k] = {**s[k], **v} if isinstance(s.get(k), dict) and isinstance(v, dict) else v
    return {"cash": float(cash), "start_cash": float(cash), "position": {"qty": 0, "avg": 0.0}, "realized": 0.0,
            "commissions": 0.0, "orders": [], "fills": [], "next_id": 1, "settings": s, "closed": False}


def commission(qty: int, price: float, settings: dict) -> float:
    c = settings["commission"]
    fee = max(abs(qty) * c["per_share"], c["minimum"])
    return round(min(fee, abs(qty) * price * c["max_pct"] / 100), 2)


# ---------------------------------------------------------------- placing, changing and cancelling orders
def _check(state: dict, o: dict) -> None:
    if o.get("side") not in SIDES:
        raise PaperError("side must be buy or sell")
    if o.get("type") not in TYPES:
        raise PaperError("type must be one of " + ", ".join(TYPES))
    if not isinstance(o.get("qty"), int) or o["qty"] <= 0:
        raise PaperError("quantity must be a whole number of shares above 0")
    if o["type"] in ("limit", "stop") and not (isinstance(o.get("price"), (int, float)) and o["price"] > 0):
        raise PaperError(f"a {o['type']} order needs a price above 0")
    if o["type"] == "trail":
        t = o.get("trail") or {}
        if not ((t.get("amount") or 0) > 0 or (t.get("pct") or 0) > 0):
            raise PaperError("a trailing stop needs a distance in dollars or percent")
    if o["type"] == "level":
        lv = o.get("level") or {}
        if not isinstance(lv.get("spec"), dict) or lv.get("as") not in ("limit", "stop"):
            raise PaperError("an order at a study level needs the study and whether it works as a limit or a stop")


def place(state: dict, order: dict, minute: int, price: float | None = None) -> dict:
    """Add an order (a copy, with an id) after checking it; `price` is the last price known, for the checks and for
    a trailing stop's first level. Returns the order as kept."""
    if state["closed"]:
        raise PaperError("The session has ended: positions were closed at the close")
    o = {"active": True, "parent": None, "oco": None, "exit": False, "note": "", **copy.deepcopy(order)}
    _check(state, o)
    pos = state["position"]["qty"]
    after = pos + (o["qty"] if o["side"] == "buy" else -o["qty"])
    if not o["exit"] and after < 0 and not state["settings"]["shorting"]:
        raise PaperError("Shorting is off for this account: you can sell only shares you hold")
    if not o["exit"] and abs(after) > abs(pos) and price:          # no margin: long or short, at most the equity
        equity = state["cash"] + pos * price
        if abs(after) * price > equity + 1e-9:
            raise PaperError(f"Not enough buying power: {abs(after)} shares at about {price:.2f} are "
                             f"${abs(after) * price:,.0f}; the account has ${equity:,.0f} (no margin)")
    if o["type"] == "trail" and o.get("price") is None and price and o["active"]:
        o["price"] = _trail_level(o, price, price)
    o["id"] = state["next_id"]
    o["placed"] = minute
    state["next_id"] += 1
    state["orders"].append(o)
    return o


def bracket(state: dict, entry: dict, minute: int, price: float | None, stop: dict | None = None,
            target: dict | None = None) -> list[dict]:
    """An entry with an attached stop and/or target (one cancels the other), working once the entry fills. stop is
    {"price": p} for a fixed stop or {"trail": {...}} for a trailing one; target is {"price": p}."""
    if not stop and not target:
        raise PaperError("A bracket needs a stop, a target or both")
    first = place(state, entry, minute, price)
    exit_side = "sell" if entry["side"] == "buy" else "buy"
    group = f"b{first['id']}"
    out = [first]
    try:
        if stop:
            kind = "trail" if stop.get("trail") else "stop"
            out.append(place(state, {"side": exit_side, "qty": entry["qty"], "type": kind, "price": stop.get("price"),
                                     "trail": stop.get("trail"), "parent": first["id"], "oco": group, "exit": True,
                                     "active": False}, minute))
        if target:
            out.append(place(state, {"side": exit_side, "qty": entry["qty"], "type": "limit", "price": target.get("price"),
                                     "parent": first["id"], "oco": group, "exit": True, "active": False}, minute))
    except PaperError:
        state["orders"] = [o for o in state["orders"] if o["id"] not in {x["id"] for x in out}]
        raise
    return out


def cancel(state: dict, order_id: int, why: str = "cancelled") -> list[dict]:
    """Cancel an order and the exits waiting on it; the cancellations as events."""
    gone = [o for o in state["orders"] if o["id"] == order_id or o.get("parent") == order_id]
    if not any(o["id"] == order_id for o in gone):
        raise PaperError(f"No working order {order_id}")
    state["orders"] = [o for o in state["orders"] if o not in gone]
    return [{"event": "cancel", "order": o["id"], "why": why} for o in gone]


def modify(state: dict, order_id: int, changes: dict) -> dict:
    """Change a working order's quantity, price, trail distance or level; checked like a new order."""
    o = next((x for x in state["orders"] if x["id"] == order_id), None)
    if o is None:
        raise PaperError(f"No working order {order_id}")
    new = {**o, **{k: v for k, v in changes.items() if k in ("qty", "price", "trail", "level")}}
    _check(state, new)
    o.update(new)
    return o


def flatten(state: dict, minute: int) -> list[dict]:
    """Cancel every working order and close the position with a market order (it fills on the next bar)."""
    events = [{"event": "cancel", "order": o["id"], "why": "flatten"} for o in state["orders"]]
    state["orders"] = []
    q = state["position"]["qty"]
    if q:
        place(state, {"side": "sell" if q > 0 else "buy", "qty": abs(q), "type": "market", "exit": True, "note": "flatten"}, minute)
    return events


# ---------------------------------------------------------------- one bar
def _trail_level(o: dict, best: float, ref: float) -> float:
    t = o.get("trail") or {}
    dist = t["amount"] if t.get("amount") else ref * t["pct"] / 100
    return round(best - dist, 4) if o["side"] == "sell" else round(best + dist, 4)


def _how(o: dict) -> str:
    """How an order filled, in words, for the trade list: "target", "stop", "trailing stop", "limit", …"""
    if o["type"] == "trail":
        return "trailing stop"
    if o["exit"] and o["type"] in ("limit", "stop"):
        return "target" if o["type"] == "limit" else "stop"
    return {"level": "study line"}.get(o["type"], o["type"])


def _trigger(o: dict, bar: dict, price: float | None) -> tuple[str, float] | None:
    """Whether the order fills on this bar, and at what price before slippage; kind is "stop" or "limit"."""
    kind = o["type"]
    if kind == "market":
        return ("market", bar["open"])
    if kind == "level":
        kind = o["level"]["as"]
    elif kind == "trail":
        kind = "stop"
    if price is None:
        return None
    if kind == "limit":
        if o["side"] == "buy" and bar["low"] <= price:
            return ("limit", min(bar["open"], price))
        if o["side"] == "sell" and bar["high"] >= price:
            return ("limit", max(bar["open"], price))
    else:
        if o["side"] == "buy" and bar["high"] >= price:
            return ("stop", max(bar["open"], price))
        if o["side"] == "sell" and bar["low"] <= price:
            return ("stop", min(bar["open"], price))
    return None


def _apply_fill(state: dict, side: str, qty: int, price: float, minute: int, order_id, note: str) -> dict:
    pos = state["position"]
    signed = qty if side == "buy" else -qty
    fee = commission(qty, price, state["settings"])
    realized = 0.0
    if pos["qty"] and (pos["qty"] > 0) != (signed > 0):                    # reduces (or reverses) the position
        closing = min(abs(signed), abs(pos["qty"]))
        realized = closing * (price - pos["avg"]) * (1 if pos["qty"] > 0 else -1)
        left = pos["qty"] + signed
        if left == 0:
            pos.update(qty=0, avg=0.0)
        elif (left > 0) == (pos["qty"] > 0):
            pos["qty"] = left
        else:
            pos.update(qty=left, avg=price)                                    # reversed: the rest at this price
    else:
        total = pos["qty"] + signed
        pos["avg"] = (pos["avg"] * abs(pos["qty"]) + price * qty) / abs(total)
        pos["qty"] = total
    state["cash"] += -signed * price - fee
    state["realized"] += realized
    state["commissions"] += fee
    f = {"event": "fill", "order": order_id, "side": side, "qty": qty, "price": round(price, 4), "minute": minute,
         "commission": fee, "realized": round(realized, 2), "position": pos["qty"], "note": note}
    state["fills"].append(f)
    return f


def step(state: dict, bar: dict, level_of=None) -> list[dict]:
    """Run one 1-minute bar: {"minute", "open", "high", "low", "close", "last_rth"}. level_of(spec) gives a study
    level's price at the previous bar's close (None when unknown). Returns what happened, in order."""
    if state["closed"]:
        return []
    events: list[dict] = []
    m = bar["minute"]
    slip = state["settings"]["slippage"]
    working = [o for o in state["orders"] if o["active"] and o["placed"] <= m]      # placed before this bar opened
    for o in working:                                          # study-level orders: the price at the last close
        if o["type"] == "level":
            v = level_of(o["level"]["spec"]) if level_of else None
            o["price"] = None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v + o["level"].get("offset", 0), 4)
    rank = {"market": 0, "stop": 1, "limit": 2}
    hits = []
    for o in working:
        t = _trigger(o, bar, o.get("price"))
        if t:
            hits.append((rank[t[0]], o["id"], o, t))
    filled_groups = set()
    for _, _, o, (kind, px) in sorted(hits, key=lambda h: (h[0], h[1])):
        if o not in state["orders"] or (o["oco"] and o["oco"] in filled_groups):
            continue
        qty = o["qty"]
        if o["exit"]:
            pos = state["position"]["qty"]
            reducing = (pos > 0 and o["side"] == "sell") or (pos < 0 and o["side"] == "buy")
            if not reducing:
                state["orders"].remove(o)
                events.append({"event": "cancel", "order": o["id"], "why": "no position to close"})
                continue
            qty = min(qty, abs(pos))
        if kind in ("market", "stop"):
            px = px + slip if o["side"] == "buy" else px - slip
        state["orders"].remove(o)
        events.append(_apply_fill(state, o["side"], qty, px, m, o["id"], o.get("note") or _how(o)))
        if o["oco"]:
            filled_groups.add(o["oco"])
            for x in [x for x in state["orders"] if x["oco"] == o["oco"]]:
                state["orders"].remove(x)
                events.append({"event": "cancel", "order": x["id"], "why": "the other side of the bracket filled"})
        for child in (x for x in state["orders"] if x["parent"] == o["id"]):
            child["active"] = True
            child["placed"] = m                                # works from the next bar
            child["qty"] = qty
            if child["type"] == "trail" and child.get("price") is None:
                child["price"] = _trail_level(child, px, px)
    was_working = {o["id"] for o in working}
    for o in state["orders"]:              # trailing stops follow this bar's best price (not one activated on it)
        if o["type"] == "trail" and o["id"] in was_working and o.get("price") is not None:
            best = bar["high"] if o["side"] == "sell" else bar["low"]
            new = _trail_level(o, best, bar["close"])
            o["price"] = max(o["price"], new) if o["side"] == "sell" else min(o["price"], new)
    if bar.get("last_rth"):
        events += session_end(state, bar)
    return events


def session_end(state: dict, bar: dict) -> list[dict]:
    """The day is over: cancel working orders, close the position at the bar's close (plus slippage)."""
    events = [{"event": "cancel", "order": o["id"], "why": "session end"} for o in state["orders"]]
    state["orders"] = []
    q = state["position"]["qty"]
    if q:
        side = "sell" if q > 0 else "buy"
        px = bar["close"] - state["settings"]["slippage"] if side == "sell" else bar["close"] + state["settings"]["slippage"]
        events.append(_apply_fill(state, side, abs(q), px, bar["minute"], None, "session end"))
    state["closed"] = True
    return events


def equity(state: dict, price: float | None) -> dict:
    """Cash, the position's market value and unrealized P/L at `price`, and the total."""
    pos = state["position"]
    value = pos["qty"] * price if price is not None else 0.0
    unreal = pos["qty"] * (price - pos["avg"]) if price is not None and pos["qty"] else 0.0
    return {"cash": round(state["cash"], 2), "position": pos["qty"], "avg": round(pos["avg"], 4),
            "market_value": round(value, 2), "unrealized": round(unreal, 2), "realized": round(state["realized"], 2),
            "commissions": round(state["commissions"], 2), "equity": round(state["cash"] + value, 2)}
