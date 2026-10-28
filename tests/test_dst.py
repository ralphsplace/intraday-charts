"""The clocks change (2026-11-01 back to EST, 2027-03-14 forward to EDT): bars, chart times, multi-day charts
and headline times must all still read US/Eastern wall-clock. Bars here are INVENTED."""
from datetime import UTC, datetime

import pandas as pd
import pytest

import fetch_ibkr
import market_events as me
from app import engine, store

ET = "America/New_York"
BEFORE, AFTER = "2026-10-30", "2026-11-02"          # Friday in EDT (UTC-4), Monday in EST (UTC-5)
SPRING_BEFORE, SPRING_AFTER = "2027-03-12", "2027-03-15"


class Bar:
    def __init__(self, date, px):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, px, px + 1, px - 1, px, 100


def minutes_day(day, lo=240, hi=1200, px=100.0):
    t = [pd.Timestamp(day, tz=ET) + pd.Timedelta(minutes=m) for m in range(lo, hi)]
    return pd.DataFrame({"time": t, "open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 10.0})


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store._day_cache.clear()
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return tmp_path


@pytest.mark.parametrize("day,utc_open", [(BEFORE, 13), (AFTER, 14), (SPRING_BEFORE, 14), (SPRING_AFTER, 13)])
def test_tws_bars_land_on_the_eastern_open(day, utc_open):
    y, m, d = map(int, day.split("-"))
    df = fetch_ibkr.bars_to_frame([Bar(datetime(y, m, d, utc_open, 30, tzinfo=UTC), 1.0)])
    assert df["time"].iloc[0].strftime("%Y-%m-%d %H:%M") == f"{day} 09:30"


def test_chart_times_read_eastern_on_both_sides():
    for day in (BEFORE, AFTER, SPRING_BEFORE, SPRING_AFTER):
        t = engine.chart_time(pd.Timestamp(day, tz=ET) + pd.Timedelta(minutes=570))
        assert t % 86400 == 9 * 3600 + 30 * 60, day


def test_two_day_chart_across_the_change(cache):
    for d in (BEFORE, AFTER):
        store.write_day("QQQ", d, minutes_day(d))
    v = engine.build_view("QQQ", AFTER, tf=5, cursor=1200, days=2)   # whole day, so both days are complete
    assert v["shown_days"] == [BEFORE, AFTER]
    opens = [b for b in v["bars"] if b["session"] == "rth"]
    firsts = {b["day"]: b["time"] for b in reversed(opens)}          # first regular-hours bar of each day
    assert all(t % 86400 == 570 * 60 for t in firsts.values())
    assert len([b for b in v["bars"] if b["day"] == AFTER]) == len([b for b in v["bars"] if b["day"] == BEFORE])


def test_headline_times_convert_on_both_sides():
    class IB:
        def reqNewsProviders(self):
            return [type("P", (), {"code": "DJ-N", "name": "Dow Jones"})()]

        def qualifyContracts(self, c):
            c.conId = 1
            return [c]

        def reqHistoricalNews(self, *a):
            mk = lambda t, h, i: type("N", (), {"time": pd.Timestamp(t).to_pydatetime(), "headline": h,  # noqa: E731
                                                "providerCode": "DJ-N", "articleId": i})()
            return [mk("2026-11-02 14:35:00", "Invented: after the change", "b"),
                    mk("2026-10-30 13:35:00", "Invented: before the change", "a")]

        def sleep(self, s):
            pass

    n = me.News(IB(), symbols=["QQQ"], log=lambda *a: None)
    n.load("2026-10-01")
    assert [f"{it['time']:%Y-%m-%d %H:%M}" for it in n.items] == ["2026-10-30 09:35", "2026-11-02 09:35"]
