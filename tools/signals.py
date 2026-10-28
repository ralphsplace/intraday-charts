"""Buy/sell signal rules, used only by the backtester (tools/backtest_signals.py). They are not studies and are
never drawn on the charts. Indicator maths lives in app/indicators.py; this module only turns indicators into
entry and exit signals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.indicators import RTH_CLOSE_MIN, RTH_OPEN_MIN, atr, macd  # noqa: E402,F401


# ---------------------------------------------------------------- CCI / ATR trend line ("Trading BUY/SELL Signal")
def cci_close(price, n: int) -> np.ndarray:
    """thinkorswim f_cci from the technicalwhale script: CCI of one price series (not hlc3); 0 where undefined."""
    s = pd.Series(np.asarray(price, dtype=float))
    avg = s.rolling(n, min_periods=n).mean()
    dev = s.rolling(n, min_periods=n).apply(lambda x: float(np.mean(np.abs(x - x.mean()))), raw=True)
    cci = (s - avg) / dev / 0.015
    cci[(dev == 0) | dev.isna()] = 0.0
    return cci.fillna(0.0).to_numpy()


def cci_atr_line(h, l, c, cci, atr_len: int, mult: float) -> np.ndarray:
    """The script's calcx: a stop line that trails below the lows (low - ATR) while CCI >= 0 and above the
    highs (high + ATR) while CCI < 0. It only ratchets in the trend's direction, and when CCI changes sign it
    carries the other side's level over, so the line turns only once price clears that level by an ATR."""
    h, l, c = (np.asarray(x, dtype=float) for x in (h, l, c))
    n = len(c)
    out = np.full(n, np.nan)
    if not n:
        return out
    prev_c = np.concatenate([[np.nan], c[:-1]])
    tr = np.where(np.isnan(prev_c), h - l, np.maximum(h, prev_c) - np.minimum(l, prev_c))
    w = np.arange(1, atr_len + 1, dtype=float)
    natr = np.full(n, np.nan)
    for i in range(n):
        seg = tr[max(0, i - atr_len + 1):i + 1]
        natr[i] = float(np.dot(seg, w[-len(seg):]) / w[-len(seg):].sum()) * mult
    bu_up, bu_dn = l - natr, h + natr
    buf_up = buf_dn = np.nan
    last_cci = 0.0
    for i in range(n):
        pre_up = bu_up[i] if i == 0 or not buf_up or np.isnan(buf_up) else buf_up
        pre_dn = bu_dn[i] if i == 0 or not buf_dn or np.isnan(buf_dn) else buf_dn
        k = cci[i]
        up1 = pre_dn if (k >= 0 and last_cci < 0) else bu_up[i]
        dn1 = pre_up if (k <= 0 and last_cci > 0) else bu_dn[i]
        if k >= 0:
            buf_up, buf_dn = (pre_up if up1 < pre_up else up1), dn1
        else:
            buf_up, buf_dn = up1, (pre_dn if dn1 > pre_dn else dn1)
        x = buf_up if k >= 0 else buf_dn
        out[i] = c[i] if np.isnan(x) else x
        last_cci = k
    return out


def line_turns(x: np.ndarray) -> np.ndarray:
    """1 while the line last moved up, 0 after it last moved down (the script's swap2)."""
    out = np.zeros(len(x), dtype=int)
    state = 0
    for i in range(1, len(x)):
        if x[i] > x[i - 1]:
            state = 1
        elif x[i] < x[i - 1]:
            state = -1
        out[i] = 1 if state > 0 else 0
    return out


WHALE_HTF_CALC = ["As in the thinkorswim script", "True higher-timeframe bars"]


def whale_signals(df: pd.DataFrame, cci_len=10, atr_len=2, mult=1.0, filt="Higher timeframe",
                  htf_minutes=30, htf_calc=WHALE_HTF_CALC[0]) -> dict:
    """Buy/sell signals of the 'Trading BUY/SELL Signal' script (technicalwhale, thinkorswim port by Sam4Cok).
    df: chart bars with time, high, low, close. Returns the chart-timeframe line, the higher-timeframe line,
    and boolean buy/sell arrays (signal on a bar's close)."""
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    line = cci_atr_line(h, l, c, cci_close(c, cci_len), atr_len, mult)
    swap = line_turns(line)
    # higher timeframe: values of the previous completed higher-timeframe bar, on every chart bar
    t = pd.to_datetime(df["time"])
    key = (t.dt.strftime("%Y-%m-%d") + "/" + ((t.dt.hour * 60 + t.dt.minute) // htf_minutes).astype(str)).to_numpy()
    first = np.r_[True, key[1:] != key[:-1]]
    grp = np.cumsum(first) - 1
    gh = pd.Series(h).groupby(grp).max().to_numpy()
    gl = pd.Series(l).groupby(grp).min().to_numpy()
    gc = pd.Series(c).groupby(grp).last().to_numpy()
    prev = grp - 1
    valid = prev >= 0
    if htf_calc.startswith("True"):
        gline = cci_atr_line(gh, gl, gc, cci_close(gc, cci_len), atr_len, mult)
        htf_line = np.where(valid, gline[np.maximum(prev, 0)], np.nan)
    else:
        # the script computes CCI and ATR over chart bars of the stepped higher-timeframe series
        hs = np.where(valid, gh[np.maximum(prev, 0)], np.nan)
        ls = np.where(valid, gl[np.maximum(prev, 0)], np.nan)
        cs = np.where(valid, gc[np.maximum(prev, 0)], np.nan)
        start = int(np.argmax(valid)) if valid.any() else len(c)
        htf_line = np.full(len(c), np.nan)
        if start < len(c):
            htf_line[start:] = cci_atr_line(hs[start:], ls[start:], cs[start:], cci_close(cs[start:], cci_len),
                                            atr_len, mult)
    hl = np.nan_to_num(htf_line, nan=-np.inf)
    swap_tf = line_turns(np.nan_to_num(htf_line, nan=0.0))
    if filt == "Higher timeframe":
        f_up, f_dn = line > hl, (line < hl) & ~np.isnan(htf_line)
    elif filt == "Trend direction":
        f_up, f_dn = (swap == 1) & (swap_tf == 1), (swap == 0) & (swap_tf == 0)
    else:
        f_up = f_dn = np.ones(len(c), dtype=bool)
    prev_swap = np.r_[swap[0], swap[:-1]]
    return {"line": line, "htf_line": htf_line, "swap": swap, "swap_tf": swap_tf,
            "buy": (prev_swap == 0) & (swap == 1) & f_up, "sell": (prev_swap == 1) & (swap == 0) & f_dn}



# ---------------------------------------------------------------- TICK divergence (Supply Demand Edge)
def supply_demand_edge(day, minute, high, low, t_high, t_low, skip_minutes: int = 0):
    """tosindicators' Supply Demand Edge on TICK, per bar (regular hours, reset each day):
    bearish when price makes a new session high but TICK's high on that bar is below TICK's session high
    so far; bullish when price makes a new session low but TICK's low is above TICK's session low so far.
    Arrays are aligned bar for bar (TICK may be NaN where missing). Returns (bull, bear) boolean arrays."""
    n = len(high)
    bull, bear = np.zeros(n, bool), np.zeros(n, bool)
    cur_day = None
    p_hi = p_lo = t_hi = t_lo = np.nan
    for i in range(n):
        if not (RTH_OPEN_MIN <= minute[i] < RTH_CLOSE_MIN):
            continue
        if day[i] != cur_day:
            cur_day, p_hi, p_lo, t_hi, t_lo = day[i], high[i], low[i], t_high[i], t_low[i]
            continue
        late = minute[i] >= RTH_OPEN_MIN + skip_minutes
        if late and not np.isnan(t_high[i]) and not np.isnan(t_hi):
            if high[i] > p_hi and t_high[i] < t_hi:
                bear[i] = True
            if low[i] < p_lo and t_low[i] > t_lo:
                bull[i] = True
        p_hi, p_lo = max(p_hi, high[i]), min(p_lo, low[i])
        if not np.isnan(t_high[i]):
            t_hi = t_high[i] if np.isnan(t_hi) else max(t_hi, t_high[i])
            t_lo = t_low[i] if np.isnan(t_lo) else min(t_lo, t_low[i])
    return bull, bear



# ---------------------------------------------------------------- VZO exit rule
def vzo_macd_exits(v, close, level: float = 40.0, fast: int = 12, slow: int = 26, signal: int = 9):
    """VZO exit signal: the previous VZO was above `level`, the current VZO is lower (descending), and the
    MACD line is NOT above its signal line. MACD is used for nothing else. Consecutive qualifying bars
    produce one signal, on the first of them. Returns a boolean array."""
    v = np.asarray(v, dtype=float)
    line, sig, _ = macd(pd.Series(np.asarray(close, dtype=float)), fast, slow, signal)
    line, sig = line.to_numpy(dtype=float), sig.to_numpy(dtype=float)
    prev = np.r_[np.nan, v[:-1]]
    cond = (prev > level) & (v < prev) & ~(line > sig) & ~np.isnan(line) & ~np.isnan(sig)
    return cond & ~np.r_[False, cond[:-1]]
