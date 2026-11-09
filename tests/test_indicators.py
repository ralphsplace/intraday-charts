import numpy as np
import pandas as pd
import pytest

from app import indicators as ind


def bars(closes):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 1, "low": c - 1, "close": c,
                         "volume": 100.0})


def test_sma_ema_wma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert ind.sma(s, 3).tolist()[2:] == [2, 3, 4]
    assert ind.wma(s, 3).iloc[-1] == pytest.approx((3 * 1 + 4 * 2 + 5 * 3) / 6)
    e = ind.ema(s, 3)
    assert np.isnan(e.iloc[1]) and e.iloc[-1] == pytest.approx(s.ewm(span=3, adjust=False).mean().iloc[-1])


def test_rsi_extremes_and_range():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert ind.rsi(up, 14).iloc[-1] == pytest.approx(100)
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert ind.rsi(down, 14).iloc[-1] == pytest.approx(0)
    rnd = pd.Series(np.random.default_rng(1).normal(0, 1, 300).cumsum() + 100)
    r = ind.rsi(rnd, 14).dropna()
    assert r.between(0, 100).all()


def test_macd_is_ema_difference():
    s = pd.Series(np.random.default_rng(2).normal(0, 1, 200).cumsum() + 50)
    line, sig, hist = ind.macd(s, 12, 26, 9)
    ref = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    assert line.iloc[-1] == pytest.approx(ref.iloc[-1])
    assert hist.iloc[-1] == pytest.approx(line.iloc[-1] - sig.iloc[-1])


def test_bollinger_band_width():
    s = pd.Series([10, 12, 10, 12, 10, 12], dtype=float)
    mid, up, lo = ind.bollinger(s, 4, 2)
    assert mid.iloc[-1] == pytest.approx(11) and up.iloc[-1] - mid.iloc[-1] == pytest.approx(2)


def test_stochastic_and_williams_bounds():
    df = bars(np.random.default_rng(3).normal(0, 1, 200).cumsum() + 100)
    k, d = ind.stochastic(df, 14, 3, 3)
    assert k.dropna().between(0, 100).all()
    assert ind.williams_r(df, 14).dropna().between(-100, 0).all()


def test_adx_strong_trend():
    df = bars(np.arange(100, 200, dtype=float))
    a, pdi, mdi = ind.adx(df, 14)
    assert a.iloc[-1] > 50 and pdi.iloc[-1] > mdi.iloc[-1]


def test_obv_and_psar():
    df = bars([10, 11, 10, 12])
    assert ind.obv(df).tolist() == [0, 100, 0, 100]
    trend = bars(np.arange(100, 160, dtype=float))
    sar = ind.psar(trend, 0.02, 0.2).dropna()
    assert (sar.values < trend["low"].values[-len(sar):]).all()    # below price in an uptrend


def test_pfe_straight_lines_read_100_and_chop_low():
    up = ind.pfe(pd.Series(np.arange(40, dtype=float)), 10, 1)
    assert up.iloc[9] != up.iloc[9] and up.iloc[10:].tolist() == pytest.approx([100.0] * 30)   # n bars of warm-up
    assert ind.pfe(pd.Series(-np.arange(40, dtype=float)), 10, 1).iloc[-1] == pytest.approx(-100)
    chop = ind.pfe(pd.Series([100.0, 105.0] * 20), 10, 1)                 # back and forth, no net move: only the
    assert chop.iloc[-1] == pytest.approx(100 * 10 / (10 * np.sqrt(26)))  # 10-bar width is left, about 20%
    # one-bar-wide steps: 10 bars up by 1 each -> sqrt(10^2 + 10^2) / (10 * sqrt(2)) = 100%
    # 10 bars, one jump of 10: sqrt(10^2 + 10^2) / (9 + sqrt(101)) = about 74%
    jump = ind.pfe(pd.Series([0.0] * 9 + [10.0] * 2), 10, 1)
    assert jump.iloc[-1] == pytest.approx(100 * np.sqrt(200) / (9 + np.sqrt(101)))
    smooth = ind.pfe(pd.Series(np.sin(np.arange(200) / 7) * 5), 10, 5)
    assert smooth.dropna().between(-100, 100).all()


def test_dmi_stochastic_matches_thinkorswims_formula():
    rng = np.random.default_rng(3)
    df = bars(100 + rng.normal(0, 1, 120).cumsum())
    v = ind.dmi_stochastic(df, 10, 3, 3)
    _, pdi, mdi = ind.adx(df, 10)
    osc = (pdi - mdi).to_numpy()
    i = 80                                                         # by hand: Sum(osc - ll, 3) / Sum(hh - ll, 3) * 100
    num = sum(osc[j] - osc[j - 2:j + 1].min() for j in range(i - 2, i + 1))
    den = sum(osc[j - 2:j + 1].max() - osc[j - 2:j + 1].min() for j in range(i - 2, i + 1))
    assert v.iloc[i] == pytest.approx(100 * num / den)
    assert v.dropna().between(0, 100).all()
    rising = ind.dmi_stochastic(bars(np.arange(60, dtype=float) ** 1.5), 10, 3, 3)    # DI+ widening: at the top
    assert rising.iloc[-1] == pytest.approx(100)


def test_trend_channel_is_a_straight_line_with_every_bar_inside():
    """On a rising line with noise, the mid is the least-squares line; the high and low are parallel to it and touch
    the highest high and lowest low; nothing before the window."""
    rng = np.random.default_rng(3)
    close = 100 + 0.25 * np.arange(80) + rng.normal(0, 0.3, 80)
    df = pd.DataFrame({"close": close, "high": close + 0.2, "low": close - 0.2})
    mid, up, lo, slope = ind.trend_channel(df, df["close"], 50)
    assert mid.iloc[:30].isna().all() and mid.iloc[30:].notna().all()
    assert slope == pytest.approx(0.25, abs=0.03)
    d = np.diff(mid.iloc[30:].to_numpy())
    gap = (up - mid).iloc[30:]
    assert np.allclose(d, d[0]) and np.allclose(gap, gap.iloc[-1])                     # straight, and parallel
    assert (df["high"].iloc[30:] <= up.iloc[30:] + 1e-9).all() and (df["low"].iloc[30:] >= lo.iloc[30:] - 1e-9).all()
    assert np.isclose((up - df["high"]).iloc[30:].min(), 0) and np.isclose((df["low"] - lo).iloc[30:].min(), 0)   # touching
    short = ind.trend_channel(df.iloc[:1], df["close"].iloc[:1], 50)
    assert short[3] is None and short[0].isna().all()


def test_alma_is_tradingviews_gaussian_average():
    rng = np.random.default_rng(7)
    s = pd.Series(100 + rng.normal(0, 1, 60).cumsum())
    n, offset, sigma = 9, 0.85, 6.0
    v = ind.alma(s, n, offset, sigma)
    assert v.iloc[: n - 1].isna().all() and v.iloc[n - 1:].notna().all()
    m, sd = offset * (n - 1), n / sigma                  # by hand, as Pine's ta.alma: weight i on series[n - 1 - i]
    x = s.to_numpy()[-n:]
    w = [np.exp(-((i - m) ** 2) / (2 * sd * sd)) for i in range(n)]
    assert v.iloc[-1] == pytest.approx(sum(wi * xi for wi, xi in zip(w, x, strict=True)) / sum(w))
    flat = ind.alma(pd.Series([5.0] * 20), 9)
    assert flat.dropna().tolist() == pytest.approx([5.0] * 12)
    up = ind.alma(pd.Series(np.arange(30, dtype=float)), 9)                        # leans to the newest bars:
    assert ind.sma(pd.Series(np.arange(30, dtype=float)), 9).iloc[-1] < up.iloc[-1] < 29   # above the SMA, below the close
    assert ind.alma(pd.Series(np.arange(30, dtype=float)), 9, offset=0.5).iloc[-1] == pytest.approx(25)   # centred: the middle


def test_stoch_rsi_is_a_stochastic_of_the_rsi():
    rng = np.random.default_rng(11)
    s = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
    k, d = ind.stoch_rsi(s, 14, 14, 3, 3)
    r = ind.rsi(s, 14).to_numpy()
    raw = [100 * (r[j] - r[j - 13:j + 1].min()) / (r[j - 13:j + 1].max() - r[j - 13:j + 1].min()) for j in (197, 198, 199)]
    assert k.iloc[-1] == pytest.approx(sum(raw) / 3)                      # %K: a 3-bar SMA of the raw stochastic
    assert d.iloc[-1] == pytest.approx(k.iloc[-3:].mean())                # %D: a 3-bar SMA of %K
    assert k.dropna().between(0, 100).all() and d.dropna().between(0, 100).all()
    assert k.iloc[:14 + 13 + 2].isna().all()                              # RSI, then its range, then the smoothing


def test_balance_of_power():
    df = pd.DataFrame({"open": [10, 10, 12, 11, 10], "high": [12, 11, 12, 11, 14], "low": [9, 10, 8, 11, 10],
                       "close": [12, 10.5, 8, 11, 13]}, dtype=float)
    assert ind.balance_of_power(df).tolist() == pytest.approx([2 / 3, 0.5, -1, 0, 0.75])   # no range: 0
    sm = ind.balance_of_power(df, 2)
    assert np.isnan(sm.iloc[0]) and sm.iloc[-1] == pytest.approx(0.375)
