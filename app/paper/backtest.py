"""Strategy backtests (#44, #67): a strategy run over a symbol's cached days with the paper engine, bar by bar, exactly
as Replay practice would trade it; a report of the trades; and the same exits on random entries as a baseline.

"rule" below is a prepared strategy (strategies.prepare): its rules expanded down to their conditions.

Each day: the strategy's signals (strategies.signals, read at each bar's close) become orders at the minute after; the engine
fills them on 1-minute bars (engine.py); what was done is kept as the same actions a practice session keeps
(practice.py), so a day of a backtest can be saved into an account and opened on a chart, where it fills the same.
Stops, targets and trails are measured from the signal bar's close. One position at a time; a new entry signal
while one is open is ignored (unless the rule reverses). Every day ends flat at the last regular-hours bar.
"""
from __future__ import annotations

import datetime
import random
import statistics

from .. import app_config, sessions, store
from . import engine, practice, rules, strategies

MAX_DAYS = 260
BUILT_IN_DEFAULTS = {"symbol": "QQQ", "account": "", "baseline_runs": 5, "missing": "stop"}


def defaults() -> dict:
    """What a new backtest starts with (Config, Backtests): the built-in ones with the Config page's on top."""
    return {**BUILT_IN_DEFAULTS, **(app_config.section("paper").get("backtest") or {})}


def check_defaults(d: dict) -> dict:
    """Backtest defaults checked; ValueError says what's wrong. Only the known keys are kept."""
    out = {**BUILT_IN_DEFAULTS, **{k: v for k, v in d.items() if k in BUILT_IN_DEFAULTS}}
    sym = out["symbol"]
    if not isinstance(sym, str) or not sym.strip() or len(sym) > 12:
        raise ValueError("The symbol is 1 to 12 characters")
    out["symbol"] = sym.strip().upper()
    if not isinstance(out["account"], str) or len(out["account"]) > 200:
        raise ValueError("The account is a paper account's name, or empty for the defaults")
    n = out["baseline_runs"]
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 20:
        raise ValueError("Random runs are 0 to 20")
    if out["missing"] not in ("stop", "skip"):
        raise ValueError("Days without cached bars: stop or skip")
    return out


def trading_days(symbol: str, start: str, end: str) -> tuple[list[str], list[str]]:
    """The trading days from start to end: those with cached bars, and those without."""
    if end < start:
        raise ValueError("The end is before the start")
    have = set(store.list_days(symbol))
    days = []
    cur = datetime.date.fromisoformat(start)
    last = datetime.date.fromisoformat(end)
    while cur <= last:
        d = cur.isoformat()
        if sessions.is_trading_day(d):
            days.append(d)
        cur += datetime.timedelta(days=1)
    if len(days) > MAX_DAYS:
        raise ValueError(f"At most {MAX_DAYS} trading days at a time")
    return [d for d in days if d in have], [d for d in days if d not in have]


def _entry(rule: dict, side: str, close: float, minute: int) -> dict:
    """The actions for an entry: the order, with its stop / target / trail as a bracket when the rule has them."""
    buy = side == "long"
    o = rule["order"]
    order = {"side": "buy" if buy else "sell", "qty": rule["qty"], "type": o["type"]}
    if o["type"] == "limit":
        order["price"] = round(close - o["offset"] if buy else close + o["offset"], 4)
    elif o["type"] == "stop":
        order["price"] = round(close + o["offset"] if buy else close - o["offset"], 4)
    elif o["type"] == "level":
        order["level"] = {"spec": {**o["level"], "tf": rule["tf"]}, "as": o["as"]}
    x = rule["exits"]
    sign = 1 if buy else -1
    stop = {"price": round(close - sign * x["stop"], 4)} if "stop" in x else {"trail": {"amount": x["trail"]}} if "trail" in x else None
    target = {"price": round(close + sign * x["target"], 4)} if "target" in x else None
    if stop or target:
        return {"kind": "bracket", "order": order, **({"stop": stop} if stop else {}), **({"target": target} if target else {}),
                "minute": minute}
    return {"kind": "order", "order": order, "minute": minute}


def _hm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _says(a: dict) -> str:
    """An action in words, for the log."""
    if a["kind"] == "flatten":
        return "flatten"
    o = a["order"]
    out = f"{o['side']} {o['qty']} {o['type']}" + (f" {o['price']:.2f}" if o.get("price") is not None else "")
    if o["type"] == "level":
        out += f" at {o['level']['spec']['type']} {o['level']['spec']['output']} as a {o['level']['as']}"
    for k in ("stop", "target"):
        x = a.get(k)
        if x:
            out += f", {k} " + (f"{x['price']:.2f}" if "price" in x else f"trailing {x['trail']['amount']:.2f}")
    return out


def run_day(rule: dict, symbol: str, day: str, cash: float, settings: dict, entries: list[dict] | None = None,
            series: dict | None = None, log=None) -> dict:
    """One day: the actions the rule takes (or the given entries, for the random baseline), the engine's fills
    and the closing cash. Entries given: {"minute", "what": "long" | "short", "close"}. series: the day's
    rules.day_series, when it's already been worked out (the baseline reuses the rule's). log(text, level): what
    happened, in words (signals acted on, refused or ignored, and fills)."""
    say = log or (lambda text, level="info": None)
    ignored = {"in a trade": 0, "outside the hours": 0, "an opposite trade (no reverse)": 0}
    s = series or rules.day_series(symbol, day, rule["tf"], strategies.studies(rule))
    sig = strategies.signals(rule, s) if entries is None else entries
    by_minute: dict[int, list[dict]] = {}
    for x in sig:
        by_minute.setdefault(x["minute"], []).append(x)
    day_bars = practice.bars(symbol, day)
    st = engine.new_state(cash, settings)
    actions, events, skipped = [], [], []
    h = rule["hours"]

    def level_of(spec):                                       # the level's value at the last closed rule bar
        key = rules._key({k: spec[k] for k in ("type", "params", "output")})
        vals, idx = s.get(key), [i for i, b in enumerate(s["bars"]) if b["end"] <= cur_minute]
        return vals[idx[-1]] if vals and idx else None

    def act(a, why):
        try:
            events.extend(practice._apply(st, a, practice.last_price(day_bars, a["minute"])))
            actions.append(a)
            say(f"{_hm(a['minute'])} {why}: {_says(a)}")
        except engine.PaperError as e:                        # e.g. not enough buying power: skipped, and counted
            skipped.append(str(e))
            say(f"{_hm(a['minute'])} {why}, refused: {e}", "warn")

    for b in day_bars:
        cur_minute = b["minute"]
        for x in by_minute.get(cur_minute, []):
            pos = st["position"]["qty"]
            if x["what"] == "exit_long" and pos > 0 or x["what"] == "exit_short" and pos < 0:
                act({"kind": "flatten", "minute": cur_minute}, f"{x['what'].replace('_', ' ')} signal (close {x['close']:.2f})")
            elif x["what"] in ("long", "short") and not st["closed"]:
                if not h["from"] <= cur_minute <= h["to"]:
                    ignored["outside the hours"] += 1
                    continue
                want = 1 if x["what"] == "long" else -1
                working = [o for o in st["orders"] if not o["exit"]]
                if pos * want > 0 or working:
                    ignored["in a trade"] += 1
                    continue                                  # already in, or an entry is working
                if pos * want < 0:
                    if not rule["exits"]["reverse"]:
                        ignored["an opposite trade (no reverse)"] += 1
                        continue
                    act({"kind": "flatten", "minute": cur_minute}, f"{x['what']} signal, reversing")
                act(_entry(rule, x["what"], x["close"], cur_minute), f"{x['what']} signal (close {x['close']:.2f})")
        for e in engine.step(st, b, level_of):
            events.append({**e, "minute": cur_minute})
            if e["event"] == "fill":
                say(f"{_hm(cur_minute)} filled: {e['side'].upper()} {e['qty']} @ {e['price']:.2f}" + (f" ({e['note']})" if e.get("note") else ""))
    if any(ignored.values()):
        say("signals not taken: " + ", ".join(f"{n} while {k}" if k == "in a trade" else f"{n} {k}" if k == "outside the hours"
                                              else f"{n} against {k}" for k, n in ignored.items() if n))
    return {"day": day, "actions": actions, "fills": [e for e in events if e["event"] == "fill"], "cash": st["cash"],
            "start_cash": cash, "state": st, "skipped": skipped, "series": s}


def trades_of(day: str, fills: list[dict]) -> list[dict]:
    """Round trips from a day's fills: from flat to flat."""
    out, cur, pos = [], None, 0
    for f in fills:
        signed = f["qty"] if f["side"] == "buy" else -f["qty"]
        if pos == 0:
            cur = {"day": day, "side": "long" if signed > 0 else "short", "entry_minute": f["minute"], "entry": f["price"],
                   "qty": abs(signed), "pnl": 0.0, "commission": 0.0}
        cur["pnl"] += -signed * f["price"]
        cur["commission"] += f["commission"]
        pos += signed
        if pos == 0:
            cur.update(exit_minute=f["minute"], exit=f["price"], why=f.get("note") or "")
            cur["pnl"] = round(cur["pnl"] - cur["commission"], 2)
            cur["commission"] = round(cur["commission"], 2)
            out.append(cur)
            cur = None
    return out


def stats(trades: list[dict], days: int) -> dict:
    pnl = [t["pnl"] for t in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p <= 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)

    def part(side):
        ps = [t["pnl"] for t in trades if t["side"] == side]
        return {"trades": len(ps), "total": round(sum(ps), 2), "win_rate": round(100 * sum(p > 0 for p in ps) / len(ps), 1) if ps else None}
    return {"trades": len(pnl), "total": round(sum(pnl), 2), "per_day": round(sum(pnl) / days, 2) if days else None,
            "trades_per_day": round(len(pnl) / days, 2) if days else None,
            "win_rate": round(100 * len(wins) / len(pnl), 1) if pnl else None,
            "avg_win": round(statistics.mean(wins), 2) if wins else None,
            "avg_loss": round(statistics.mean(losses), 2) if losses else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown": round(dd, 2), "long": part("long"), "short": part("short"),
            "commissions": round(sum(t["commission"] for t in trades), 2)}


def _random_entries(rule: dict, symbol: str, day: str, n: int, rng: random.Random) -> list[dict]:
    """n market entries at random minutes in the rule's hours, on the sides the rule trades."""
    sides = strategies.sides(rule)
    day_bars = [b for b in practice.bars(symbol, day) if rule["hours"]["from"] <= b["minute"] <= rule["hours"]["to"]]
    if not day_bars or not n:
        return []
    picks = sorted(rng.sample(day_bars, min(n, len(day_bars))), key=lambda b: b["minute"])
    return [{"minute": b["minute"], "what": rng.choice(sides), "close": practice.last_price(practice.bars(symbol, day), b["minute"]) or b["open"]}
            for b in picks]


def run(rule: dict, symbol: str, days: list[str], cash: float, settings: dict, seed: int = 1, baseline_runs: int = 5,
        progress=None, log=None) -> dict:
    """The rule over `days`, then the baseline. progress(done, total) is called after each day; log(day, text,
    level) with what happened (run_day), a line a day, and the baseline."""
    total = len(days) * (1 + baseline_runs)
    done = 0
    note = log or (lambda day, text, level="info": None)
    results, trades, equity, bal, skipped, series = [], [], [], cash, [], {}
    for d in days:
        r = run_day(rule, symbol, d, bal, settings, log=lambda text, level="info", d=d: note(d, text, level))
        series[d] = r["series"]
        skipped += r["skipped"]
        t = trades_of(d, r["fills"])
        note(d, f"{len(t)} trade(s), P/L {sum(x['pnl'] for x in t):+,.2f}, cash {r['cash']:,.2f}", "day")
        bal = r["cash"]
        trades += t
        equity.append({"day": d, "equity": round(bal, 2)})
        results.append({"day": d, "actions": r["actions"], "trades": len(t)})
        done += 1
        if progress:
            progress(done, total)
    rng = random.Random(seed)
    base_trades = []
    if baseline_runs:
        note(None, f"random entries with the same exits: {baseline_runs} run(s) over the same days")
    random_rule = {**rule, "order": {"type": "market"}}
    for _ in range(baseline_runs):
        for res in results:
            entries = _random_entries(rule, symbol, res["day"], res["trades"], rng)
            r = run_day(random_rule, symbol, res["day"], cash, settings, entries, series[res["day"]])
            base_trades += trades_of(res["day"], r["fills"])
            done += 1
            if progress:
                progress(done, total)
    base = stats(base_trades, len(days) * baseline_runs) if baseline_runs else None
    if base:
        note(None, f"random entries: {base['trades']} trade(s), P/L {base['total']:+,.2f}")
    return {"symbol": symbol, "days": days, "start_cash": cash, "end_cash": round(bal, 2), "trades": trades,
            "equity": equity, "stats": stats(trades, len(days)), "baseline": base, "baseline_runs": baseline_runs,
            "actions": {res["day"]: res["actions"] for res in results}, "demo": symbol.endswith("-DEMO"),
            "skipped": {"count": len(skipped), "first": skipped[0] if skipped else None}}
