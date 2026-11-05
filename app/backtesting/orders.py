"""A backtest's orders on a day's bars (backtest.py): the day's 1-minute bars as the engine reads them, and an action
(an order, a bracket, cancel, modify, flatten) applied to the engine, with an ATR trailing distance worked out at
the action's minute from the bars before it.
"""
from __future__ import annotations

from .. import engine as day_engine
from .. import store, study_values
from . import engine

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


def atr_distance(symbol: str, day: str, t: dict, minute: int) -> float:
    """An ATR trailing distance in dollars: {"atr": multiple, "length": n, "tf": minutes} times the ATR on that
    timeframe, as it was when the order went in (from the bars before `minute`, as the chart's ATR study)."""
    mult, n, tf = t.get("atr"), t.get("length", 14), t.get("tf", 1)
    if not (isinstance(mult, (int, float)) and 0 < mult <= 20 and isinstance(n, int) and 1 <= n <= 100):
        raise engine.OrderError("an ATR trailing stop is 0 to 20 times an ATR of 1 to 100 bars")
    v = study_values.value(symbol, day, {"type": "atr", "params": {"length": n}, "output": "atr", "tf": tf}, cursor=minute)["value"]
    if not v:
        raise engine.OrderError(f"ATR ({n}) isn't known yet at {minute // 60:02d}:{minute % 60:02d}")
    return round(mult * v, 4)


def resolved(a: dict, symbol: str, day: str) -> dict:
    """The action with any ATR trailing distance ({"atr": ...}) turned into dollars, at the action's minute. The
    action is kept as written, so a replay works the distance out again the same way."""
    def fix(t):
        return {"amount": atr_distance(symbol, day, t, a["minute"]), "atr": t} if t and "atr" in t else t
    out = a
    if a.get("order", {}).get("trail"):
        out = {**out, "order": {**a["order"], "trail": fix(a["order"]["trail"])}}
    if (a.get("stop") or {}).get("trail"):
        out = {**out, "stop": {**a["stop"], "trail": fix(a["stop"]["trail"])}}
    return out


def apply(st: dict, a: dict, price: float | None, symbol: str | None = None, day: str | None = None) -> list[dict]:
    """An action (order, bracket, cancel, modify, flatten) on the engine at its minute; the events it made."""
    if symbol:
        a = resolved(a, symbol, day)
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
    raise engine.OrderError(f"Unknown action {k}")
