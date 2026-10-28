"""The day context every study reads from (bars, prior days, warm-up, VWAP, opening range, events), and the
view the chart page asks for.

Everything only looks at bars that started before the cursor time (plus fully finished
prior days), so a replay of a past day never "sees the future". Times are US/Eastern.
"""
from __future__ import annotations

import json
from functools import cached_property

import numpy as np
import pandas as pd

from . import store

PRE_START, RTH_START, RTH_END, POST_END = 4 * 60, 9 * 60 + 30, 16 * 60, 20 * 60
MAX_WARMUP_DAYS = 15
MAX_SHOWN_DAYS = 5
MINUTE_SUMMARY_DAYS = 60     # prior days summarised from 1-min files; older history comes from 1day.parquet


# ---------------------------------------------------------------- helpers
def minute_of_day(times: pd.Series) -> pd.Series:
    return times.dt.hour * 60 + times.dt.minute


def chart_time(ts: pd.Timestamp) -> int:
    """US/Eastern wall-clock time encoded as a UTC epoch, so the chart's axis reads ET."""
    naive = ts.tz_localize(None) if ts.tzinfo else ts
    return int((naive - pd.Timestamp("1970-01-01")).total_seconds())


def fmt_min(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def daily_summary(df: pd.DataFrame) -> dict | None:
    """Regular-hours open/high/low/close/volume for one day of 1-min bars."""
    if df.empty:
        return None
    m = minute_of_day(df["time"])
    rth = df[(m >= RTH_START) & (m < RTH_END)]
    if rth.empty:
        return None
    return {"open": float(rth["open"].iloc[0]), "high": float(rth["high"].max()),
            "low": float(rth["low"].min()), "close": float(rth["close"].iloc[-1]),
            "volume": float(rth["volume"].sum())}


_summary_cache: dict = {}
_tf_cache: dict = {}


def _mtime(symbol: str, day: str) -> float:
    try:
        return store.day_path(symbol, day).stat().st_mtime
    except OSError:
        return 0.0


def cached_summary(symbol: str, day: str) -> dict | None:
    key = (str(store.DATA_DIR), symbol, day)
    mt = _mtime(symbol, day)
    hit = _summary_cache.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    s = daily_summary(store.read_day(symbol, day))
    _summary_cache[key] = (mt, s)
    return s


def prior_context(symbol: str, day: str, lookback: int = 260) -> pd.DataFrame:
    """Daily bars before `day`: from cached 1-min days where present, else from 1day.parquet."""
    minute_days = [d for d in store.list_days(symbol) if d < day][-MINUTE_SUMMARY_DAYS:]
    rows = {}
    for d in minute_days:
        s = cached_summary(symbol, d)
        if s:
            rows[d] = {"date": d, **s}
    daily = store.read_daily(symbol)
    if not daily.empty:
        for r in daily[daily["date"] < day].itertuples():
            rows.setdefault(r.date, {"date": r.date, "open": float(r.open), "high": float(r.high),
                                     "low": float(r.low), "close": float(r.close), "volume": float(r.volume)})
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(sorted(rows.values(), key=lambda x: x["date"])).tail(lookback).reset_index(drop=True)


def atr_from_daily(daily: pd.DataFrame, n: int = 14) -> tuple[float | None, int]:
    if daily.empty:
        return None, 0
    h, l, c = daily["high"].values, daily["low"].values, daily["close"].values
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(h))]
    tr = tr[-n:]
    return float(np.mean(tr)), len(tr)


def chart_times(times: pd.Series) -> np.ndarray:
    """Vectorised chart_time for a Series of timestamps."""
    t = times.dt.tz_localize(None) if times.dt.tz is not None else times
    return ((t - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).to_numpy(dtype=np.int64)


def aggregate(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Group 1-min bars into tf-minute candles aligned to 04:00 (and so to 09:30); works across days.
    Column `ct` is the chart time of each candle."""
    cols = ["time", "bucket", "open", "high", "low", "close", "volume", "ct"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    m = minute_of_day(df["time"])
    bucket = PRE_START + ((m - PRE_START) // tf) * tf
    key = df["time"].dt.normalize() + pd.to_timedelta(bucket, unit="min")
    g = df.assign(key=key, bucket=bucket).groupby("key", sort=True)  # keep tz-aware keys (no .values)
    out = g.agg(bucket=("bucket", "first"), open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    out = out.rename(columns={"key": "time"})
    out["ct"] = chart_times(out["time"])
    return out[cols]


def vwap_frame(bars: pd.DataFrame) -> pd.DataFrame:
    """Cumulative VWAP and volume-weighted standard deviation per 1-min bar."""
    bars = bars.reset_index(drop=True)
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3
    v = bars["volume"].clip(lower=0)
    cv = v.cumsum().replace(0, np.nan)
    vwap = (tp * v).cumsum() / cv
    var = ((tp ** 2) * v).cumsum() / cv - vwap ** 2
    return pd.DataFrame({"time": bars["time"], "vwap": vwap, "sd": np.sqrt(var.clip(lower=0))})


def load_events(path, day: str) -> list[dict]:
    try:
        with open(path) as f:
            events = json.load(f)
    except (OSError, ValueError, TypeError):
        return []
    return [e for e in events if e.get("date") == day and "time" in e]


# ---------------------------------------------------------------- the day context
class DayContext:
    """Bars and shared calculations for one symbol, day, timeframe and cursor time."""

    def __init__(self, symbol: str, day: str, tf: int = 5, cursor: int | None = None,
                 events_path=None, config: dict | None = None, days: int = 1):
        self.symbol, self.day, self.tf = symbol.upper(), day, tf
        self.days = max(1, min(int(days), MAX_SHOWN_DAYS))
        self.config = config or {}
        self.events_path = events_path
        df = store.read_day(self.symbol, day)
        if df.empty:
            raise ValueError(f"No cached bars for {self.symbol} on {day}")
        m_all = minute_of_day(df["time"])
        self.last_minute = int(m_all.iloc[-1]) + 1
        self.cursor = self.last_minute if cursor is None else max(PRE_START + 1, min(int(cursor), POST_END))
        cut = df[m_all < self.cursor].reset_index(drop=True)
        self.cut = cut if not cut.empty else df.iloc[:1].reset_index(drop=True)
        m = minute_of_day(self.cut["time"])
        self.pre = self.cut[(m >= PRE_START) & (m < RTH_START)].reset_index(drop=True)
        self.rth = self.cut[(m >= RTH_START) & (m < RTH_END)].reset_index(drop=True)
        self.price = float(self.cut["close"].iloc[-1])
        self.day0 = self.cut["time"].iloc[0].normalize()

    # -- history
    @cached_property
    def daily(self) -> pd.DataFrame:
        return prior_context(self.symbol, self.day)

    @cached_property
    def atr_info(self):
        return atr_from_daily(self.daily)

    @property
    def atr(self):
        return self.atr_info[0]

    @property
    def pd_row(self):
        return self.daily.iloc[-1] if not self.daily.empty else None

    # -- bars on the chart timeframe
    @cached_property
    def agg(self) -> pd.DataFrame:
        a = aggregate(self.cut, self.tf)
        a["complete"] = (a["bucket"] + self.tf) <= self.cursor
        return a

    def _prior_tf(self, d: str) -> pd.DataFrame:
        key = (str(store.DATA_DIR), self.symbol, d, self.tf)
        mt = _mtime(self.symbol, d)
        hit = _tf_cache.get(key)
        if hit and hit[0] == mt:
            return hit[1]
        a = aggregate(store.read_day(self.symbol, d), self.tf)
        _tf_cache[key] = (mt, a)
        return a

    def tf_bars(self, d: str) -> pd.DataFrame:
        """This symbol's bars on the chart timeframe for an earlier day (whole day, cached)."""
        return self._prior_tf(d)

    def minute_bars(self, d: str) -> pd.DataFrame:
        """This symbol's 1-minute bars for an earlier day (whole day)."""
        return store.read_day(self.symbol, d)

    def companion(self, symbol: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Another symbol's bars (e.g. TICK-NYSE) for the days in `frame`, cut at the replay cursor like the
        chart's own bars. Returns (bars aligned row-for-row with `frame` on the chart timeframe, NaN where
        missing; the 1-minute bars themselves)."""
        days = sorted(set(frame["day"])) if "day" in frame else [self.day]
        parts = []
        for d in days:
            df = store.read_day(symbol, d)
            if df.empty:
                continue
            if d == self.day:
                df = df[minute_of_day(df["time"]) < self.cursor]
            parts.append(df.assign(day=d))
        one = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=[*store.COLUMNS, "day"])
        agg = aggregate(one[store.COLUMNS], self.tf) if not one.empty else pd.DataFrame(columns=["time", "open", "high", "low", "close"])
        aligned = frame[["time"]].merge(agg[["time", "open", "high", "low", "close"]], on="time", how="left")
        return aligned.reset_index(drop=True), one.reset_index(drop=True)

    @cached_property
    def prior_days(self) -> list[str]:
        return [d for d in store.list_days(self.symbol) if d < self.day]

    @cached_property
    def shown_prior_days(self) -> list[str]:
        """Earlier days drawn on the chart when it shows more than one day."""
        return self.prior_days[-(self.days - 1):] if self.days > 1 else []

    @cached_property
    def shown(self) -> pd.DataFrame:
        """Every bar drawn on the chart: the earlier shown days (complete) then today up to the cursor."""
        parts = [self._prior_tf(d).assign(complete=True, day=d) for d in self.shown_prior_days]
        parts.append(self.agg.assign(day=self.day))
        return pd.concat(parts, ignore_index=True).assign(current=True)

    def warm(self, bars_needed: int) -> pd.DataFrame:
        """The shown bars plus at least `bars_needed` bars from earlier days, so an indicator is already
        warmed up at the first drawn bar. Column `current` marks the drawn bars."""
        parts, have = [self.shown], 0
        earlier = [d for d in self.prior_days if d not in self.shown_prior_days]
        for d in reversed(earlier[-MAX_WARMUP_DAYS:]):
            if have >= bars_needed:
                break
            p = self._prior_tf(d)
            parts.insert(0, p.assign(current=False, complete=True, day=d))
            have += len(p)
        return pd.concat(parts, ignore_index=True)

    def points(self, frame: pd.DataFrame, values: pd.Series, digits: int = 4) -> list[dict]:
        """Chart points for the drawn bars only, skipping warm-up and NaN values."""
        vals = pd.to_numeric(pd.Series(values).reset_index(drop=True), errors="coerce").to_numpy(dtype=float)
        keep = frame["current"].to_numpy(dtype=bool) & ~np.isnan(vals)
        cts = frame["ct"].to_numpy()[keep]
        return [{"time": int(t), "value": v} for t, v in zip(cts, np.round(vals[keep], digits).tolist(), strict=True)]

    # -- session VWAP per chart bar
    def _vwap_for(self, bars_1m: pd.DataFrame, agg: pd.DataFrame, session: str) -> pd.DataFrame:
        m = minute_of_day(bars_1m["time"])
        src = bars_1m[(m >= RTH_START) & (m < RTH_END)] if session == "rth" else bars_1m[m >= PRE_START]
        a = agg[["time", "bucket"]].copy()
        if src.empty:
            a["vwap"], a["sd"] = np.nan, np.nan
            return a
        vw = vwap_frame(src)
        vw["bucket"] = PRE_START + ((minute_of_day(vw["time"]) - PRE_START) // self.tf) * self.tf
        last = vw.groupby("bucket")[["vwap", "sd"]].last()
        return a.merge(last, left_on="bucket", right_index=True, how="left")

    def vwap_tf(self, session: str = "rth", shown: bool = False) -> pd.DataFrame:
        """Session VWAP (reset each day) per chart bar: today's bars, or every shown day when shown=True."""
        cache = self.__dict__.setdefault("_vwap_cache", {})
        key = (session, shown)
        if key in cache:
            return cache[key]
        if not shown:
            out = self._vwap_for(self.cut, self.agg, session)
        else:
            parts = [self._vwap_for(self.minute_bars(d), self._prior_tf(d), session) for d in self.shown_prior_days]
            parts.append(self._vwap_for(self.cut, self.agg, session))
            out = pd.concat(parts, ignore_index=True).assign(current=True, ct=self.shown["ct"].to_numpy())
        cache[key] = out
        return out

    # -- regular-hours facts
    @cached_property
    def hod_lod(self):
        if self.rth.empty:
            return None, None
        return float(self.rth["high"].max()), float(self.rth["low"].min())

    @cached_property
    def open_price(self) -> float:
        return float(self.rth["open"].iloc[0]) if not self.rth.empty else self.price

    def opening_range(self, minutes: int) -> dict | None:
        if self.rth.empty:
            return None
        orb = self.rth[minute_of_day(self.rth["time"]) < RTH_START + minutes]
        start = orb["time"].iloc[0]
        return {"high": float(orb["high"].max()), "low": float(orb["low"].min()),
                "complete": bool(self.cursor >= RTH_START + minutes), "minutes": minutes,
                "start": chart_time(start), "end": chart_time(start + pd.Timedelta(minutes=minutes))}

    @cached_property
    def five_closed(self) -> pd.DataFrame:
        if self.rth.empty:
            return pd.DataFrame()
        f = aggregate(self.rth, 5)
        return f[(f["bucket"] + 5) <= self.cursor]

    @cached_property
    def events(self) -> list[dict]:
        evs = load_events(self.events_path, self.day) if self.events_path else []
        return [{**e, "minute": parse_hhmm(e["time"]),
                 "chart_time": chart_time(self.day0 + pd.Timedelta(minutes=parse_hhmm(e["time"])))} for e in evs]

    @cached_property
    def projection(self):
        hod, lod = self.hod_lod
        if not self.atr or hod is None:
            return None
        return {"up": round(lod + self.atr, 2), "down": round(hod - self.atr, 2), "atr": round(self.atr, 2),
                "atr_days": self.atr_info[1], "used": round((hod - lod) / self.atr, 3)}

    def future_times(self) -> list[int]:
        last_bucket = int(self.agg["bucket"].iloc[-1])
        horizon = RTH_END if self.cursor < RTH_END else POST_END
        return [chart_time(self.day0 + pd.Timedelta(minutes=b)) for b in range(last_bucket + self.tf, horizon, self.tf)]


# ---------------------------------------------------------------- the view
def build_view(symbol: str, day: str, tf: int = 5, cursor: int | None = None, studies: list[dict] | None = None,
               events_path=None, config: dict | None = None, days: int = 1) -> dict:
    from . import studies as st  # local import: studies depend on this module

    ctx = DayContext(symbol, day, tf, cursor, events_path, config, days)
    results = {}
    for s in studies or []:
        uid = str(s.get("uid") or s.get("type"))
        results[uid] = st.run_study(ctx, s.get("type", ""), s.get("params") or {})
    return {
        "symbol": ctx.symbol, "day": day, "tf": tf, "days": ctx.days, "shown_days": [*ctx.shown_prior_days, day],
        "period": False, "step": tf * 60, "tf_label": f"{tf}m", "range_label": "Today" if ctx.days == 1 else f"{ctx.days}D",
        "cursor": ctx.cursor, "cursor_label": fmt_min(ctx.cursor),
        "last_minute": ctx.last_minute, "price": ctx.price,
        "bars": [{"time": int(r.ct), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                  "volume": r.volume, "complete": bool(r.complete), "day": r.day,
                  "session": "pre" if r.bucket < RTH_START else ("rth" if r.bucket < RTH_END else "post")}
                 for r in ctx.shown.itertuples()],
        "future": ctx.future_times(),
        "now_time": chart_time(ctx.day0 + pd.Timedelta(minutes=ctx.cursor)),
        "studies": results,
        "context": {"atr": ctx.atr, "atr_days": ctx.atr_info[1], "prior_days": len(ctx.daily),
                    "prior_day": None if ctx.pd_row is None else ctx.pd_row["date"]},
    }
