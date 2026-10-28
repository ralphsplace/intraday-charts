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
