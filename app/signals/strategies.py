"""Signal strategies (#67, #83): what to do on saved rules (rules.py). Backtests run a strategy; it's checked on the
server and kept in the application config by name.

A strategy:
    tf          the bars its rules are read on: 1, 2, 3, 5 or 15 minutes
    buy         when to go long: an expression of saved rules (expr.py), e.g. ("Rule 1" AND NOT "Rule 3") OR Rule5
    short       when to go short ("" for never); at least one of buy and short
    exit_long   when to close a long ("" for only the stop, target, trail or session end)
    exit_short  when to close a short
    order       the entry: {"type": "market"} | {"type": "limit" | "stop", "offset": dollars from the close}
                | {"type": "level", "level": a study line or level, "as": "limit" | "stop"}
    qty         shares
    exits       {"stop": dollars, "target": dollars, "trail": dollars, "trail_atr": a multiple of the ATR, with
                 "atr_length" (14) on the strategy's bars, worked out when the entry goes in (one kind of stop),
                 "reverse": an opposite entry closes the trade and turns it}
    hours       {"from": minute, "to": minute}: new trades start only between (default 09:30 to 15:50)

prepare() turns a strategy into what backtest.py runs: the same fields, with each expression expanded down to its
conditions ("when"), so a backtest keeps what the rules said when it ran.
"""
from __future__ import annotations

from ..named import Named
from . import expr, rules

STRATEGIES = Named("signal_strategies", "Strategy", "strategy")
SIGNALS = (("buy", "long"), ("short", "short"), ("exit_long", "exit_long"), ("exit_short", "exit_short"))
DEFAULT_HOURS = {"from": 9 * 60 + 30, "to": 15 * 60 + 50}
WORDS = {"buy": "Buy if", "short": "Sell short if", "exit_long": "Close a long if", "exit_short": "Close a short if"}


def _expression(x, where: str, saved: dict) -> str:
    """An expression of saved rules as text ("" for none)."""
    if x in (None, ""):
        return ""
    tree = expr.valid_tree(x) if isinstance(x, dict) else expr.parse(x) if isinstance(x, str) else None
    if tree is None:
        raise ValueError(f"{where}: an expression")
    letters, names = expr.refs(tree)
    if letters:
        raise ValueError(f"{where}: {', '.join(letters)} would be a rule's own condition. Write conditions in a rule, "
                         'and use the rule here by name (in quotes if it has spaces: "Rule 1")')
    for n in names:
        if n not in saved:
            raise ValueError(f'{where}: there is no rule called "{n}"')
    rules.compiled(tree, saved)                                        # a loop inside the rules is refused
    return expr.text(tree)


def check(st: dict, saved: dict | None = None) -> dict:
    """The strategy with every field checked and filled in; ValueError says what's wrong, in words."""
    if not isinstance(st, dict):
        raise ValueError("A strategy is an object")
    saved = rules.all_rules() if saved is None else saved
    tf = st.get("tf", 3)
    if tf not in rules.TFS:
        raise ValueError("tf is one of " + ", ".join(map(str, rules.TFS)) + " minutes")
    out = {"tf": tf}
    for k, _ in SIGNALS:
        try:
            out[k] = _expression(st.get(k), WORDS[k], saved)
        except expr.ExprError as e:
            raise ValueError(f"{WORDS[k]}: {e}") from None
    if not out["buy"] and not out["short"]:
        raise ValueError("A strategy needs Buy if, Sell short if, or both")
    o = st.get("order") or {"type": "market"}
    if o.get("type") not in ("market", "limit", "stop", "level"):
        raise ValueError("the entry order is market, limit, stop or level")
    order = {"type": o["type"]}
    if o["type"] in ("limit", "stop"):
        off = o.get("offset", 0)
        if not isinstance(off, (int, float)) or not 0 <= off <= 1000:
            raise ValueError("the entry's offset is $0 to $1,000 from the close")
        order["offset"] = float(off)
    if o["type"] == "level":
        order["level"] = rules._operand({"study": o.get("level")}, "the entry's level")["study"]
        if o.get("as") not in ("limit", "stop"):
            raise ValueError("an entry at a level works as a limit or a stop")
        order["as"] = o["as"]
    qty = st.get("qty", 100)
    if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= 1_000_000:
        raise ValueError("qty is 1 to 1,000,000 shares")
    e = st.get("exits") or {}
    exits = {}
    for k in ("stop", "target", "trail"):
        if e.get(k) is not None:
            if not isinstance(e[k], (int, float)) or not 0 < e[k] <= 1000:
                raise ValueError(f"the {k} is a distance of $0 to $1,000")
            exits[k] = float(e[k])
    if e.get("trail_atr") is not None:                     # a trailing stop of N x ATR, worked out at the entry
        if not isinstance(e["trail_atr"], (int, float)) or isinstance(e["trail_atr"], bool) or not 0 < e["trail_atr"] <= 20:
            raise ValueError("the ATR trailing stop is 0 to 20 times the ATR")
        n = e.get("atr_length", 14)
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 100:
            raise ValueError("the ATR's length is 1 to 100 bars")
        exits["trail_atr"], exits["atr_length"] = float(e["trail_atr"]), n
    if sum(k in exits for k in ("stop", "trail", "trail_atr")) > 1:
        raise ValueError("one stop: a stop, a trailing stop or an ATR trailing stop")
    exits["reverse"] = bool(e.get("reverse", False))
    h = {**DEFAULT_HOURS, **(st.get("hours") or {})}
    if not (isinstance(h["from"], int) and isinstance(h["to"], int) and 4 * 60 <= h["from"] < h["to"] <= 16 * 60):
        raise ValueError("hours run from 04:00 to 16:00, from before to")
    return {**out, "order": order, "qty": qty, "exits": exits, "hours": {"from": h["from"], "to": h["to"]}}


def prepare(st: dict, saved: dict | None = None) -> dict:
    """What a backtest runs: the checked strategy with "when": {"long", "short", "exit_long", "exit_short"}, each an
    expression expanded down to its conditions (or None)."""
    saved = rules.all_rules() if saved is None else saved
    st = check(st, saved)
    when = {what: rules.compiled(expr.parse(st[k]), saved) if st[k] else None for k, what in SIGNALS}
    return {**st, "when": when}


def studies(c: dict) -> list[dict]:
    """Every study line or level a compiled strategy reads (to check, and to compute once a day)."""
    extra = [c["order"]["level"]] if c["order"]["type"] == "level" else []
    return rules.studies_in([t for t in c["when"].values() if t], extra)


def signals(c: dict, s: dict, check=None) -> list[dict]:
    """What a compiled strategy says, bar by bar, read at each bar's close: {"minute": the minute after the bar
    closes (when an order goes in), "what": "long" | "short" | "exit_long" | "exit_short", "close", "bar"}."""
    out, memo = [], {}
    order = [w for w in ("exit_long", "exit_short", "long", "short") if c["when"][w]]
    for i, b in enumerate(s["bars"]):
        if check:
            check()
        for what in order:
            if rules.holds(c["when"][what], s, i, memo):
                out.append({"minute": b["end"], "what": what, "close": b["close"], "bar": i})
    return out


def sides(c: dict) -> list[str]:
    return [x for x in ("long", "short") if c["when"][x]]


# ---------------------------------------------------------------- saved strategies (app-wide, named)
def all_strategies() -> dict:
    return {n: v for n, v in STRATEGIES.items().items() if "buy" in v}


def rules_used(st: dict) -> list[str]:
    names = []
    for k, _ in SIGNALS:
        if st.get(k):
            names += [n for n in expr.refs(expr.parse(st[k]))[1] if n not in names]
    return names


def rename_rule(st: dict, old: str, new: str) -> None:
    """A saved strategy, in place, with rule `old` called `new` (rules.rename)."""
    for k, _ in SIGNALS:
        if st.get(k):
            st[k] = expr.text(expr.rename(expr.parse(st[k]), old, new))


def save(name: str | None, st: dict) -> tuple[str, dict]:
    body = check(st)
    if name and name in STRATEGIES.items():
        return name, STRATEGIES.replace(name, body)
    return STRATEGIES.create(body, name)
