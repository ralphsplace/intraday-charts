"""Paper trading rules (#43, #67): named true / false conditions, read at each bar's close, written in a form, never as
code. A strategy (strategies.py) trades on them: Buy if ("Rule 1" AND NOT "Rule 3") OR Rule5.

A rule:
    conditions  up to 26 conditions, lettered A, B, C... in order
    when        an expression of its letters and of other saved rules, by name (expr.py):
                (A OR B) AND NOT (X OR (S AND H)), WITHIN 3 (A AND B), A AND "Trend up"
                (default: every condition, A AND B AND ...)
A condition: {"a": operand, "op": "crosses_above" | "crosses_below" | "above" | "below", "b": operand}
An operand: {"price": "open" | "high" | "low" | "close"} | {"value": number}
            | {"study": {"type", "params", "output": a line id, or "level:<name>"}} (settings default to the user's
              study defaults)
A rule has no timeframe of its own: it's read on the bars of the strategy that uses it.

A level ("level:OR high", "level:PH"...) is the one each bar traded against: computed from the bars before the bar
(study_values.py, as Replay practice reads it), and only once it's finished: the opening range high appears once
the opening range is complete, and "close crosses above HOD" means the bar closed above the high of the day before
it. A study whose past values change as new bars arrive can't be traded on without looking ahead: such a study's
line is refused, after a check that computes it at earlier cursors and compares.
"""
from __future__ import annotations

import math
import string

from .. import app_config
from .. import engine as day_engine
from .. import study_values
from ..named import Named
from ..studies import base as studies_base
from . import expr

RULES = Named("paper_rules", "Rule", "rule")
OPS = ("crosses_above", "crosses_below", "above", "below")
PRICES = ("open", "high", "low", "close")
TFS = (1, 2, 3, 5, 15)
MAX_CONDITIONS = 26
LETTERS = string.ascii_uppercase


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
        outs = studies_base.rule_outputs(spec)
        if not outs:
            raise ValueError(f"{where}: {spec['name']} has no line or level a rule can read")
        out = s.get("output") or outs[0]["id"]
        legacy = next((o["id"] for o in outs if o.get("plot") == out), None)      # a level study's plot, saved before #65
        out = legacy or out
        if out not in [o["id"] for o in outs]:
            raise ValueError(f"{where}: {spec['name']} has no '{out}': pick one of " + ", ".join(o["label"] for o in outs))
        params = studies_base.effective_params(s["type"], s.get("params") or {})
        if out.startswith("level:"):
            params = studies_base.rule_params(s["type"], out, params)
        return {"study": {"type": s["type"], "params": params, "output": out}}
    raise ValueError(f"{where}: an operand is a price, a value or a study line")


def condition(c, where: str) -> dict:
    if not isinstance(c, dict) or c.get("op") not in OPS:
        raise ValueError(f"{where}: op is one of " + ", ".join(OPS))
    return {"a": _operand(c.get("a"), where), "op": c["op"], "b": _operand(c.get("b"), where)}


def check(rule: dict, saved: dict | None = None, name: str | None = None) -> dict:
    """The rule with every field checked; ValueError says what's wrong, in words. saved: the saved rules its
    expression may use (default: all of them); name: its own name, so it can't use itself."""
    if not isinstance(rule, dict):
        raise ValueError("A rule is an object")
    cs = rule.get("conditions") or []
    if not isinstance(cs, list) or len(cs) > MAX_CONDITIONS:
        raise ValueError(f"A rule has at most {MAX_CONDITIONS} conditions (A to Z)")
    conds = [condition(c, f"Condition {LETTERS[i]}") for i, c in enumerate(cs)]
    when = rule.get("when")
    if isinstance(when, dict):                                   # from the group editor
        tree = expr.valid_tree(when)
    elif isinstance(when, str) and when.strip():
        tree = expr.parse(when)
    elif conds:
        tree = expr.parse(" AND ".join(LETTERS[: len(conds)]))
    else:
        raise ValueError("A rule needs conditions, or an expression of other rules")
    letters, names = expr.refs(tree)
    missing = [x for x in letters if LETTERS.index(x) >= len(conds)]
    if missing:
        raise ValueError(f"The expression uses {', '.join(missing)}, but the rule has "
                         + (f"conditions A to {LETTERS[len(conds) - 1]}" if conds else "no conditions"))
    saved = all_rules() if saved is None else saved
    for n in names:
        if n not in saved and n != name:
            raise ValueError(f'There is no rule called "{n}"')
    out = {"conditions": conds, "when": expr.text(tree)}
    expand(tree, {**saved, **({name: out} if name else {})}, conds, [name] if name else [])     # refuses a loop
    return out


def expand(tree: dict, saved: dict, conds: list[dict], stack: list[str]) -> dict:
    """The tree with every letter replaced by its condition ({"c": condition}) and every rule by its own tree, all
    the way down: what's evaluated. A rule that uses itself, directly or through others, is refused."""
    if "cond" in tree:
        return {"c": conds[LETTERS.index(tree["cond"])]}
    if "rule" in tree:
        n = tree["rule"]
        if n in stack:
            raise ValueError("A rule can't use itself: " + " uses ".join(f'"{x}"' for x in [*stack[stack.index(n):], n]))
        item = saved.get(n)
        if not item or "when" not in item:
            raise ValueError(f'There is no rule called "{n}"')
        return expand(expr.parse(item["when"]), saved, item["conditions"], [*stack, n])
    if "not" in tree:
        return {"not": expand(tree["not"], saved, conds, stack)}
    if "within" in tree:
        return {"within": tree["within"], "of": expand(tree["of"], saved, conds, stack)}
    op = "and" if "and" in tree else "or"
    return {op: [expand(y, saved, conds, stack) for y in tree[op]]}


def compiled(tree: dict, saved: dict | None = None) -> dict:
    """An expression of saved rules (a strategy's), expanded down to conditions."""
    return expand(tree, all_rules() if saved is None else saved, [], [])


def conditions_in(tree: dict) -> list[dict]:
    if "c" in tree:
        return [tree["c"]]
    if "not" in tree:
        return conditions_in(tree["not"])
    if "within" in tree:
        return conditions_in(tree["of"])
    return [c for y in tree.get("and") or tree.get("or") or [] for c in conditions_in(y)]


def studies_in(trees: list[dict], extra: list[dict] = ()) -> list[dict]:
    """Every study line or level the expanded trees read, and the extra specs (an entry at a level), once each."""
    found = []
    for t in trees:
        for c in conditions_in(t):
            for x in (c["a"], c["b"]):
                if "study" in x and x["study"] not in found:
                    found.append(x["study"])
    for spec in extra:
        if spec not in found:
            found.append(spec)
    return found


def _key(spec: dict) -> str:
    return f"{spec['type']}:{spec['output']}:{sorted(spec['params'].items())}"


def day_series(symbol: str, day: str, tf: int, specs: list[dict]) -> dict:
    """The day's bars at the rule's timeframe and every value the rule reads, by bar: {"bars": [{"start", "end",
    "open", ...}], "<study key>": [value or None per bar]} for each study line or level in specs (studies_in)."""
    ctx = day_engine.DayContext(symbol, day, tf, None)
    a = ctx.agg
    a = a[a["current"]] if "current" in a else a
    bars = [{"start": int(r.bucket), "end": int(r.bucket) + tf, "ct": int(r.ct), "open": float(r.open), "high": float(r.high),
             "low": float(r.low), "close": float(r.close)} for r in a.itertuples()]
    out = {"bars": bars}
    by_ct = {b["ct"]: i for i, b in enumerate(bars)}
    for spec in specs:
        if is_level(spec):
            out[_key(spec)] = _level_series(symbol, day, tf, spec, bars)
            continue
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


def is_level(spec: dict) -> bool:
    return spec["output"].startswith("level:")


def _level_series(symbol: str, day: str, tf: int, spec: dict, bars: list[dict]) -> list:
    """The level each regular-hours bar traded against: as it was when the bar started (none until it's finished;
    none outside regular hours, when no trade is open)."""
    q = {"type": spec["type"], "params": spec["params"], "output": spec["output"], "tf": tf}
    return [study_values.value(symbol, day, q, cursor=b["start"])["value"]
            if day_engine.RTH_START <= b["start"] < day_engine.RTH_END else None for b in bars]


def check_no_repaint(symbol: str, day: str, tf: int, specs: list[dict]) -> None:
    """Refuse a study whose past values change as new bars arrive: its line, computed with the day cut at two
    earlier cursors, must match the whole day's line before them."""
    full = day_series(symbol, day, tf, specs)
    n = len(full["bars"])
    if n < 10:
        return
    for frac in (0.4, 0.7):
        cut = full["bars"][int(n * frac)]["start"]
        ctx = day_engine.DayContext(symbol, day, tf, cut)
        for spec in [x for x in specs if not is_level(x)]:       # levels are read as they were: nothing to check
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


def holds(tree: dict, s: dict, i: int, memo: dict) -> bool:
    """An expanded tree's value at bar i's close (memo: per tree node and bar, kept for the day)."""
    k = (id(tree), i)
    if k in memo:
        return memo[k]
    if "c" in tree:
        v = _holds(tree["c"], s, i)
    elif "not" in tree:
        v = not holds(tree["not"], s, i, memo)
    elif "within" in tree:
        v = any(holds(tree["of"], s, j, memo) for j in range(max(0, i - tree["within"] + 1), i + 1))
    elif "and" in tree:
        v = all(holds(y, s, i, memo) for y in tree["and"])
    else:
        v = any(holds(y, s, i, memo) for y in tree["or"])
    memo[k] = v
    return v


# ---------------------------------------------------------------- saved rules (app-wide, named)
def all_rules() -> dict:
    """{name: {"id", "conditions", "when"}} (anything from before #67 is upgraded at start-up: app/upgrade.py)."""
    return {n: v for n, v in RULES.items().items() if "when" in v}


def users(name: str) -> list[str]:
    """What uses a rule: 'rule "X"', 'strategy "Y"'."""
    from . import strategies
    out = [f'rule "{n}"' for n, v in all_rules().items() if n != name and name in expr.refs(expr.parse(v["when"]))[1]]
    out += [f'strategy "{n}"' for n, v in strategies.all_strategies().items() if name in strategies.rules_used(v)]
    return out


def save(name: str | None, rule: dict) -> tuple[str, dict]:
    """A new rule under `name` (or "Rule N"), or new contents for an existing one, keeping its id."""
    others = all_rules()
    if name and name in others:
        return name, RULES.replace(name, check(rule, {k: v for k, v in others.items() if k != name}, name))
    if name:
        RULES.check_name(name)
    return RULES.create(check(rule, others, name or RULES.next_name(RULES.items())), name)


def rename(old: str, new: str) -> dict:
    """A new name, and every rule and strategy that uses it says the new name."""
    from . import strategies
    new = RULES.check_name(new)
    item = RULES.rename(old, new)
    with app_config.editing() as d:
        for v in d.get("paper_rules", {}).values():
            if isinstance(v, dict) and "when" in v:
                v["when"] = expr.text(expr.rename(expr.parse(v["when"]), old, new))
        for v in d.get("paper_strategies", {}).values():
            if isinstance(v, dict):
                strategies.rename_rule(v, old, new)
    return item


def delete(name: str) -> None:
    """Delete a rule nothing uses (ValueError says what does)."""
    used = users(name)
    if used:
        raise ValueError(f'"{name}" is used by ' + ", ".join(used) + ": change those first")
    RULES.delete(name)
