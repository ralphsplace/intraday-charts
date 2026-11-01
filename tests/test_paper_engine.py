"""The paper engine (app/paper/engine.py): fills on hand-built 1-minute bars where the right answer is known, and the
no-look-ahead check on a random walk, where random entries can't beat their costs."""
import ast
import random
from pathlib import Path

import pytest

from app.paper import engine as E

FREE = {"commission": {"per_share": 0.0, "minimum": 0.0, "max_pct": 1.0}, "slippage": 0.0}


def bar(minute, o, h, l, c, last=False):
    return {"minute": minute, "open": o, "high": h, "low": l, "close": c, "last_rth": last}


def acct(cash=100_000, **settings):
    return E.new_state(cash, {**FREE, **settings})


def fills(events):
    return [(e["side"], e["qty"], e["price"]) for e in events if e["event"] == "fill"]


def test_a_market_order_fills_at_the_next_bars_open_plus_slippage():
    s = acct(slippage=0.02)
    E.place(s, {"side": "buy", "qty": 100, "type": "market"}, minute=600, price=500)
    assert fills(E.step(s, bar(600, 501.0, 502, 500, 501.5))) == [("buy", 100, 501.02)]
    assert s["position"] == {"qty": 100, "avg": 501.02} and s["cash"] == pytest.approx(100_000 - 50_102)


def test_an_order_placed_now_never_fills_on_a_bar_already_shown():
    s = acct()
    E.place(s, {"side": "buy", "qty": 1, "type": "market"}, minute=601, price=500)
    assert E.step(s, bar(600, 499, 499, 499, 499)) == []                 # the bar before the order: shown already


def test_limits_fill_at_their_price_or_better_on_a_gap():
    s = acct()
    E.place(s, {"side": "buy", "qty": 10, "type": "limit", "price": 99.5}, 600, 100)
    assert E.step(s, bar(600, 100, 100.2, 99.6, 99.8)) == []              # didn't trade down to it
    assert fills(E.step(s, bar(601, 99.9, 100, 99.4, 99.7))) == [("buy", 10, 99.5)]
    s = acct()
    E.place(s, {"side": "buy", "qty": 10, "type": "limit", "price": 99.5}, 600, 100)
    assert fills(E.step(s, bar(600, 99.0, 99.3, 98.8, 99.1))) == [("buy", 10, 99.0)]   # opened below: the open


def test_stops_fill_at_their_price_or_worse_on_a_gap_plus_slippage():
    s = acct(slippage=0.01)
    E.place(s, {"side": "buy", "qty": 10, "type": "market"}, 600, 100)
    E.step(s, bar(600, 100, 100, 100, 100))
    E.place(s, {"side": "sell", "qty": 10, "type": "stop", "price": 99.0}, 601, 100)
    assert fills(E.step(s, bar(601, 98.5, 98.9, 98.0, 98.2))) == [("sell", 10, 98.49)]   # gapped through: the open
    assert s["realized"] == pytest.approx(10 * (98.49 - 100.01))


def test_a_bar_touching_both_stop_and_target_exits_at_the_stop():
    s = acct()
    E.bracket(s, {"side": "buy", "qty": 100, "type": "market"}, 600, 100, stop={"price": 99.0}, target={"price": 101.0})
    E.step(s, bar(600, 100, 100, 100, 100))
    ev = E.step(s, bar(601, 100, 101.5, 98.5, 100))
    assert fills(ev) == [("sell", 100, 99.0)]
    assert [e["why"] for e in ev if e["event"] == "cancel"] == ["the other side of the bracket filled"]
    assert s["orders"] == [] and s["position"]["qty"] == 0


def test_a_brackets_exits_wait_for_the_entry_and_start_on_the_next_bar():
    s = acct()
    E.bracket(s, {"side": "buy", "qty": 50, "type": "limit", "price": 99}, 600, 100, target={"price": 100})
    assert E.step(s, bar(600, 100, 100.5, 99.5, 100.2)) == []             # entry not filled: the target waits
    ev = E.step(s, bar(601, 99.5, 100.5, 98.8, 100.4))                    # entry fills; the same bar reaches 100
    assert fills(ev) == [("buy", 50, 99)]
    assert fills(E.step(s, bar(602, 100.1, 100.3, 100, 100.2))) == [("sell", 50, 100.1)]


def test_cancelling_an_entry_cancels_its_exits():
    s = acct()
    entry, *_ = E.bracket(s, {"side": "buy", "qty": 5, "type": "limit", "price": 90}, 600, 100, stop={"price": 85})
    assert len(E.cancel(s, entry["id"])) == 2 and s["orders"] == []


def test_a_trailing_stop_follows_the_best_price_but_not_on_the_bar_that_triggers_it():
    s = acct()
    E.place(s, {"side": "buy", "qty": 10, "type": "market"}, 600, 100)
    E.step(s, bar(600, 100, 100, 100, 100))
    t = E.place(s, {"side": "sell", "qty": 10, "type": "trail", "trail": {"amount": 1.0}}, 601, 100)
    assert t["price"] == 99.0
    E.step(s, bar(601, 100, 102, 100, 101.8))
    assert t["price"] == 101.0                                            # follows the high
    E.step(s, bar(602, 101.5, 101.6, 101.2, 101.3))
    assert t["price"] == 101.0                                            # never moves back
    ev = E.step(s, bar(603, 101.2, 103, 100.5, 102.8))                    # stopped out before the new high counts
    assert fills(ev) == [("sell", 10, 101.0)]


def test_a_trailing_stop_in_percent():
    s = acct()
    t = E.place(s, {"side": "buy", "qty": 1, "type": "trail", "trail": {"pct": 1.0}}, 600, 200)   # a buy stop above
    assert t["price"] == 202.0


def test_an_order_at_a_study_level_uses_the_previous_bars_value():
    s = acct()
    E.place(s, {"side": "buy", "qty": 10, "type": "level", "level": {"spec": {"type": "vwap"}, "as": "limit"}}, 600, 101)
    seen = []

    def vwap(spec):
        seen.append(spec["type"])
        return 100.0
    assert E.step(s, bar(600, 101, 101.2, 100.4, 100.6), vwap) == []      # VWAP 100: not reached
    assert fills(E.step(s, bar(601, 100.5, 100.6, 99.9, 100.2), vwap)) == [("buy", 10, 100.0)]
    assert seen == ["vwap", "vwap"]
    s = acct()                                                            # unknown level (study not ready): no fill
    E.place(s, {"side": "buy", "qty": 1, "type": "level", "level": {"spec": {"type": "sma"}, "as": "limit"}}, 600, 1)
    assert E.step(s, bar(600, 1, 1, 0.5, 1), lambda spec: None) == []


def test_short_and_reverse():
    s = acct()
    E.place(s, {"side": "sell", "qty": 10, "type": "market"}, 600, 100)
    E.step(s, bar(600, 100, 100, 100, 100))
    assert s["position"] == {"qty": -10, "avg": 100.0}
    E.place(s, {"side": "buy", "qty": 15, "type": "market"}, 601, 98)
    E.step(s, bar(601, 98, 98, 98, 98))
    assert s["position"] == {"qty": 5, "avg": 98.0} and s["realized"] == pytest.approx(20.0)


def test_shorting_can_be_turned_off():
    s = acct(shorting=False)
    with pytest.raises(E.PaperError, match="Shorting is off"):
        E.place(s, {"side": "sell", "qty": 1, "type": "market"}, 600, 100)


def test_orders_are_checked():
    s = acct(cash=1000)
    for bad, why in (({"side": "hold", "qty": 1, "type": "market"}, "side"), ({"side": "buy", "qty": 0, "type": "market"}, "quantity"),
                     ({"side": "buy", "qty": 1.5, "type": "market"}, "quantity"), ({"side": "buy", "qty": 1, "type": "limit"}, "price"),
                     ({"side": "buy", "qty": 1, "type": "trail", "trail": {}}, "distance"),
                     ({"side": "buy", "qty": 1, "type": "level", "level": {"spec": {}}}, "study level"),
                     ({"side": "buy", "qty": 100, "type": "market"}, "Not enough cash")):
        with pytest.raises(E.PaperError, match=why):
            E.place(s, bad, 600, 100)


def test_ibkr_fixed_commissions():
    st = E.DEFAULT_SETTINGS
    assert E.commission(100, 500, st) == 1.0                               # $0.50 -> the $1.00 minimum
    assert E.commission(1000, 500, st) == 5.0                              # $0.005 a share
    assert E.commission(10, 5, st) == 0.5                                  # at most 1% of the trade's value


def test_the_session_end_closes_the_position_and_cancels_orders():
    s = acct()
    E.place(s, {"side": "buy", "qty": 10, "type": "market"}, 900, 100)
    E.place(s, {"side": "sell", "qty": 10, "type": "limit", "price": 120}, 900, 100)
    ev = E.step(s, bar(959, 100, 101, 99, 100.5, last=True))
    assert fills(ev) == [("buy", 10, 100), ("sell", 10, 100.5)]
    assert s["orders"] == [] and s["position"]["qty"] == 0 and s["closed"]
    with pytest.raises(E.PaperError, match="session has ended"):
        E.place(s, {"side": "buy", "qty": 1, "type": "market"}, 961, 100)


def test_flatten_and_modify():
    s = acct()
    E.place(s, {"side": "buy", "qty": 10, "type": "market"}, 600, 100)
    E.step(s, bar(600, 100, 100, 100, 100))
    o = E.place(s, {"side": "sell", "qty": 10, "type": "limit", "price": 110}, 601, 100)
    E.modify(s, o["id"], {"price": 105})
    assert s["orders"][0]["price"] == 105
    E.flatten(s, 601)
    assert fills(E.step(s, bar(601, 101, 101, 101, 101))) == [("sell", 10, 101)]


def test_equity():
    s = acct(cash=10_000)
    E.place(s, {"side": "buy", "qty": 10, "type": "market"}, 600, 100)
    E.step(s, bar(600, 100, 100, 100, 100))
    eq = E.equity(s, 103)
    assert eq["unrealized"] == 30 and eq["equity"] == 10_030 and eq["cash"] == 9_000


def test_random_entries_on_a_random_walk_lose_about_their_costs():
    """No look-ahead: on a random walk, random brackets average zero before costs, so after costs they lose."""
    rng = random.Random(5)
    totals = []
    for _day in range(60):
        s = E.new_state(1_000_000)
        px = 500.0
        bars = []
        for m in range(570, 960):
            o = px
            px += rng.gauss(0, 0.05)
            hi, lo = max(o, px) + abs(rng.gauss(0, 0.02)), min(o, px) - abs(rng.gauss(0, 0.02))
            bars.append(bar(m, o, hi, lo, px, last=m == 959))
        for b in bars:
            if not s["orders"] and s["position"]["qty"] == 0 and not s["closed"] and rng.random() < 0.05:
                side = rng.choice(["buy", "sell"])
                sign = 1 if side == "buy" else -1
                E.bracket(s, {"side": side, "qty": 100, "type": "market"}, b["minute"], b["open"],
                          stop={"price": b["open"] - sign * 0.3}, target={"price": b["open"] + sign * 0.3})
            E.step(s, b)
        totals.append(s["cash"] - 1_000_000)
    per_day = sum(totals) / len(totals)
    assert per_day < 0                                                     # costs make random entries lose
    assert per_day > -400                                                  # but only by about the costs


def test_the_engine_never_imports_the_broker():
    tree = ast.parse(Path(E.__file__).read_text())
    names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not ({"ib_async", "ib_insync", "ibapi"} & (names | mods)) and not any("tools" in m for m in mods)
