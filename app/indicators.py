"""Standard technical indicators on a bar DataFrame (columns open/high/low/close/volume).

Smoothing conventions follow the common charting-platform definitions:
RSI, ATR and ADX use Wilder's smoothing; Bollinger uses the population standard deviation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SOURCES = ["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"]


def source(df: pd.DataFrame, name: str) -> pd.Series:
    if name == "hl2":
        return (df["high"] + df["low"]) / 2
    if name == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3
    if name == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    return df[name].astype(float)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=n).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's moving average."""
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    return rma(true_range(df), n)


def rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    up, down = rma(d.clip(lower=0), n), rma((-d).clip(lower=0), n)
    rs = up / down.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(down != 0, 100.0).where(up.notna())


def macd(s: pd.Series, fast: int, slow: int, signal: int):
    line = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    line = line.where(pd.Series(np.arange(len(s)) >= slow - 1, index=s.index))
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(s: pd.Series, n: int, mult: float):
    mid = sma(s, n)
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    return mid, mid + mult * sd, mid - mult * sd


def keltner(df: pd.DataFrame, n: int, mult: float):
    mid = ema(df["close"], n)
    a = atr(df, n)
    return mid, mid + mult * a, mid - mult * a


def donchian(df: pd.DataFrame, n: int):
    hi = df["high"].rolling(n, min_periods=n).max()
    lo = df["low"].rolling(n, min_periods=n).min()
    return (hi + lo) / 2, hi, lo


def stochastic(df: pd.DataFrame, k: int, smooth: int, d: int):
    lo = df["low"].rolling(k, min_periods=k).min()
    hi = df["high"].rolling(k, min_periods=k).max()
    raw = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    kline = raw.rolling(smooth, min_periods=smooth).mean()
    return kline, kline.rolling(d, min_periods=d).mean()


def williams_r(df: pd.DataFrame, n: int) -> pd.Series:
    hi = df["high"].rolling(n, min_periods=n).max()
    lo = df["low"].rolling(n, min_periods=n).min()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, np.nan)


def cci(df: pd.DataFrame, n: int) -> pd.Series:
    tp = source(df, "hlc3")
    ma = tp.rolling(n, min_periods=n).mean()
    md = tp.rolling(n, min_periods=n).apply(lambda x: float(np.mean(np.abs(x - x.mean()))), raw=True)
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def adx(df: pd.DataFrame, n: int):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = rma(true_range(df), n)
    plus_di = 100 * rma(plus_dm, n) / tr
    minus_di = 100 * rma(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx, n), plus_di, minus_di


def dmi_stochastic(df: pd.DataFrame, n: int, hl: int, sums: int) -> pd.Series:
    """DMI Stochastic Extreme (Barbara Star, 2013; thinkorswim's DMI_StochasticExtreme): a stochastic of the DMI
    oscillator (+DI minus -DI): the sum over `sums` bars of (osc - lowest) over the sum of (highest - lowest),
    highest and lowest over `hl` bars, as a %."""
    _, pdi, mdi = adx(df, n)
    osc = pdi - mdi
    hh, ll = osc.rolling(hl, min_periods=hl).max(), osc.rolling(hl, min_periods=hl).min()
    num = (osc - ll).rolling(sums, min_periods=sums).sum()
    den = (hh - ll).rolling(sums, min_periods=sums).sum()
    return 100 * num / den.replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def psar(df: pd.DataFrame, step: float, max_step: float) -> pd.Series:
    h, l = df["high"].values, df["low"].values
    n = len(h)
    out = np.full(n, np.nan)
    if n < 2:
        return pd.Series(out, index=df.index)
    up = h[1] >= h[0]
    sar = l[0] if up else h[0]
    ep = h[1] if up else l[1]
    af = step
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, max_step)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, max_step)
        out[i] = sar
    return pd.Series(out, index=df.index)


def vzo(df: pd.DataFrame, n: int) -> pd.Series:
    """Volume Zone Oscillator (Khalil & Steckler): EMA of direction-signed volume as a % of EMA of volume."""
    direction = np.sign(df["close"].diff()).fillna(0).replace(0, 1)
    r = ema(direction * df["volume"], n)
    v = ema(df["volume"].astype(float), n)
    return 100 * r / v.replace(0, np.nan)


def pfe(s: pd.Series, n: int, smooth: int) -> pd.Series:
    """Polarized Fractal Efficiency (Hannula): the straight-line distance over the last n bars as a % of the
    bar-by-bar path, each step one bar wide and price in its own units; negative when price fell over the n bars,
    then EMA-smoothed. A straight line reads +/-100, a choppy path near 0."""
    change = s - s.shift(n)
    straight = np.sqrt(change ** 2 + n ** 2)
    path = np.sqrt(s.diff() ** 2 + 1).rolling(n, min_periods=n).sum()
    raw = 100 * np.sign(change).replace(0, 1) * straight / path
    return ema(raw, smooth) if smooth > 1 else raw


def value_area(volumes, share: float = 0.70) -> tuple[int, int, int]:
    """Point of control and value area of a volume-at-price profile (rows ordered by price): the busiest row,
    then grow one row at a time toward the busier neighbour until `share` of the volume is covered.
    Returns (poc, low, high) row indexes."""
    vol = np.asarray(volumes, dtype=float)
    n = len(vol)
    poc = int(np.argmax(vol))
    target, acc, i, j = vol.sum() * share, vol[poc], poc, poc
    while acc < target and (i > 0 or j < n - 1):
        down = vol[i - 1] if i > 0 else -1
        up = vol[j + 1] if j < n - 1 else -1
        if up >= down:
            j += 1
            acc += up
        else:
            i -= 1
            acc += down
    return poc, i, j


# ---------------------------------------------------------------- market internals (NYSE TICK)
RTH_OPEN_MIN, RTH_CLOSE_MIN = 9 * 60 + 30, 16 * 60


def cumulative_tick(day, minute, high, low, close):
    """Running total of TICK's (high + low + close) / 3 per 1-minute bar from 09:30, reset each day."""
    hlc3 = (np.asarray(high, float) + np.asarray(low, float) + np.asarray(close, float)) / 3
    out = np.full(len(hlc3), np.nan)
    total, cur_day = 0.0, None
    for i in range(len(hlc3)):
        if not (RTH_OPEN_MIN <= minute[i] < RTH_CLOSE_MIN) or np.isnan(hlc3[i]):
            continue
        if day[i] != cur_day:
            cur_day, total = day[i], 0.0
        total += hlc3[i]
        out[i] = total
    return out
