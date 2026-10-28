"""Local cache of 1-minute bars, one Parquet file per symbol per trading day.

Layout:  data/bars/<SYMBOL>/1min/<YYYY-MM-DD>.parquet
Columns: time (tz-aware America/New_York, bar start), open, high, low, close, volume

Derived symbols (DERIVED) are computed from another cached symbol when read and never written, e.g. "-VIX":
VIX upside down, as thinkorswim draws it (rising = volatility falling).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ET = "America/New_York"
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
COLUMNS = ["time", "open", "high", "low", "close", "volume"]


def _invert(df: pd.DataFrame) -> pd.DataFrame:
    """Bars upside down: every price negated, so the old low is the new high."""
    out = df.copy()
    out["open"], out["close"], out["high"], out["low"] = -df["open"], -df["close"], -df["low"], -df["high"]
    return out


# derived symbol -> (the cached symbol it comes from, how)
DERIVED = {"-VIX": ("VIX", _invert)}


def source(symbol: str) -> str:
    """The cached symbol behind `symbol`: itself, or what a derived symbol is computed from."""
    return DERIVED.get(symbol.upper(), (symbol.upper(), None))[0]


def bars_dir(symbol: str) -> Path:
    return DATA_DIR / "bars" / source(symbol) / "1min"


def day_path(symbol: str, day: str) -> Path:
    return bars_dir(symbol) / f"{day}.parquet"


def list_symbols() -> list[str]:
    root = DATA_DIR / "bars"
    if not root.exists():
        return []
    have = {p.name for p in root.iterdir() if (p / "1min").is_dir() and any((p / "1min").glob("*.parquet"))}
    return sorted(have | {d for d, (base, _) in DERIVED.items() if base in have})


def list_days(symbol: str) -> list[str]:
    d = bars_dir(symbol)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.parquet"))


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a bar frame to the cache schema, sorted and de-duplicated."""
    df = df[COLUMNS].copy()
    t = pd.to_datetime(df["time"])
    if t.dt.tz is None:
        t = t.dt.tz_localize(ET)
    df["time"] = t.dt.tz_convert(ET)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)


def write_day(symbol: str, day: str, df: pd.DataFrame) -> Path:
    if symbol.upper() in DERIVED:
        raise ValueError(f"{symbol} is computed from {source(symbol)}; write that instead")
    path = day_path(symbol, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    normalize(df).to_parquet(tmp, index=False)
    os.replace(tmp, path)  # atomic, so the server never reads a half-written file
    return path


_day_cache: dict = {}


def read_day(symbol: str, day: str) -> pd.DataFrame:
    """One day of 1-minute bars. Cached in memory until the file changes (the live collector rewrites today's)."""
    if symbol.upper() in DERIVED:
        base, how = DERIVED[symbol.upper()]
        return how(read_day(base, day))
    path = day_path(symbol, day)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return pd.DataFrame(columns=COLUMNS)
    key = str(path)
    hit = _day_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    df = normalize(pd.read_parquet(path))
    if len(_day_cache) > 400:
        _day_cache.clear()
    _day_cache[key] = (mtime, df)
    return df


# ---------------------------------------------------------------- daily bars
# Optional: data/bars/<SYMBOL>/1day.parquet with columns date (YYYY-MM-DD), open, high, low, close, volume.
# Written by tools/fetch_ibkr.py --daily-years N; supplies long history (e.g. 200-day SMA)
# without having to cache years of 1-minute bars.
DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def daily_path(symbol: str) -> Path:
    return DATA_DIR / "bars" / source(symbol) / "1day.parquet"


def write_daily(symbol: str, df: pd.DataFrame, years: int | None = None) -> Path:
    """Save daily bars; `years` notes how much history was asked for (daily_years), so a deeper setting is
    fetched once and a stock with a shorter life isn't asked again and again."""
    path = daily_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[DAILY_COLUMNS].copy()
    out["date"] = out["date"].astype(str)
    out = out.drop_duplicates("date", keep="last").sort_values("date")
    tmp = path.with_suffix(".tmp")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    if years is not None:
        path.with_suffix(".json").write_text(json.dumps({"years": int(years)}))
    return path


def daily_years(symbol: str) -> int:
    """The years of daily history last asked for (0 when unknown, e.g. a file from an older version)."""
    try:
        return int(json.loads(daily_path(symbol).with_suffix(".json").read_text()).get("years", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def read_daily(symbol: str) -> pd.DataFrame:
    if symbol.upper() in DERIVED:
        base, how = DERIVED[symbol.upper()]
        return how(read_daily(base))
    path = daily_path(symbol)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    hit = _day_cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    df = pd.read_parquet(path)
    df["date"] = df["date"].astype(str)
    _day_cache[str(path)] = (mtime, df)
    return df
