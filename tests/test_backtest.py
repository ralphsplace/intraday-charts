"""The signal backtest: fills, stops and the no-look-ahead check on data where no signal can work."""
import numpy as np
import pandas as pd
import pytest

import backtest_signals as bt
from app import store

ET = "America/New_York"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def write_random_walk(days=40, seed=3):
    rng = np.random.default_rng(seed)
    px = 500.0
    for d in pd.bdate_range("2026-06-01", periods=days).strftime("%Y-%m-%d"):
        mins = np.arange(4 * 60, 20 * 60)
        steps = rng.normal(0, 0.06, len(mins))
        close = px + np.cumsum(steps)
        open_ = np.concatenate([[px], close[:-1]])
        wig = np.abs(rng.normal(0, 0.04, (2, len(mins))))
        df = pd.DataFrame({"time": [pd.Timestamp(d, tz=ET) + pd.Timedelta(minutes=int(m)) for m in mins],
                           "open": open_, "high": np.maximum(open_, close) + wig[0],
                           "low": np.minimum(open_, close) - wig[1], "close": close,
                           "volume": rng.lognormal(8, 0.5, len(mins))})
        store.write_day("RW", d, df)
        px = close[-1]


def test_no_edge_on_a_random_walk(cache):
    """Volume and price are independent random noise here, so no rule should beat random entries."""
    write_random_walk()
    res = bt.main(["--symbol", "RW", "--stops", "0.15", "--sims", "200", "--cost", "0"])
    for name in ("vzo_tos", "vzo_rules", "vzo_zero", "macd"):
        s = res[(0.15, name)][0]
        assert s["trades"] > 100
        assert abs(s["t_stat"]) < 3, (name, s)
        assert 1 < s["beats_random_pct"] < 99, (name, s)


def bars_frame(rows, day="2026-10-16"):
    df = pd.DataFrame(rows, columns=["minute", "open", "high", "low", "close"])
    df["volume"], df["day"] = 1000.0, day
    return df


def test_stop_fills_at_stop_or_gap_open_and_eod_close():
    rows = [(m, 100, 100.05, 99.95, 100) for m in range(570, 600)]
    rows[5] = (575, 100, 100.05, 99.80, 99.9)     # low reaches a 0.15 stop below 100.00
    a = bt.Arrays(bars_frame(rows))
    x, px, stopped = bt.run_trade(a, 1, +1, -1, 0.15)
    assert stopped and x == 5 and px == pytest.approx(99.85)
    gap = list(rows)
    gap[5] = (575, 99.5, 99.6, 99.4, 99.5)        # opens below the stop: filled at the open
    x, px, stopped = bt.run_trade(bt.Arrays(bars_frame(gap)), 1, +1, -1, 0.15)
    assert stopped and px == pytest.approx(99.5)
    x, px, stopped = bt.run_trade(bt.Arrays(bars_frame(rows)), 1, -1, -1, 0.15)   # short: never stopped
    assert not stopped and x == len(rows) - 1 and px == rows[-1][4]


def test_signal_fills_at_next_bar_open(cache):
    write_random_walk(days=3)
    bars = bt.load_bars("RW", 1, None, None)
    a = bt.Arrays(bars)
    t = bt.simulate(bars, a, "macd", 0.15)
    entry, _, _ = bt.signals(bars, "macd")
    first = t.iloc[0]
    i = np.nonzero((entry != 0) & a.can_enter[np.minimum(np.arange(len(bars)) + 1, len(bars) - 1)])[0][0]
    assert first["entry"] == a.open[i + 1] and first["dir"] == entry[i]


def test_trailing_stop_follows_the_best_price():
    # long from 100.00: price climbs to a 100.50 high, then falls; a 0.15 trail should exit at 100.35
    rows = [(570, 100.00, 100.05, 99.95, 100.0), (571, 100.0, 100.20, 99.98, 100.2), (572, 100.2, 100.50, 100.30, 100.45),
            (573, 100.45, 100.46, 100.30, 100.32), (574, 100.3, 100.3, 99.0, 99.1)] + \
           [(m, 99.1, 99.2, 99.0, 99.1) for m in range(575, 600)]
    a = bt.Arrays(bars_frame(rows))
    x, px, stopped = bt.run_trade(a, 0, +1, -1, 0.15, trail=True)
    assert stopped and x == 3 and px == pytest.approx(100.35)
    x, px, stopped = bt.run_trade(a, 0, +1, -1, 0.15, trail=False)   # fixed stop: rides it down to 99.85
    assert stopped and x == 4 and px == pytest.approx(99.85)


def test_confirmed_vzo_entries_need_a_trigger(cache):
    write_random_walk(days=5)
    bars = bt.load_bars("RW", 1, None, None)
    v = bt.ind.vzo(bars, 20)
    e = bt.vzo_confirmed(bars, v)
    trig_up = bt.tos_crosses(v)[0]
    for i in np.nonzero(e == 1)[0]:
        assert trig_up[max(0, i - bt.CONFIRM_BARS + 1):i + 1].any()
