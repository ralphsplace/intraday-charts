"""Recommended paper trading rules, ready to use in strategies (#75): price against the usual lines and levels (VWAP,
SMA 50 / 200, EMA 9 / 21, the opening range), breakouts, trend alignment, slope and momentum, and two trend rules
made of the others. Each is an ordinary rule once added (Config, Paper rules): it can be renamed or changed.
They're checked like any rule, and the tests run every one over the demo days (tests/test_paper_presets.py).
"""
from __future__ import annotations

from . import expr, rules

CLOSE = {"price": "close"}


def study(type_: str, output: str, **params) -> dict:
    return {"study": {"type": type_, "params": params, "output": output}}


VWAP = study("vwap", "vwap")
SMA50, SMA200 = study("sma", "sma", length=50, source="close"), study("sma", "sma", length=200, source="close")
EMA9, EMA21 = study("ema", "ema", length=9, source="close"), study("ema", "ema", length=21, source="close")
ORH = study("session_levels", "level:OR high", or_minutes="15")
ORL = study("session_levels", "level:OR low", or_minutes="15")
PH, PL = study("prior_day", "level:PH"), study("prior_day", "level:PL")
RSI = study("rsi", "rsi", length=14, source="close")
MACD, MACD_SIGNAL = study("macd", "macd"), study("macd", "signal")
VZO = study("vzo", "vzo", length=20)


def cond(a: dict, op: str, b: dict | float | None = None, bars: int = 1) -> dict:
    if op in rules.TRENDS:
        return {"a": a, "op": op, "bars": bars}
    return {"a": a, "op": op, "b": {"value": float(b)} if isinstance(b, (int, float)) else b}


def one(group: str, name: str, about: str, c: dict) -> dict:
    return {"group": group, "name": name, "about": about, "rule": {"conditions": [c], "when": "A"}}


def _price_vs() -> list[dict]:
    out = []
    for label, line in (("VWAP", VWAP), ("SMA 50", SMA50), ("SMA 200", SMA200), ("EMA 9", EMA9), ("EMA 21", EMA21),
                        ("ORH", ORH), ("ORL", ORL)):
        what = {"ORH": "the 15-minute opening range high", "ORL": "the 15-minute opening range low"}.get(label, label)
        out += [one("Price against a line or level", f"Price above {label}", f"The bar closed above {what}.", cond(CLOSE, "above", line)),
                one("Price against a line or level", f"Price below {label}", f"The bar closed below {what}.", cond(CLOSE, "below", line))]
    return out


PRESETS: list[dict] = [
    *_price_vs(),
    # breakouts: the bar that crosses
    one("Crossings and breakouts", "Price crosses above VWAP", "This bar closed above VWAP; the one before closed at or below it.", cond(CLOSE, "crosses_above", VWAP)),
    one("Crossings and breakouts", "Price crosses below VWAP", "This bar closed below VWAP; the one before at or above it.", cond(CLOSE, "crosses_below", VWAP)),
    one("Crossings and breakouts", "Price crosses above EMA 9", "A close back above the 9 EMA.", cond(CLOSE, "crosses_above", EMA9)),
    one("Crossings and breakouts", "Price crosses below EMA 9", "A close back below the 9 EMA.", cond(CLOSE, "crosses_below", EMA9)),
    one("Crossings and breakouts", "ORH breakout", "The first close above the 15-minute opening range high.", cond(CLOSE, "crosses_above", ORH)),
    one("Crossings and breakouts", "ORL breakdown", "The first close below the 15-minute opening range low.", cond(CLOSE, "crosses_below", ORL)),
    one("Crossings and breakouts", "Prior day high breakout", "A close above yesterday's high.", cond(CLOSE, "crosses_above", PH)),
    one("Crossings and breakouts", "Prior day low breakdown", "A close below yesterday's low.", cond(CLOSE, "crosses_below", PL)),
    # trend: moving averages in order
    one("Trend", "EMA 9 above EMA 21", "The fast average above the slow one: short-term uptrend.", cond(EMA9, "above", EMA21)),
    one("Trend", "EMA 9 below EMA 21", "The fast average below the slow one: short-term downtrend.", cond(EMA9, "below", EMA21)),
    one("Trend", "EMA 9 crosses above EMA 21", "The bar the fast average crosses up through the slow one.", cond(EMA9, "crosses_above", EMA21)),
    one("Trend", "EMA 9 crosses below EMA 21", "The bar the fast average crosses down through the slow one.", cond(EMA9, "crosses_below", EMA21)),
    one("Trend", "SMA 50 above SMA 200", "The longer trend is up.", cond(SMA50, "above", SMA200)),
    one("Trend", "SMA 50 below SMA 200", "The longer trend is down.", cond(SMA50, "below", SMA200)),
    # slope: higher or lower than the bar before
    one("Slope", "VWAP rising", "VWAP higher than on the bar before.", cond(VWAP, "rising")),
    one("Slope", "VWAP falling", "VWAP lower than on the bar before.", cond(VWAP, "falling")),
    one("Slope", "EMA 21 rising", "The 21 EMA higher than on the bar before.", cond(EMA21, "rising")),
    one("Slope", "EMA 21 falling", "The 21 EMA lower than on the bar before.", cond(EMA21, "falling")),
    # momentum
    one("Momentum", "RSI above 50", "RSI (14) above 50: buyers in control.", cond(RSI, "above", 50)),
    one("Momentum", "RSI below 50", "RSI (14) below 50: sellers in control.", cond(RSI, "below", 50)),
    one("Momentum", "RSI oversold", "RSI (14) below 30.", cond(RSI, "below", 30)),
    one("Momentum", "RSI overbought", "RSI (14) above 70.", cond(RSI, "above", 70)),
    one("Momentum", "MACD above signal", "MACD above its signal line.", cond(MACD, "above", MACD_SIGNAL)),
    one("Momentum", "MACD below signal", "MACD below its signal line.", cond(MACD, "below", MACD_SIGNAL)),
    {"group": "Momentum", "name": "VZO above -40 and rising", "about": "VZO (20) above -40, and higher than on the bar before.",
     "rule": {"conditions": [cond(VZO, "above", -40), cond(VZO, "rising")], "when": "A AND B"}},
    {"group": "Momentum", "name": "VZO below 40 and falling", "about": "VZO (20) below 40, and lower than on the bar before.",
     "rule": {"conditions": [cond(VZO, "below", 40), cond(VZO, "falling")], "when": "A AND B"}},
    # made of the others (added after them)
    {"group": "Made of other rules", "name": "Bull trend", "about": "Price above VWAP, and the 9 EMA above the 21 EMA.",
     "rule": {"conditions": [], "when": '"Price above VWAP" AND "EMA 9 above EMA 21"'}},
    {"group": "Made of other rules", "name": "Bear trend", "about": "Price below VWAP, and the 9 EMA below the 21 EMA.",
     "rule": {"conditions": [], "when": '"Price below VWAP" AND "EMA 9 below EMA 21"'}},
]
BY_NAME = {p["name"]: p for p in PRESETS}


def listing() -> list[dict]:
    """Every recommended rule: {"group", "name", "about", "added": a saved rule has its name}."""
    have = rules.all_rules()
    return [{"group": p["group"], "name": p["name"], "about": p["about"], "added": p["name"] in have} for p in PRESETS]


def add(names: list[str] | None = None) -> dict:
    """Save the named recommended rules (None: all of them), with the rules they're made of; a saved rule of the
    same name is kept as it is. {"added": [...], "kept": [...]}."""
    want = list(BY_NAME) if names is None else names
    unknown = [n for n in want if n not in BY_NAME]
    if unknown:
        raise KeyError(f"No recommended rule called {', '.join(unknown)}")
    need = []
    for n in want:                                        # a rule made of others brings them along, first
        for dep in expr.refs(expr.parse(BY_NAME[n]["rule"]["when"]))[1]:
            if dep in BY_NAME and dep not in need:
                need.append(dep)
        if n not in need:
            need.append(n)
    added, kept = [], []
    for n in need:
        if n in rules.all_rules():
            kept.append(n)
            continue
        rules.save(n, BY_NAME[n]["rule"])
        added.append(n)
    return {"added": added, "kept": kept}
