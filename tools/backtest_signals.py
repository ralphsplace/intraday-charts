"""Backtest VZO and MACD entry signals with a fixed stop, on the bars cached by the TWS collector.

Answers one question: with the same stop, do VZO signals do better than MACD signals, and does either
do better than entering at random?

    python tools/backtest_signals.py --symbol QQQ --tf 1 --stops 0.15 0.30
    python tools/backtest_signals.py --symbol QQQ --tf 3 --start 2026-08-01 --out reports/

Fill rules (no look-ahead):
  - Signals are read at a bar's close. The trade is filled at the next bar's open.
  - New trades start only from 09:30 to 15:50 ET. Every trade is closed at the last bar before 16:00.
  - Stop: a fixed dollar amount from the fill price, on the underlying's price. A bar whose low (long) or
    high (short) reaches the stop exits there, or at that bar's open if price gapped through it.
  - Other exits: the strategy's exit signal, or the opposite entry signal (which reverses the trade).
  - Costs: --cost dollars per share per round trip (spread plus slippage), subtracted from every trade.

Strategies:
  macd        MACD(12,26,9) line crosses its signal line: up = long, down = short.
  vzo_tos     thinkorswim STO_VZO_Lower arrows: VZO crosses up through +5 = long, down through -5 = short.
  vzo_tos_x   the same arrows plus the VZO exit signal (closes longs): previous VZO above 40, current VZO
              lower, and MACD(12,26,9) not above its signal line
  vzo_zero    VZO crosses 0: up = long, down = short.
  vzo_rules   Khalil & Steckler's rules (as in thinkorswim's VolumeZoneOscillator):
                trend up (ADX(14) > 18 and close > EMA(60)): long when VZO crosses up through -40
                trend down (ADX > 18 and close < EMA(60)):   short when VZO crosses down through +40
                no trend (ADX <= 18): long on crossing up through -40 or +15,
                                      short on crossing down through +40 or -5
                exits: long when VZO crosses down through +60, or through 0 with close below EMA(60);
                       short mirrored (-60, or 0 with close above EMA(60))
  vzo_conf_*  VZO trigger confirmed by MACD and ADX:
                trigger (--vzo-trigger): tos   = VZO crosses up through +5 / down through -5 (default)
                                         zones = VZO crosses up through -40 / down through +40
                confirm, all on one bar within 3 bars of the trigger:
                  MACD converging: the histogram rose two bars running (long) / fell two bars running (short)
                  ADX(14) >= 20 and the +DI minus -DI spread widened toward the trade (long: rose; short: fell)
                exits: vzo_conf_macd  MACD line crosses its signal line against the trade (plus the fixed stop)
                       vzo_conf_trail trailing stop: starts at the stop distance, then follows the best price
                                      reached by the same distance
                       vzo_conf_both  whichever of the two comes first
  whale       "Trading BUY/SELL Signal" (technicalwhale): B / S arrows of the CCI + ATR trend line, with the
              script's default filter (line above / below the 30-minute line, computed as the script does)
  whale_raw   the same arrows without the filter
              (exits for both: stop, opposite arrow or 15:59; the script's own 4 / 3 x ATR(200) areas are
              not used here, so every strategy is compared under the same stop)
  sde         Supply Demand Edge (NYSE TICK divergence): long when price makes a new session low but TICK
              doesn't, short when price makes a new session high but TICK doesn't
  tick_fade   long after a TICK reading of -1000 or lower, short after +1000 or higher (fade the extreme)
  tick_follow the opposite: go with the extreme
              (TICK strategies need TICK-NYSE in the cache; days without it have no trades)
  random      baseline: the same number of trades as each strategy, at random entry bars and directions,
              held for the same planned time with the same stop. Repeated --sims times.

Indicators are calculated on all cached bars (pre- and post-market included, as on the charts), carried
across days.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import indicators as ind  # noqa: E402
import signals as sg  # noqa: E402  (tools/signals.py: the buy/sell rules)
from app import store  # noqa: E402

RTH_OPEN, LAST_ENTRY, RTH_END = 9 * 60 + 30, 15 * 60 + 50, 16 * 60
CONFIRM_BARS = 3       # MACD and ADX must confirm within this many bars of the VZO trigger (trigger bar included)
ADX_MIN = 20
TICK_EXTREME = 1000
VZO = {"len": 20, "trigger": "tos"}   # set from --vzo-len / --vzo-trigger; 20 matches STO_VZO_Lower (20)
TRAILING = {"vzo_conf_trail", "vzo_conf_both"}   # strategies whose stop trails


# ---------------------------------------------------------------- data
def load_bars(symbol: str, tf: int, start: str | None, end: str | None) -> pd.DataFrame:
    days = [d for d in store.list_days(symbol) if (not start or d >= start) and (not end or d <= end)]
    if not days:
        raise SystemExit(f"No cached {symbol} bars{' in that date range' if start or end else ''}. "
                         "Fetch them first (Load data… in the chart page, or tools/fetch_ibkr.py --days N).")
    frames = []
    for d in days:
        df = store.read_day(symbol, d)
        if df.empty:
            continue
        m = df["time"].dt.hour * 60 + df["time"].dt.minute
        df = df.assign(day=d, bucket=(m // tf) * tf)
        g = df.groupby("bucket", sort=True).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                                close=("close", "last"), volume=("volume", "sum"))
        g["day"] = d
        g["minute"] = g.index.astype(int)
        frames.append(g.reset_index(drop=True))
    bars = pd.concat(frames, ignore_index=True)
    return bars


def rth_days(bars: pd.DataFrame) -> list[str]:
    """Days with a regular session (at least an hour of bars after 09:30)."""
    r = bars[(bars["minute"] >= RTH_OPEN) & (bars["minute"] < RTH_END)]
    counts = r.groupby("day").size()
    return [d for d, n in counts.items() if n * (bars.attrs.get("tf", 1)) >= 60]


# ---------------------------------------------------------------- signals: +1 long, -1 short, 0 none
def crosses_up(s: pd.Series, level) -> pd.Series:
    prev = s.shift(1)
    lvp = level if np.isscalar(level) else level.shift(1)
    return (s > level) & (prev <= lvp)


def crosses_down(s: pd.Series, level) -> pd.Series:
    prev = s.shift(1)
    lvp = level if np.isscalar(level) else level.shift(1)
    return (s < level) & (prev >= lvp)


def signals(bars: pd.DataFrame, name: str):
    """Returns (entry, exit_long, exit_short) arrays for a strategy."""
    n = len(bars)
    none = np.zeros(n, dtype=bool)
    if name.startswith("whale"):
        t = pd.to_datetime(bars["day"]) + pd.to_timedelta(bars["minute"], unit="m")
        sig = sg.whale_signals(bars.assign(time=t), filt="No filter" if name == "whale_raw" else "Higher timeframe")
        return np.where(sig["buy"], 1, np.where(sig["sell"], -1, 0)), none, none
    if name in ("sde", "tick_fade", "tick_follow"):
        t = bars.attrs.get("tick")
        if t is None:
            return np.zeros(n, dtype=int), none, none
        if name == "sde":
            bull, bear = sg.supply_demand_edge(bars["day"].to_numpy(), bars["minute"].to_numpy(),
                                                bars["high"].to_numpy(float), bars["low"].to_numpy(float),
                                                t["high"].to_numpy(float), t["low"].to_numpy(float))
            return np.where(bull, 1, np.where(bear, -1, 0)), none, none
        hi_x = (t["high"] >= TICK_EXTREME).to_numpy()
        lo_x = (t["low"] <= -TICK_EXTREME).to_numpy()
        sign = 1 if name == "tick_follow" else -1
        entry = np.where(hi_x & ~lo_x, sign, np.where(lo_x & ~hi_x, -sign, 0))
        return entry, none, none
    if name == "macd":
        line, sig, _ = ind.macd(bars["close"], 12, 26, 9)
        entry = np.where(crosses_up(line, sig), 1, np.where(crosses_down(line, sig), -1, 0))
        return entry, none, none
    v = ind.vzo(bars, VZO["len"])
    if name in ("vzo_tos", "vzo_tos_x"):
        up, dn = tos_crosses(v)
        entry = np.where(up, 1, np.where(dn, -1, 0))
        if name == "vzo_tos_x":
            return entry, sg.vzo_macd_exits(v, bars["close"]), none
        return entry, none, none
    if name == "vzo_zero":
        entry = np.where(crosses_up(v, 0), 1, np.where(crosses_down(v, 0), -1, 0))
        return entry, none, none
    if name == "vzo_rules":
        adx = ind.adx(bars, 14)[0]
        e60 = ind.ema(bars["close"], 60)
        c = bars["close"]
        up = (adx > 18) & (c > e60)
        dn = (adx > 18) & (c < e60)
        flat = adx <= 18
        long_ = (up & crosses_up(v, -40)) | (flat & (crosses_up(v, -40) | crosses_up(v, 15)))
        short = (dn & crosses_down(v, 40)) | (flat & (crosses_down(v, 40) | crosses_down(v, -5)))
        entry = np.where(long_, 1, np.where(short, -1, 0))
        exit_long = (crosses_down(v, 60) | (crosses_down(v, 0) & (c < e60))).to_numpy()
        exit_short = (crosses_up(v, -60) | (crosses_up(v, 0) & (c > e60))).to_numpy()
        return entry, exit_long, exit_short
    if name.startswith("vzo_conf_"):
        entry = vzo_confirmed(bars, v)
        line, sig, _ = ind.macd(bars["close"], 12, 26, 9)
        if name in ("vzo_conf_macd", "vzo_conf_both"):
            return entry, crosses_down(line, sig).to_numpy(), crosses_up(line, sig).to_numpy()
        return entry, none, none
    raise ValueError(name)


def tos_crosses(v: pd.Series):
    """STO_VZO_Lower's arrows, exactly as the chart draws them: VZO >= +5 after < +5, and <= -5 after > -5."""
    prev = v.shift(1)
    return ((v >= 5) & (prev < 5)).to_numpy(), ((v <= -5) & (prev > -5)).to_numpy()


def vzo_confirmed(bars: pd.DataFrame, v: pd.Series) -> np.ndarray:
    """+1/-1 on the first bar, within CONFIRM_BARS of a VZO trigger, where MACD and ADX both confirm."""
    _, _, hist = ind.macd(bars["close"], 12, 26, 9)
    adx, plus_di, minus_di = ind.adx(bars, 14)
    spread = plus_di - minus_di
    conf = {
        1: ((hist > hist.shift(1)) & (hist.shift(1) > hist.shift(2)) & (adx >= ADX_MIN) & (spread > spread.shift(1))),
        -1: ((hist < hist.shift(1)) & (hist.shift(1) < hist.shift(2)) & (adx >= ADX_MIN) & (spread < spread.shift(1))),
    }
    if VZO["trigger"] == "tos":
        up, dn = tos_crosses(v)
    else:
        up, dn = crosses_up(v, -40).to_numpy(), crosses_down(v, 40).to_numpy()
    trig = {1: up, -1: dn}
    out = np.zeros(len(bars), dtype=int)
    for d in (1, -1):
        ok = conf[d].fillna(False).to_numpy()
        armed_until = -1
        for i in range(len(bars)):
            if trig[d][i]:
                armed_until = i + CONFIRM_BARS - 1
            if i <= armed_until and ok[i]:
                if out[i] == 0:
                    out[i] = d
                armed_until = -1          # one entry per trigger
    return out


# ---------------------------------------------------------------- trade simulation
class Arrays:
    def __init__(self, bars: pd.DataFrame):
        self.open = bars["open"].to_numpy(float)
        self.high = bars["high"].to_numpy(float)
        self.low = bars["low"].to_numpy(float)
        self.close = bars["close"].to_numpy(float)
        self.minute = bars["minute"].to_numpy(int)
        self.day = bars["day"].to_numpy()
        # index of each day's last bar before 16:00 (the forced exit)
        rth = (self.minute >= RTH_OPEN) & (self.minute < RTH_END)
        self.eod = np.full(len(bars), -1)
        last = {}
        for i in np.nonzero(rth)[0]:
            last[self.day[i]] = i
        for i in range(len(bars)):
            self.eod[i] = last.get(self.day[i], -1)
        self.can_enter = rth & (self.minute < LAST_ENTRY) & (self.eod >= 0)


def run_trade(a: Arrays, e: int, d: int, planned: int, stop: float, trail: bool = False):
    """Trade filled at open[e], direction d, planned exit at open[planned] (planned < 0: hold to the
    day's last bar and exit at its close). Returns (exit_index, price, stopped).

    With trail=True the stop follows the best price reached on earlier bars, by the same distance. Only
    finished bars move it, because within a bar we can't tell whether the high or the low came first."""
    entry = a.open[e]
    eod = a.eod[e]
    end = eod if planned < 0 or planned > eod else planned - 1      # bars held fully
    seg_lo, seg_hi = a.low[e:end + 1], a.high[e:end + 1]
    if trail:
        best = np.maximum.accumulate(seg_hi) if d > 0 else np.minimum.accumulate(seg_lo)
        best = np.concatenate([[entry], best[:-1]])                      # best price before each bar
        level = np.maximum(entry - stop, best - stop) if d > 0 else np.minimum(entry + stop, best + stop)
    else:
        level = np.full(len(seg_lo), entry - d * stop)
    hit = np.nonzero(seg_lo <= level)[0] if d > 0 else np.nonzero(seg_hi >= level)[0]
    if hit.size:
        k = int(hit[0])
        j, lv = e + k, level[k]
        px = lv if j == e else (min(a.open[j], lv) if d > 0 else max(a.open[j], lv))
        return j, px, True
    if planned < 0 or planned > eod:
        return eod, a.close[eod], False
    return planned, a.open[planned], False


def simulate(bars: pd.DataFrame, a: Arrays, name: str, stop: float):
    entry, xl, xs = signals(bars, name)
    trail = name in TRAILING
    n = len(bars)
    trades = []
    i = 0
    sig_idx = np.nonzero((entry != 0) | xl | xs)[0]
    pos_ptr = 0
    while pos_ptr < len(sig_idx):
        i = sig_idx[pos_ptr]
        pos_ptr += 1
        d = int(entry[i])
        e = i + 1
        if d == 0 or e >= n or not a.can_enter[e] or a.day[e] != a.day[i]:
            continue
        # planned exit: the first later bar with an exit for this side or an opposite entry, filled next open
        k = pos_ptr
        planned = -1
        reverse = False
        while k < len(sig_idx):
            j = sig_idx[k]
            if a.day[j] != a.day[e] or j >= a.eod[e]:
                break
            if j >= e and ((entry[j] == -d) or (d > 0 and xl[j]) or (d < 0 and xs[j])):
                planned = j + 1
                reverse = entry[j] == -d
                break
            k += 1
        x, px, stopped = run_trade(a, e, d, planned, stop, trail)
        trades.append({"day": a.day[e], "entry_min": int(a.minute[e]), "dir": d, "entry": a.open[e],
                       "exit_min": int(a.minute[x]), "exit": px, "stopped": stopped,
                       "planned_bars": (planned if planned > 0 else a.eod[e] + 1) - e,
                       "pnl": d * (px - a.open[e])})
        # continue from the exit: a reversing signal at planned-1 opens the next trade
        nxt = (planned - 1) if (reverse and not stopped) else x
        while pos_ptr < len(sig_idx) and sig_idx[pos_ptr] < nxt:
            pos_ptr += 1
    return pd.DataFrame(trades)


def random_baseline(a: Arrays, trades: pd.DataFrame, stop: float, sims: int, rng, trail: bool = False) -> np.ndarray:
    """Mean P&L per trade of `sims` random strategies with the same trade count and holding times."""
    starts = np.nonzero(a.can_enter)[0]
    holds = trades["planned_bars"].to_numpy(int)
    means = np.empty(sims)
    for s in range(sims):
        es = rng.choice(starts, size=len(holds))
        ds = rng.choice([-1, 1], size=len(holds))
        tot = 0.0
        for e, d, h in zip(es, ds, holds, strict=True):
            planned = e + h if e + h <= a.eod[e] else -1
            _, px, _ = run_trade(a, e, d, planned, stop, trail)
            tot += d * (px - a.open[e])
        means[s] = tot / len(holds)
    return means


# ---------------------------------------------------------------- report
def stats(t: pd.DataFrame, cost: float) -> dict:
    if t.empty:
        return {"trades": 0}
    net = t["pnl"] - cost
    wins, losses = net[net > 0].sum(), -net[net < 0].sum()
    eq = net.cumsum()
    sd = net.std(ddof=1) if len(net) > 1 else np.nan
    return {"trades": len(t), "days": t["day"].nunique(), "win%": 100 * (net > 0).mean(),
            "stopped%": 100 * t["stopped"].mean(),
            "avg_gross": t["pnl"].mean(), "avg_net": net.mean(), "total_net": net.sum(),
            "profit_factor": wins / losses if losses else np.inf,
            "max_dd": float((eq.cummax() - eq).max()),
            "t_stat": net.mean() / (sd / np.sqrt(len(net))) if sd and sd > 0 else np.nan,
            "avg_hold_bars": float(np.where(t["stopped"], np.nan, t["planned_bars"]).astype(float).mean())}


def fmt_row(name, s, extra=""):
    if not s.get("trades"):
        return f"  {name:<14} no trades"
    return (f"  {name:<14} {s['trades']:>6} {s['win%']:>6.1f} {s['stopped%']:>7.1f} {s['avg_gross']:>+8.3f} "
            f"{s['avg_net']:>+8.3f} {s['total_net']:>+9.2f} {s['profit_factor']:>5.2f} {s['max_dd']:>7.2f} "
            f"{s['t_stat']:>+6.2f}{extra}")


HEADER = ("  strategy       trades   win%  stopped  avg/sh    net/sh   total$/sh   PF   maxDD$  t-stat  "
          "random: mean/sh  better than")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--tf", type=int, default=1, choices=[1, 2, 3, 5, 15], help="bar size in minutes (default 1)")
    p.add_argument("--stops", type=float, nargs="+", default=[0.15, 0.30],
                   help="stop distances in dollars on the underlying (default 0.15 0.30)")
    p.add_argument("--cost", type=float, default=0.01, help="round-trip cost per share in dollars (default 0.01)")
    p.add_argument("--strategies", nargs="+",
                   default=["vzo_tos", "vzo_tos_x", "whale", "whale_raw", "sde", "tick_fade", "tick_follow", "vzo_rules", "vzo_zero", "macd", "vzo_conf_macd", "vzo_conf_trail",
                            "vzo_conf_both"])
    p.add_argument("--tick", default="TICK-NYSE", help="TICK index used by the TICK strategies (default TICK-NYSE)")
    p.add_argument("--vzo-len", type=int, default=20, help="VZO length (default 20, as STO_VZO_Lower (20))")
    p.add_argument("--vzo-trigger", choices=["tos", "zones"], default="tos",
                   help="trigger for the vzo_conf strategies: tos = +/-5 crossings (default), zones = -40 / +40")
    p.add_argument("--start"), p.add_argument("--end")
    p.add_argument("--sims", type=int, default=300, help="random-entry runs per strategy (default 300)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", help="folder for the trade lists (CSV)")
    p.add_argument("--data-dir", help="cache folder (default: ./data)")
    args = p.parse_args(argv)
    if args.data_dir:
        store.DATA_DIR = Path(args.data_dir)
    VZO["len"], VZO["trigger"] = args.vzo_len, args.vzo_trigger

    bars = load_bars(args.symbol.upper(), args.tf, args.start, args.end)
    bars.attrs["tf"] = args.tf
    try:
        tk = load_bars(args.tick, args.tf, args.start, args.end) if store.list_days(args.tick) else None
    except SystemExit:
        tk = None
    if tk is not None:
        bars.attrs["tick"] = bars[["day", "minute"]].merge(tk[["day", "minute", "high", "low", "close"]],
                                                           on=["day", "minute"], how="left")
        tick_days = set(tk["day"])
        print(f"{args.tick}: cached for {len(tick_days & set(bars['day']))} of the days")
    a = Arrays(bars)
    days = rth_days(bars)
    if not days:
        raise SystemExit("No regular-session days in the cache.")
    half = days[len(days) // 2] if len(days) > 1 else days[0]
    rng = np.random.default_rng(args.seed)
    print(f"{args.symbol.upper()} {args.tf}-minute bars, {len(days)} trading days ({days[0]} to {days[-1]}). "
          f"Cost {args.cost:.3f}/share round trip. Dollar figures are per share of the underlying.")
    if any(s.endswith("-DEMO") for s in [args.symbol.upper()]):
        print("NOTE: synthetic test data: the results mean nothing.")
    results = {}
    for stop in args.stops:
        print(f"\n=== Stop ${stop:.2f} ===")
        print(HEADER)
        for name in args.strategies:
            t = simulate(bars, a, name, stop)
            t = t[t["day"].isin(days)] if not t.empty else t
            s = stats(t, args.cost)
            extra = ""
            if s.get("trades", 0) >= 5:
                rm = random_baseline(a, t, stop, args.sims, rng, name in TRAILING) - args.cost
                pct = 100 * (rm < s["avg_net"]).mean()
                extra = f"   {rm.mean():>+8.3f}        {pct:5.1f}% of runs"
                s["random_mean"], s["beats_random_pct"] = rm.mean(), pct
            print(fmt_row(name, s, extra))
            results[(stop, name)] = (s, t)
            if args.out and not t.empty:
                Path(args.out).mkdir(parents=True, exist_ok=True)
                t.to_csv(Path(args.out) / f"{args.symbol.upper()}_{args.tf}m_{name}_stop{stop:.2f}.csv", index=False)
        # first half vs second half of the days: does the ranking hold out of sample?
        print(f"  split at {half}:        first half avg net/sh | second half avg net/sh")
        for name in args.strategies:
            t = results[(stop, name)][1]
            if t.empty:
                continue
            a1, a2 = stats(t[t["day"] < half], args.cost), stats(t[t["day"] >= half], args.cost)
            f = lambda s: f"{s['avg_net']:+.3f} ({s['trades']})" if s.get("trades") else "   n/a"  # noqa: E731
            print(f"  {name:<14} {f(a1):>24} | {f(a2)}")
    print("\nHow to read it:\n"
          "- 'better than' is the share of random-entry runs (same trade count, holding times and stop) that\n"
          "  the strategy beat. Near 50% = no better than chance. Treat an edge as real only if it beats\n"
          "  97.5%+ of runs, has a t-stat above +2 after costs, AND stays positive in both halves of the days.\n"
          "  On pure random data one of the three still reaches ~95% by luck now and then.\n"
          "- Dollars are per share of the underlying. For an option, multiply by its delta and by 100 per\n"
          "  contract, then subtract the option's own bid-ask spread, which is usually larger than --cost.")
    return results


if __name__ == "__main__":
    main()
