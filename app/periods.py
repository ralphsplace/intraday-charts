"""Daily, weekly and monthly candles: the period context studies read from, and the view the chart page asks for.

One job: daily prices in, period candles out, with the same interface the generic studies use on intraday charts
(warm, points, shown, price, daily). The days before the replay day come from the daily cache (and recent cached
1-minute days, engine.prior_context). The replay day itself is built from its 1-minute bars up to the cursor, in
regular hours, so a replay never sees the rest of the day; in Live it is today's candle as it forms.
"""
from __future__ import annotations

from functools import cached_property

import pandas as pd

from . import engine as en
from . import store
from . import timeframes as tfs

ALL_HISTORY = 100_000        # daily rows: everything cached
FUTURE_SLOTS = 3             # empty candles to the right of the last one


def _period_start(dates: pd.Series, period: str) -> pd.Series:
    """The first calendar day of each date's period (the day, its week from Monday, or its month)."""
    if period == "1w":
        return dates - pd.to_timedelta(dates.dt.weekday, unit="D")
    if period == "1M":
        return dates.dt.to_period("M").dt.start_time
    return dates


def group(days: pd.DataFrame, period: str) -> pd.DataFrame:
    """Daily rows (date, open, high, low, close, volume, complete) grouped into period candles, each timed at its
    first trading day."""
    cols = ["time", "key", "day", "open", "high", "low", "close", "volume", "complete"]
    if days.empty:
        return pd.DataFrame(columns=cols)
    d = days.assign(dt=pd.to_datetime(days["date"]))
    d["key"] = _period_start(d["dt"], period)
    out = d.groupby("key", sort=True).agg(key=("key", "first"), time=("dt", "first"), day=("date", "first"), open=("open", "first"),
                                          high=("high", "max"), low=("low", "min"), close=("close", "last"),
                                          volume=("volume", "sum"), complete=("complete", "all")).reset_index(drop=True)
    return out[cols]


class PeriodContext:
    """Bars and shared calculations for one symbol, replay day, period ("1d", "1w", "1M"), cursor and span."""

    period = True                # studies that need intraday bars check this (studies/base.py)

    def __init__(self, symbol: str, day: str, tf: str, cursor: int | None = None, span: int | None = None,
                 config: dict | None = None):
        self.symbol, self.day, self.tf = symbol.upper(), day, tf
        self.span = int(span or tfs.PERIODS[tf]["span"])
        self.config = config or {}
        self.daily = en.prior_context(self.symbol, day, lookback=ALL_HISTORY)
        today, self.last_minute, self.cursor, self.price = self._today(cursor)
        if today is None and self.daily.empty:
            raise ValueError(f"No cached bars for {self.symbol} on {day}")
        rows = self.daily.assign(complete=True)
        if today is not None:
            rows = pd.concat([rows, pd.DataFrame([today])], ignore_index=True)
        if self.price is None:
            self.price = float(rows["close"].iloc[-1])
        self.bars = self._frame(group(rows, tf))

    def _today(self, cursor):
        """The replay day's regular-hours candle so far (from its 1-minute bars, cut at the cursor), or its
        daily row when it has no 1-minute bars; also the last minute, the cursor and the latest price."""
        df = store.read_day(self.symbol, self.day)
        if df.empty:
            row = store.read_daily(self.symbol)
            row = row[row["date"] == self.day] if not row.empty else row
            if row.empty:
                return None, en.POST_END, en.POST_END, None
            r = row.iloc[-1]
            return ({"date": self.day, "open": float(r.open), "high": float(r.high), "low": float(r.low),
                     "close": float(r.close), "volume": float(r.volume), "complete": True},
                    en.POST_END, en.POST_END, float(r.close))
        m = en.minute_of_day(df["time"])
        last = int(m.iloc[-1]) + 1
        cur = last if cursor is None else max(en.PRE_START + 1, min(int(cursor), en.POST_END))
        cut = df[m < cur]
        price = float(cut["close"].iloc[-1]) if not cut.empty else None
        s = en.daily_summary(cut)                  # None before 09:30: no candle yet today
        if s is None:
            return None, last, cur, price
        return {"date": self.day, **s, "complete": cur >= en.RTH_END}, last, cur, price

    def _frame(self, g: pd.DataFrame) -> pd.DataFrame:
        """The columns the studies read on any chart: chart time, a regular-hours bucket, the day."""
        if g.empty:
            return g.assign(ct=pd.Series(dtype="int64"), bucket=pd.Series(dtype="int64"))
        g = g.copy()
        # a week or month that holds the replay day is still forming (a day is finished once 16:00 has passed)
        if self.tf != "1d":
            now = _period_start(pd.Series([pd.Timestamp(self.day)]), self.tf).iloc[0]
            g.loc[g["key"] == now, "complete"] = False
        g["ct"] = en.chart_times(g["time"])
        g["bucket"] = en.RTH_START
        return g.reset_index(drop=True)

    # -- what's drawn, and warm-up for indicators
    @cached_property
    def first_shown(self) -> int:
        start = pd.Timestamp(self.day) - pd.DateOffset(months=self.span)
        idx = self.bars.index[self.bars["time"] >= start]
        return int(idx[0]) if len(idx) else len(self.bars)

    @cached_property
    def shown(self) -> pd.DataFrame:
        return self.bars.iloc[self.first_shown:].assign(current=True).reset_index(drop=True)

    def warm(self, bars_needed: int) -> pd.DataFrame:
        lo = max(0, self.first_shown - int(bars_needed))
        return self.bars.iloc[lo:].assign(current=[i >= self.first_shown for i in range(lo, len(self.bars))]) \
            .reset_index(drop=True)

    points = en.DayContext.points

    # -- daily facts some studies use (prior days only, like the intraday context)
    @cached_property
    def atr_info(self):
        return en.atr_from_daily(self.daily)

    @property
    def atr(self):
        return self.atr_info[0]

    @property
    def pd_row(self):
        return self.daily.iloc[-1] if not self.daily.empty else None

    def future_times(self) -> list[int]:
        """Empty candles after the last one, at the start of each following day, week or month."""
        if self.bars.empty:
            return []
        last = pd.Timestamp(self.bars["key"].iloc[-1])
        if self.tf == "1d":
            nxt = pd.bdate_range(last + pd.Timedelta(days=1), periods=FUTURE_SLOTS)
        elif self.tf == "1w":
            nxt = [last + pd.Timedelta(weeks=k) for k in range(1, FUTURE_SLOTS + 1)]
        else:
            nxt = [last + pd.DateOffset(months=k) for k in range(1, FUTURE_SLOTS + 1)]
        return [int(t) for t in en.chart_times(pd.Series(pd.to_datetime(list(nxt))))]

def build_view(symbol: str, day: str, tf: str, cursor: int | None = None, studies: list[dict] | None = None,
               config: dict | None = None, span: int | None = None) -> dict:
    from . import studies as st  # local import: studies depend on the engine

    ctx = PeriodContext(symbol, day, tf, cursor, span, config)
    results = {}
    for s in studies or []:
        uid = str(s.get("uid") or s.get("type"))
        results[uid] = st.run_study(ctx, s.get("type", ""), s.get("params") or {})
    shown = ctx.shown
    return {
        "symbol": ctx.symbol, "day": day, "tf": tf, "period": True, "span": ctx.span,
        "tf_label": tfs.label(tf), "range_label": tfs.span_label(ctx.span), "step": tfs.PERIODS[tf]["seconds"],
        "days": 1, "shown_days": [day], "cursor": ctx.cursor, "cursor_label": en.fmt_min(ctx.cursor),
        "last_minute": ctx.last_minute, "price": ctx.price,
        "bars": [{"time": int(r.ct), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                  "volume": r.volume, "complete": bool(r.complete), "day": r.day, "session": "rth"}
                 for r in shown.itertuples()],
        "future": ctx.future_times(),
        "now_time": int(shown["ct"].iloc[-1]) if len(shown) else None,
        "studies": results,
        "context": {"atr": ctx.atr, "atr_days": ctx.atr_info[1], "prior_days": len(ctx.daily),
                    "prior_day": None if ctx.pd_row is None else ctx.pd_row["date"]},
    }
