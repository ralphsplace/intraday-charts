"""Paper trading rules as data (#43): when to enter and leave a trade, written in a form, never as code. A rule is
checked on the server like a study's settings and evaluated with the same study code as the charts, on the cached
bars, reading each bar only at its close.

A rule:
    tf          the bars the conditions read: 1, 2, 3, 5 or 15 minutes
    long        conditions for a long entry (all of them), or [] for none
    short       conditions for a short entry, or []
    within      the conditions may come true on different bars, all within this many bars (1: the same bar)
    order       the entry: {"type": "market"} | {"type": "limit" | "stop", "offset": dollars from the close}
                | {"type": "level", "level": a study line, "as": "limit" | "stop"}
    qty         shares
    exits       {"stop": dollars, "target": dollars, "trail": dollars (any of them),
                 "exit_long": [conditions], "exit_short": [conditions], "reverse": the opposite entry closes and turns}
    hours       {"from": minute, "to": minute}: new trades start only between (default 09:30 to 15:50)
A condition: {"a": operand, "op": "crosses_above" | "crosses_below" | "above" | "below", "b": operand}
An operand: {"price": "open" | "high" | "low" | "close"} | {"value": number}
            | {"study": {"type", "params", "output": a line id}} (settings default to the user's study defaults)

A study whose past values change as new bars arrive can't be traded on without looking ahead: such a study is
refused, after a check that computes its line at earlier cursors and compares.
"""
from __future__ import annotations

import math

from .. import engine as day_engine
from ..named import Named
from ..studies import base as studies_base

RULES = Named("paper_rules", "Rule", "rule")
OPS = ("crosses_above", "crosses_below", "above", "below")
PRICES = ("open", "high", "low", "close")
TFS = (1, 2, 3, 5, 15)
DEFAULT_HOURS = {"from": 9 * 60 + 30, "to": 15 * 60 + 50}
MAX_CONDITIONS = 8


# ---------------------------------------------------------------- checking a rule
def _operand(x, where: str) -> dict:
    if not isinstance(x, dict) or len(x) != 1:
        raise ValueError(f"{where}: an operand is a price, a value or a study line")
    if "price" in x:
        if x["price"] not in PRICES:
            raise ValueError(f"{where}: price is one of " + ", ".join(PRICES))
        return {"price": x["price"]}
    if "value" in x:
        if not isinstance(x["value"], (int, float)) or isinstance(x["value"], bool) or not math.isfinite(x["value"]):
            raise ValueError(f"{where}: value must be a number")
        return {"value": float(x["value"])}
    if "study" in x:
        s = x["study"] if isinstance(x["study"], dict) else {}
        spec = studies_base.REGISTRY.get(s.get("type"))
        if not spec:
            raise ValueError(f"{where}: unknown study '{s.get('type')}'")
        lines = [p["id"] for p in spec.get("plots", [])]
        out = s.get("output") or (lines[0] if lines else None)
        if lines and out not in lines:
            raise ValueError(f"{where}: {spec['name']} has the lines " + ", ".join(lines))
        return {"study": {"type": s["type"], "params": studies_base.effective_params(s["type"], s.get("params") or {}),
                          "output": out}}
    raise ValueError(f"{where}: an operand is a price, a value or a study line")


def _conditions(xs, where: str) -> list[dict]:
    if not isinstance(xs, list) or len(xs) > MAX_CONDITIONS:
        raise ValueError(f"{where}: a list of at most {MAX_CONDITIONS} conditions")
    out = []
    for i, c in enumerate(xs, 1):
        w = f"{where} {i}"
        if not isinstance(c, dict) or c.get("op") not in OPS:
            raise ValueError(f"{w}: op is one of " + ", ".join(OPS))
        out.append({"a": _operand(c.get("a"), w), "op": c["op"], "b": _operand(c.get("b"), w)})
    return out


def check(rule: dict) -> dict:
    """The rule with every field checked and filled in; ValueError says what's wrong, in words."""
    if not isinstance(rule, dict):
        raise ValueError("A rule is an object")
    tf = rule.get("tf", 3)
    if tf not in TFS:
        raise ValueError("tf is one of " + ", ".join(map(str, TFS)) + " minutes")
    long, short = _conditions(rule.get("long") or [], "long"), _conditions(rule.get("short") or [], "short")
    if not long and not short:
        raise ValueError("A rule needs entry conditions: long, short or both")
    within = rule.get("within", 1)
    if not isinstance(within, int) or not 1 <= within <= 20:
        raise ValueError("within is 1 to 20 bars")
    o = rule.get("order") or {"type": "market"}
    if o.get("type") not in ("market", "limit", "stop", "level"):
        raise ValueError("the entry order is market, limit, stop or level")
    order = {"type": o["type"]}
    if o["type"] in ("limit", "stop"):
        off = o.get("offset", 0)
        if not isinstance(off, (int, float)) or not 0 <= off <= 1000:
            raise ValueError("the entry's offset is $0 to $1,000 from the close")
        order["offset"] = float(off)
    if o["type"] == "level":
        order["level"] = _operand({"study": o.get("level")}, "the entry's level")["study"]
        if o.get("as") not in ("limit", "stop"):
            raise ValueError("an entry at a level works as a limit or a stop")
        order["as"] = o["as"]
    qty = rule.get("qty", 100)
    if not isinstance(qty, int) or not 1 <= qty <= 1_000_000:
        raise ValueError("qty is 1 to 1,000,000 shares")
    e = rule.get("exits") or {}
    exits = {}
    for k in ("stop", "target", "trail"):
        if e.get(k) is not None:
            if not isinstance(e[k], (int, float)) or not 0 < e[k] <= 1000:
                raise ValueError(f"the {k} is a distance of $0 to $1,000")
            exits[k] = float(e[k])
    if "stop" in exits and "trail" in exits:
        raise ValueError("a stop or a trailing stop, not both")
    exits["exit_long"] = _conditions(e.get("exit_long") or [], "exit_long")
    exits["exit_short"] = _conditions(e.get("exit_short") or [], "exit_short")
    exits["reverse"] = bool(e.get("reverse", False))
    h = {**DEFAULT_HOURS, **(rule.get("hours") or {})}
    if not (isinstance(h["from"], int) and isinstance(h["to"], int) and 4 * 60 <= h["from"] < h["to"] <= 16 * 60):
        raise ValueError("hours run from 04:00 to 16:00, from before to")
    return {"tf": tf, "long": long, "short": short, "within": within, "order": order, "qty": qty, "exits": exits,
            "hours": {"from": h["from"], "to": h["to"]}}


def studies_in(rule: dict) -> list[dict]:
    """Every study line the rule reads (to check, and to compute once a day)."""
    found = []
    conds = rule["long"] + rule["short"] + rule["exits"]["exit_long"] + rule["exits"]["exit_short"]
    for c in conds:
        for x in (c["a"], c["b"]):
            if "study" in x and x["study"] not in found:
                found.append(x["study"])
    if rule["order"]["type"] == "level" and rule["order"]["level"] not in found:
        found.append(rule["order"]["level"])
    return found


# ---------------------------------------------------------------- the values, bar by bar
def _key(spec: dict) -> str:
    return f"{spec['type']}:{spec['output']}:{sorted(spec['params'].items())}"


def day_series(symbol: str, day: str, tf: int, rule: dict) -> dict:
    """The day's bars at the rule's timeframe and every value the rule reads, by bar: {"bars": [{"start", "end",
    "open", ...}], "<study key>": [value or None per bar]}."""
    ctx = day_engine.DayContext(symbol, day, tf, None)
    a = ctx.agg
    a = a[a["current"]] if "current" in a else a
    bars = [{"start": int(r.bucket), "end": int(r.bucket) + tf, "ct": int(r.ct), "open": float(r.open), "high": float(r.high),
             "low": float(r.low), "close": float(r.close)} for r in a.itertuples()]
    out = {"bars": bars}
    by_ct = {b["ct"]: i for i, b in enumerate(bars)}
    for spec in studies_in(rule):
        res = studies_base.run_study(ctx, spec["type"], dict(spec["params"]))
        vals = [None] * len(bars)
        for ln in res.get("lines") or []:
            if ln.get("id") == spec["output"]:
                for p in ln.get("data") or []:
                    i = by_ct.get(p["time"])
                    if i is not None and p.get("value") is not None:
                        vals[i] = float(p["value"])
        out[_key(spec)] = vals
    return out


def check_no_repaint(symbol: str, day: str, tf: int, rule: dict) -> None:
    """Refuse a study whose past values change as new bars arrive: its line, computed with the day cut at two
    earlier cursors, must match the whole day's line before them."""
    full = day_series(symbol, day, tf, rule)
    n = len(full["bars"])
    if n < 10:
        return
    for frac in (0.4, 0.7):
        cut = full["bars"][int(n * frac)]["start"]
        ctx = day_engine.DayContext(symbol, day, tf, cut)
        for spec in studies_in(rule):
            res = studies_base.run_study(ctx, spec["type"], dict(spec["params"]))
            line = next((ln for ln in res.get("lines") or [] if ln.get("id") == spec["output"]), None)
            if line is None:
                raise ValueError(f"{spec['type']} has no line '{spec['output']}' to trade on")
            whole = dict(zip((b["ct"] for b in full["bars"]), full[_key(spec)], strict=True))
            for p in line.get("data") or []:
                w = whole.get(p["time"])
                if p["time"] in whole and p.get("value") is not None and w is not None and abs(w - p["value"]) > 1e-6 * max(1, abs(w)):
                    name = studies_base.REGISTRY[spec["type"]]["name"]
                    raise ValueError(f"{name} changes its past values as new bars arrive, so a rule can't trade on it "
                                     "without looking ahead")


def _value(x: dict, s: dict, i: int):
    if "value" in x:
        return x["value"]
    if "price" in x:
        return s["bars"][i][x["price"]]
    return s[_key(x["study"])][i]


def _holds(c: dict, s: dict, i: int) -> bool:
    a, b = _value(c["a"], s, i), _value(c["b"], s, i)
    if a is None or b is None:
        return False
    if c["op"] == "above":
        return a > b
    if c["op"] == "below":
        return a < b
    if i == 0:
        return False
    pa, pb = _value(c["a"], s, i - 1), _value(c["b"], s, i - 1)
    if pa is None or pb is None:
        return False
    return (a > b and pa <= pb) if c["op"] == "crosses_above" else (a < b and pa >= pb)


def _fires(conds: list[dict], s: dict, i: int, within: int) -> bool:
    """Every condition held on some bar of the last `within` bars, and one of them holds on this bar."""
    if not conds:
        return False
    lo = max(0, i - within + 1)
    now = False
    for c in conds:
        hits = [j for j in range(lo, i + 1) if _holds(c, s, j)]
        if not hits:
            return False
        now = now or hits[-1] == i
    return now


def signals(rule: dict, s: dict) -> list[dict]:
    """What the rule says, bar by bar, read at each bar's close: {"minute": the minute after the bar closes (when an
    order goes in), "what": "long" | "short" | "exit_long" | "exit_short", "close", "bar"}."""
    out = []
    for i, b in enumerate(s["bars"]):
        for what, conds in (("exit_long", rule["exits"]["exit_long"]), ("exit_short", rule["exits"]["exit_short"]),
                            ("long", rule["long"]), ("short", rule["short"])):
            if _fires(conds, s, i, rule["within"] if what in ("long", "short") else 1):
                out.append({"minute": b["end"], "what": what, "close": b["close"], "bar": i})
    return out


def level_value(rule: dict, s: dict, i: int):
    """The entry level's value at bar i's close (an entry at a study level)."""
    return s[_key(rule["order"]["level"])][i]


# ---------------------------------------------------------------- saved rules (app-wide, named)
def all_rules() -> dict:
    return RULES.items()


def save(name: str | None, rule: dict) -> tuple[str, dict]:
    """A new rule under `name` (or "Rule N"), or new contents for an existing one, keeping its id."""
    body = {"rule": check(rule)}
    if name and name in RULES.items():
        return name, RULES.replace(name, body)
    return RULES.create(body, name)
