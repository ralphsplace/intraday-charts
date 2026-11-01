"""Replay practice: trading a paper account by hand while stepping through a past day (#42).

A practice session is one account, one symbol and one day. It's kept as what was done, not as a running total:
the actions (orders placed, changed, cancelled, flatten), each at the replay minute it was done. Its state is the
paper engine (engine.py) run over the day's 1-minute bars and those actions, up to the cursor; so the session is
always exactly what those bars and actions give, and stepping Replay back is exact: the actions after the new time
are dropped (after asking) and the state recomputed.

The cursor follows the chart's: bars that started before it are shown, and only those have been traded. An order
placed at the cursor can fill on the first bar not yet shown, never on one already on screen.
"""
from __future__ import annotations

import time
import uuid

from .. import engine as day_engine
from .. import store, study_values
from . import accounts, engine

RTH_START, RTH_END = day_engine.RTH_START, day_engine.RTH_END
OPEN_FROM = day_engine.PRE_START                 # orders can be placed from the premarket


def bars(symbol: str, day: str) -> list[dict]:
    """The day's 1-minute bars as the engine reads them; the last regular-hours bar is marked."""
    df = store.read_day(symbol, day)
    if df.empty:
        raise ValueError(f"No bars cached for {symbol} on {day}")
    m = day_engine.minute_of_day(df["time"]).to_numpy()
    rth = [i for i, x in enumerate(m) if RTH_START <= x < RTH_END]
    last = rth[-1] if rth else -1
    return [{"minute": int(m[i]), "open": float(df["open"].iat[i]), "high": float(df["high"].iat[i]),
             "low": float(df["low"].iat[i]), "close": float(df["close"].iat[i]), "last_rth": i == last}
            for i in range(len(df)) if m[i] < RTH_END]


def last_price(day_bars: list[dict], cursor: int) -> float | None:
    shown = [b for b in day_bars if b["minute"] < cursor]
    return shown[-1]["close"] if shown else None


def _levels(symbol: str, day: str, minute: int):
    """A study level's value at the close of the bar before `minute` (the engine's level_of)."""
    def level_of(spec):
        try:
            return study_values.value(symbol, day, spec, cursor=minute)["value"]
        except ValueError:
            return None
    return level_of


def replay(symbol: str, day: str, cash: float, settings: dict, actions: list[dict], cursor: int,
           day_bars: list[dict] | None = None) -> tuple[dict, list[dict], list[str]]:
    """The engine state at `cursor`: the bars before it, with each action applied at its minute. Returns the
    state, the events in order, and the actions that were refused (with why; they're kept out of the state)."""
    day_bars = day_bars if day_bars is not None else bars(symbol, day)
    st = engine.new_state(cash, settings)
    events, refused = [], []
    acts = sorted(enumerate(actions), key=lambda ia: (ia[1]["minute"], ia[0]))
    ai = 0

    def apply_until(minute):
        nonlocal ai
        while ai < len(acts) and acts[ai][1]["minute"] <= minute:
            _, a = acts[ai]
            ai += 1
            try:
                events.extend(_apply(st, a, last_price(day_bars, a["minute"])))
            except engine.PaperError as e:
                refused.append(f"{a['kind']} at {a['minute']}: {e}")
    for b in day_bars:
        if b["minute"] >= cursor:
            break
        apply_until(b["minute"])
        for ev in engine.step(st, b, _levels(symbol, day, b["minute"])):
            events.append({**ev, "minute": b["minute"]})
    apply_until(cursor)
    return st, events, refused


def _apply(st: dict, a: dict, price: float | None) -> list[dict]:
    k, m = a["kind"], a["minute"]
    if k == "order":
        o = engine.place(st, a["order"], m, price)
        return [{"event": "placed", "order": o["id"], "minute": m}]
    if k == "bracket":
        os = engine.bracket(st, a["order"], m, price, a.get("stop"), a.get("target"))
        return [{"event": "placed", "order": o["id"], "minute": m} for o in os]
    if k == "cancel":
        return [{**e, "minute": m} for e in engine.cancel(st, a["id"])]
    if k == "modify":
        engine.modify(st, a["id"], a["changes"])
        return [{"event": "modified", "order": a["id"], "minute": m}]
    if k == "flatten":
        return [{**e, "minute": m} for e in engine.flatten(st, m)]
    raise engine.PaperError(f"Unknown action {k}")


# ---------------------------------------------------------------- sessions in an account's history
def _session(h: dict, symbol: str, day: str) -> dict | None:
    return next((s for s in reversed(h["sessions"]) if s["symbol"] == symbol and s["day"] == day and not s.get("archived")), None)


def view(account: str, symbol: str, day: str, cursor: int) -> dict:
    """The session at `cursor` (made the first time), with what changed since the last view."""
    name, item = accounts.find(account)
    day_bars = bars(symbol, day)
    with accounts.editing_history(item) as h:
        h.setdefault("sessions", [])
        h.setdefault("resets", [])
        s = _session(h, symbol, day)
        if s is None:
            s = {"id": uuid.uuid4().hex[:10], "symbol": symbol, "day": day, "actions": [], "started": time.time(),
                 "cash": accounts.balance(item), "settings": item["settings"], "cursor": OPEN_FROM}
            h["sessions"].append(s)
        st, events, refused = replay(symbol, day, s["cash"], s["settings"], s["actions"], cursor, day_bars)
        seen = s.get("cursor", OPEN_FROM)
        new = [e for e in events if e["event"] == "fill" and e["minute"] >= seen] if cursor > seen else []
        if cursor >= seen:                                      # the furthest it has been: what the balance counts
            s.update(cursor=cursor, state=st, updated=time.time())
    later = [a for a in s["actions"] if a["minute"] > cursor]           # done after this time (one at it is now)
    return {"account": name, "session": s["id"], "symbol": symbol, "day": day, "cursor": cursor,
            "orders": st["orders"], "fills": [e for e in events if e["event"] == "fill"], "new_fills": new,
            "refused": refused, "closed": st["closed"], "later_actions": len(later),
            "equity": engine.equity(st, last_price(day_bars, cursor)), "settings": s["settings"],
            "demo": symbol.endswith("-DEMO")}


def act(account: str, symbol: str, day: str, cursor: int, action: dict) -> dict:
    """Do something at `cursor`: it's checked against the session's state there, then kept."""
    name, item = accounts.find(account)
    day_bars = bars(symbol, day)
    action = {**action, "minute": int(cursor)}
    with accounts.editing_history(item) as h:
        s = _session(h, symbol, day)
        if s is None:
            raise KeyError("Open the practice session first")
        if any(a["minute"] > cursor for a in s["actions"]):
            raise engine.PaperError("The practice is ahead of the replay: step forward, or remove the later trades first")
        st, _, _ = replay(symbol, day, s["cash"], s["settings"], s["actions"], cursor, day_bars)
        _apply(st, action, last_price(day_bars, cursor))      # raises PaperError when the account can't take it
        s["actions"].append(action)
    return view(name, symbol, day, cursor)


def rewind(account: str, symbol: str, day: str, cursor: int) -> dict:
    """Drop what was done after `cursor` (the replay stepped back past it)."""
    name, item = accounts.find(account)
    with accounts.editing_history(item) as h:
        s = _session(h, symbol, day)
        if s is not None:
            s["actions"] = [a for a in s["actions"] if a["minute"] <= cursor]
            s["cursor"] = min(s.get("cursor", cursor), cursor)
    return view(name, symbol, day, cursor)
