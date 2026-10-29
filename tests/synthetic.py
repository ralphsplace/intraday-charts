"""SYNTHETIC test bars: invented prices for the automated tests and UI checks. Not market data.

Saved under the symbols QQQ-DEMO and SPY-DEMO so they can never be mistaken for real QQQ/SPY data. The market
internals for the same days (TICK-NYSE, TRIN-NYSE, VIX, ADD-NYSE, VOLD-NYSE) are invented too; they're only ever
written into a test folder.
The last day (2026-10-16) is scripted to resemble a gap-down morning with a failed VWAP reclaim and
an afternoon sell-off. The app no longer ships with this data; the tests generate it in a temp folder.

To look at it in the app anyway, generate it into a separate data folder, never your real one:
    python tests/synthetic.py --data-dir /tmp/synthetic-data
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import store  # noqa: E402

ET = "America/New_York"
LAST_DAY = "2026-10-16"
N_DAYS = 22


def path_from_anchors(anchors, rng, noise):
    """Minute closes from 04:00 to 19:59 that pass near the (minute, price) anchors."""
    mins = np.arange(4 * 60, 20 * 60)
    xs, ys = zip(*anchors, strict=True)
    base = np.interp(mins, xs, ys)
    walk = np.cumsum(rng.normal(0, 1, len(mins)))
    # Brownian bridge between anchors keeps the shape but adds texture
    bridge = np.zeros_like(walk)
    for a, b in zip(xs[:-1], xs[1:], strict=True):
        i, j = a - 240, min(b - 240, len(mins) - 1)
        seg = walk[i:j + 1] - walk[i]
        t = np.linspace(0, 1, len(seg))
        bridge[i:j + 1] = seg - t * seg[-1]
    sess = np.where((mins >= 570) & (mins < 960), 1.0, 0.35)
    return mins, base + bridge * noise * sess


def bars_for_day(day, anchors, rng, noise, vol_scale):
    mins, closes = path_from_anchors(anchors, rng, noise)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    spread = np.abs(rng.normal(0, noise * 0.9, len(mins))) * np.where((mins >= 570) & (mins < 960), 1, 0.4)
    highs = np.maximum(opens, closes) + spread
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, noise * 0.9, len(mins))) * np.where((mins >= 570) & (mins < 960), 1, 0.4)
    t_rth = (mins - 570) / 390
    u_shape = 0.55 + 2.2 * (t_rth - 0.5) ** 2
    vol = np.where((mins >= 570) & (mins < 960), u_shape * vol_scale, 0.04 * vol_scale)
    vol = vol * rng.lognormal(0, 0.35, len(mins))
    vol[mins == 570] *= 4  # opening print
    day0 = pd.Timestamp(day, tz=ET)
    return pd.DataFrame({"time": [day0 + pd.Timedelta(minutes=int(m)) for m in mins],
                         "open": opens.round(2), "high": highs.round(2), "low": lows.round(2),
                         "close": closes.round(2), "volume": vol.round(0)})


def daily_hl(df):
    m = df["time"].dt.hour * 60 + df["time"].dt.minute
    r = df[(m >= 570) & (m < 960)]
    return r["high"].max(), r["low"].min(), r["close"].iloc[-1]


def generate(data_dir=None):
    """Write the synthetic days into data_dir (default: store.DATA_DIR)."""
    if data_dir is not None:
        store.DATA_DIR = Path(data_dir)
    rng = np.random.default_rng(1016)
    days = pd.bdate_range(end=LAST_DAY, periods=N_DAYS).strftime("%Y-%m-%d").tolist()
    qqq, spy = 712.0, 668.0
    prev = None
    for day in days:
        if day != LAST_DAY:
            drift = rng.normal(0, 0.006)
            o = qqq * (1 + rng.normal(0, 0.003))
            mid = o * (1 + drift / 2 + rng.normal(0, 0.003))
            c = o * (1 + drift)
            anchors = [(240, qqq), (570, o), (700, mid), (850, o * (1 + drift * 0.7)), (959, c), (1199, c)]
        else:
            H, L, C = prev
            o = L * 0.9965                       # gap down below the prior-day low
            anchors = [(240, C * 0.999), (480, C * 0.997), (569, o + 0.4), (570, o),
                       (590, o - 1.6),            # early flush
                       (630, o + 0.3),
                       (638, o + 1.7),            # 10:38 pokes back above VWAP
                       (650, o + 0.6),            # ...and fails
                       (720, o - 0.8), (800, o - 0.2), (840, o - 0.6),
                       (870, o - 3.5),            # 14:30 sell-off after the 2pm event
                       (930, o - 6.2), (959, o - 5.6), (1199, o - 5.9)]
        df = bars_for_day(day, anchors, rng, noise=0.06, vol_scale=60_000)
        store.write_day("QQQ-DEMO", day, df)
        prev = daily_hl(df)
        qqq = prev[2]
        # SPY-DEMO tracks QQQ-DEMO closely with its own noise
        ratio = spy / df["close"].iloc[0]
        sdf = df.copy()
        for col in ["open", "high", "low", "close"]:
            sdf[col] = (df[col] * ratio * (1 + rng.normal(0, 0.0003, len(df)))).round(2)
        sdf["high"] = sdf[["open", "high", "close"]].max(axis=1)
        sdf["low"] = sdf[["open", "low", "close"]].min(axis=1)
        sdf["volume"] = (df["volume"] * 1.4).round(0)
        store.write_day("SPY-DEMO", day, sdf)
        spy = float(sdf["close"].iloc[-1])
    # a year of synthetic daily bars before the 1-minute days, so daily moving averages have history
    first = days[0]
    hist_days = pd.bdate_range(end=pd.Timestamp(first) - pd.Timedelta(days=1), periods=280).strftime("%Y-%m-%d")
    closes = 712.0 * np.exp(np.cumsum(rng.normal(-0.0006, 0.011, len(hist_days)))[::-1] * -1)
    closes = closes * (712.0 / closes[-1])
    rows = []
    for d, c in zip(hist_days, closes, strict=True):
        o = c * (1 + rng.normal(0, 0.004))
        rows.append({"date": d, "open": round(o, 2), "high": round(max(o, c) * (1 + abs(rng.normal(0, 0.004))), 2),
                     "low": round(min(o, c) * (1 - abs(rng.normal(0, 0.004))), 2), "close": round(c, 2),
                     "volume": float(rng.integers(30_000_000, 60_000_000))})
    store.write_daily("QQQ-DEMO", pd.DataFrame(rows))
    # NYSE TICK and TRIN for the same days: TICK leans with QQQ-DEMO's minute-to-minute moves
    for day in days:
        q = store.read_day("QQQ-DEMO", day)
        m = q["time"].dt.hour * 60 + q["time"].dt.minute
        r = q[(m >= 570) & (m < 960)].reset_index(drop=True)
        move = r["close"].diff().fillna(0).to_numpy()
        tick = np.clip(move * 2500 + rng.normal(0, 250, len(r)), -1500, 1500).round()
        hi = tick + np.abs(rng.normal(0, 250, len(r))).round()
        lo = tick - np.abs(rng.normal(0, 250, len(r))).round()
        store.write_day("TICK-NYSE", day, pd.DataFrame({"time": r["time"], "open": np.r_[0, tick[:-1]], "high": hi,
                                                        "low": lo, "close": tick, "volume": 0.0}))
        trin = np.clip(1 - move * 2 + rng.normal(0, 0.2, len(r)), 0.2, 4).round(3)
        store.write_day("TRIN-NYSE", day, pd.DataFrame({"time": r["time"], "open": trin, "high": trin * 1.05,
                                                        "low": trin * 0.95, "close": trin, "volume": 0.0}))
        # VIX moves against QQQ-DEMO; ADD and VOLD (normally recorded live by the collector) build up through the
        # regular session from QQQ-DEMO's moves
        vix = (17.5 - np.cumsum(move) * 0.25 + rng.normal(0, 0.03, len(r))).round(2)
        store.write_day("VIX", day, pd.DataFrame({"time": r["time"], "open": np.r_[vix[0], vix[:-1]], "high": vix + 0.04,
                                                  "low": vix - 0.04, "close": vix, "volume": 0.0}))
        add = np.clip(np.cumsum(move * 120 + rng.normal(0, 12, len(r))), -2200, 2200).round()
        vold = np.cumsum(move * 4e6 + rng.normal(0, 4e5, len(r))).round()
        for sym, v, k in (("ADD-NYSE", add, 15.0), ("VOLD-NYSE", vold, 3e5)):
            store.write_day(sym, day, pd.DataFrame({"time": r["time"], "open": np.r_[v[0], v[:-1]], "high": v + k,
                                                    "low": v - k, "close": v, "volume": 0.0}))
    events = [{"date": LAST_DAY, "time": "10:00", "label": "Example: 10am data release", "kind": "scheduled"},
              {"date": LAST_DAY, "time": "10:31", "label": "Example: headline", "kind": "headline"},
              {"date": LAST_DAY, "time": "14:00", "label": "Example: 2pm Fed event", "kind": "scheduled"}]
    (store.DATA_DIR / "events.json").write_text(json.dumps(events, indent=1))
    print(f"Wrote {len(days)} synthetic days for QQQ-DEMO and SPY-DEMO into {store.DATA_DIR}")


def generate_earnings(data_dir, symbol: str = "ACME-DEMO", seed: int = 11) -> list[dict]:
    """SYNTHETIC earnings for the earnings page: two years of invented daily bars for `symbol` and seven invented
    earnings reports (alternately before the open and after the close), each with a jump on its reaction day.
    Written into data_dir like the collector would (data/earnings/<SYMBOL>.json, source marked synthetic)."""
    from app import earnings
    store.DATA_DIR = Path(data_dir)
    rng = np.random.default_rng(seed)
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=LAST_DAY, periods=500)]
    rets = rng.normal(0.0008, 0.015, len(dates))
    reports, idx = [], [480 - 63 * k for k in range(7)]            # about one report a quarter
    for n, i in enumerate(idx):
        after_close = n % 2 == 0
        day0 = i + 1 if after_close else i
        rets[day0] += (1 if n % 3 else -1) * (0.04 + 0.02 * n)        # the reaction
        reports.append({"date": dates[i], "time": "16:05" if after_close else "07:00", "form": "8-K"})
    close = 50.0 * np.exp(np.cumsum(rets)) * np.linspace(1, 3, len(dates))   # a stock that triples: levels differ a lot
    rows = [{"date": d, "open": round(c * (1 - r / 2), 2), "high": round(c * 1.01, 2), "low": round(c * 0.99, 2),
             "close": round(c, 2), "volume": 1e6} for d, c, r in zip(dates, close, rets, strict=True)]
    store.write_daily(symbol, pd.DataFrame(rows))
    earnings.write(symbol, {"source": "SYNTHETIC test data (invented dates)", "fetched": 0, "status": "ok",
                            "earnings": sorted(reports, key=lambda e: e["date"], reverse=True)})
    return reports


DEMO_OPTIONS_NOW = "2026-10-28 10:00"      # the invented quotes' time (a Wednesday)
DEMO_OPTIONS_DATE = "2026-10-30"           # and the date asked for: that Friday's expiry


def generate_options(data_dir, symbol: str = "ACME-DEMO", target: str = DEMO_OPTIONS_DATE,
                     now: str = DEMO_OPTIONS_NOW) -> dict:
    """SYNTHETIC option quotes for the expected-move page: the real fetch code (tools/option_quotes.py) run
    against the fake TWS's invented chain (30% volatility, plus a 6% "earnings" move on the Thursday), written
    into data_dir like the collector would (data/options/<SYMBOL>.json, marked synthetic)."""
    import fake_tws
    from option_quotes import OptionQuotes

    from app import expected_move
    store.DATA_DIR = Path(data_dir)
    t = pd.Timestamp(now, tz="America/New_York")
    ib = fake_tws.FakeIB(now=lambda: t)
    data = OptionQuotes(ib, option=fake_tws.FakeOption).fetch(fake_tws.qualify(symbol), symbol, target, t)
    data["synthetic"] = True
    expected_move.write(symbol, data)
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, help="folder to write into (use a test folder, not your real data)")
    generate(ap.parse_args().data_dir)
