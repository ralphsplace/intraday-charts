"""tools/market_events.py on INVENTED bars with scripted moves and an invented calendar and news feed."""
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import market_events as me
from app import sessions, store

ET = "America/New_York"


def quiet_day(day, start_px, rng, jumps=()):
    """1-minute bars 07:00-16:00 with small noise; jumps = [(minute_of_day, dollars)] added at that minute."""
    mins = np.arange(420, 960)
    steps = rng.normal(0, 1, len(mins)) * np.where(mins < 570, 0.01, 0.03)   # quieter before the open
    for m, j in jumps:
        steps[mins == m] += j
    closes = start_px + np.cumsum(steps)
    opens = np.r_[start_px, closes[:-1]]
    d0 = pd.Timestamp(day, tz=ET)
    return pd.DataFrame({"time": [d0 + pd.Timedelta(minutes=int(m)) for m in mins], "open": opens.round(2),
                         "high": (np.maximum(opens, closes) + 0.02).round(2),
                         "low": (np.minimum(opens, closes) - 0.02).round(2), "close": closes.round(2),
                         "volume": np.full(len(mins), 1000.0)})


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    days = []
    d = "2026-08-03"
    while len(days) < 30:
        if sessions.is_trading_day(d):
            days.append(d)
        d = (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cpi_day, gap_day, odd_day = days[22], days[25], days[27]
    rng = np.random.default_rng(1)
    px = 500.0
    for day in days:
        jumps = []
        if day == cpi_day:
            jumps = [(510, 4.0)]                       # 08:30 jump
        if day == gap_day:
            jumps = [(569, -9.0)]                      # gap down into the open
        if day == odd_day:
            jumps = [(780, 3.5)]                       # 13:00, nothing scheduled
        df = quiet_day(day, px, rng, jumps)
        store.write_day("QQQ", day, df)
        px = float(df["close"].iloc[-1])
    cal = tmp_path / "calendar.json"
    cal.write_text(json.dumps({"events": [
        {"date": cpi_day, "time": "08:30", "label": "CPI (Jul)", "category": "macro", "source": "BLS (test)"},
        {"date": days[24], "time": "16:05", "label": "NVDA earnings (after close)", "category": "earnings",
         "source": "NVIDIA (NVDA)"},
        {"date": days[26], "time": "14:00", "label": "FOMC decision", "category": "fed"}]}))
    monkeypatch.setattr(me, "CALENDAR", cal)
    (tmp_path / "events.json").write_text(json.dumps([
        {"date": days[1], "time": "10:00", "label": "my own note", "kind": "headline"},
        {"date": days[1], "time": "11:00", "label": "old generated", "kind": "move", "source": me.SOURCE}]))
    return SimpleNamespace(days=days, cpi_day=cpi_day, gap_day=gap_day, odd_day=odd_day, dir=tmp_path)


def args(**kw):
    a = dict(symbol="QQQ", start=None, end=None, gap_atr=0.75, range_atr=1.5, burst_mult=6.0, max_bursts=3,
             upcoming=False, news=False, gdelt=False, host="x", port=0, client_id=1)
    a.update(kw)
    return SimpleNamespace(**a)


def test_third_fridays_and_quad_witching():
    ev = me.third_fridays("2026-01-01", "2026-06-30")
    assert [e["date"] for e in ev] == ["2026-01-16", "2026-02-20", "2026-03-20", "2026-04-17", "2026-05-15",
                                       "2026-06-18"]   # 2026-06-19 is Juneteenth, so Thursday
    assert ev[2]["label"] == "Quad witching" and ev[0]["label"] == "Monthly options expiration"
    assert all(e["source"] == me.OPEX_SOURCE for e in ev)


def test_real_calendar_file_is_well_formed():
    doc = json.loads(me.CALENDAR.read_text())
    for e in doc["events"]:
        assert set(e) >= {"date", "time", "label", "category", "source"} and e["source"]
        assert e["category"] in ("fed", "macro", "earnings")
        pd.Timestamp(e["date"]), me._minutes(e["time"])


def test_moves_found_and_matched(world):
    moves = me.run(args())
    by = {(m["day"], m["kind"]): m for m in moves}
    cpi = [m for m in moves if m["day"] == world.cpi_day and m["kind"] == "burst"]
    assert cpi and cpi[0]["start"] <= "08:30" <= cpi[0]["end"] and "CPI (Jul) 08:30" in cpi[0]["causes"]
    gap = by[(world.gap_day, "gap")]
    assert gap["move"] < 0 and gap["causes"] == ["NVDA earnings last night"]
    odd = [m for m in moves if m["day"] == world.odd_day and m["kind"] == "burst"]
    assert odd and odd[0]["start"] <= "13:00" and odd[0]["causes"] == []
    # nothing flagged on the quiet days before the scripted ones
    assert not [m for m in moves if m["day"] < world.cpi_day and m["kind"] != "range"]


def test_events_file_keeps_user_entries_and_replaces_own(world):
    me.run(args())
    ev = json.loads((world.dir / "events.json").read_text())
    assert {"date": world.days[1], "time": "10:00", "label": "my own note", "kind": "headline"} in ev
    assert not [e for e in ev if e["label"] == "old generated"]
    moves = [e for e in ev if e["kind"] == "move"]
    assert any(e["date"] == world.cpi_day and "CPI" in e["label"] for e in moves)
    assert any(e["date"] == world.odd_day and "no scheduled cause" in e["label"] for e in moves)
    assert any(e["kind"] == "scheduled" and e["label"] == "FOMC decision" for e in ev)
    me.run(args())                                     # running again doesn't duplicate
    assert json.loads((world.dir / "events.json").read_text()) == ev


def test_report_written(world):
    me.run(args())
    df = pd.read_csv(world.dir / "reports" / "significant_moves.csv")
    assert list(df.columns) == me.REPORT_COLUMNS and "scheduled_cause" not in df.columns
    cpi = df[(df["day"] == world.cpi_day) & (df["kind"] == "burst")].iloc[0]
    assert cpi["Type"] == "Scheduled" and cpi["Notes"] == "CPI (Jul) 08:30" and cpi["Source"] == "BLS (test)"
    gap = df[(df["day"] == world.gap_day) & (df["kind"] == "gap")].iloc[0]
    assert gap["Notes"] == "NVDA earnings last night" and gap["Source"] == "NVIDIA (NVDA)"
    odd = df[(df["day"] == world.odd_day) & (df["kind"] == "burst")].iloc[0]
    assert pd.isna(odd["Type"]) and pd.isna(odd["Notes"]) and pd.isna(odd["Source"])
    assert "significant moves" in (world.dir / "reports" / "significant_moves.html").read_text()


class FakeNewsIB:
    """Invented headlines, as TWS returns them: per contract, newest first, up to the end time ("" = now),
    at most n; times in UTC without a time zone. The start time is ignored, as IBKR does."""
    NAMES = {"BRFG": "Briefing.com General Market Columns", "DJ-N": "Dow Jones Global Equity Trader"}

    def __init__(self, items):
        self.items, self.calls, self.ids = items, [], {}      # items: (symbol, utc time, headline, provider, id)

    def reqNewsProviders(self):
        return [SimpleNamespace(code=c, name=n) for c, n in self.NAMES.items()]

    def qualifyContracts(self, c):
        c.conId = self.ids.setdefault(c.symbol, len(self.ids) + 1)
        return [c]

    def reqHistoricalNews(self, con_id, providers, start, end, n):
        self.calls.append((con_id, providers, end))
        sym = next(s for s, i in self.ids.items() if i == con_id)
        e = pd.Timestamp(end[:19]) if end else pd.Timestamp("2100-01-01")
        got = [it for it in self.items if it[0] == sym and pd.Timestamp(it[1]) <= e]
        got.sort(key=lambda it: it[1], reverse=True)
        return [SimpleNamespace(time=pd.Timestamp(tm).to_pydatetime(), headline=h, providerCode=p, articleId=a)
                for _, tm, h, p, a in got[:n]]

    def sleep(self, s):
        pass


def utc(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz=ET).tz_convert("UTC").tz_localize(None).strftime("%Y-%m-%d %H:%M:%S")


def test_news_fills_type_notes_and_source(world):
    prev = sessions.previous_session(world.gap_day)
    ib = FakeNewsIB([
        ("QQQ", utc(world.odd_day, "12:50"), "{A:800015:L:en}Invented: chip export rule eased", "DJ-N", "a1"),
        ("NVDA", utc(world.odd_day, "12:50"), "{A:800015:L:en}Invented: chip export rule eased", "DJ-N", "a1"),
        ("NVDA", utc(world.odd_day, "12:58"), "Invented: NVDA supplier note", "BRFG", "a2"),
        ("QQQ", utc(world.odd_day, "09:00"), "Invented: too early", "DJ-N", "a3"),
        ("NVDA", utc(prev, "16:40"), "Invented: NVDA guidance below estimates", "DJ-N", "a4"),
    ])
    moves = me.run(args(news=True), ib=ib)
    odd = [m for m in moves if m["day"] == world.odd_day and m["kind"] == "burst"][0]
    assert odd["headlines"][0] == "12:50 Invented: chip export rule eased [QQQ,NVDA]"   # filed under QQQ: first
    assert not any("too early" in h for m in moves for h in m["headlines"] if m["kind"] == "burst")   # 4 hours before
    assert ib.calls and ib.calls[0][1] == "BRFG+DJ-N"
    df = pd.read_csv(world.dir / "reports" / "significant_moves.csv")
    row = df[(df["day"] == world.odd_day) & (df["kind"] == "burst")].iloc[0]
    assert row["Type"] == "News"
    assert row["Notes"] == "12:50 Invented: chip export rule eased [QQQ,NVDA]; 12:58 Invented: NVDA supplier note [NVDA]"
    assert row["Source"] == "Dow Jones Global Equity Trader (DJ-N); Briefing.com General Market Columns (BRFG)"
    gap = df[(df["day"] == world.gap_day) & (df["kind"] == "gap")].iloc[0]
    assert gap["Type"] == "Scheduled" and "NVDA guidance below estimates" in gap["headlines"]   # scheduled stays first
    ev = json.loads((world.dir / "events.json").read_text())
    assert any(e["kind"] == "move" and "news: Invented: chip export rule eased" in e["label"] for e in ev)


def test_news_reads_every_page_back_to_the_first_day():
    items = [("QQQ", f"2026-10-{d:02d} 14:00:00", f"Invented story {d}", "DJ-N", f"id{d}") for d in range(1, 15)]
    ib = FakeNewsIB(items)
    news = me.News(ib, symbols=["QQQ"], per_request=3, log=lambda *a: None)
    news.load("2026-10-05")
    got = {it["headline"] for it in news.items}
    assert {f"Invented story {d}" for d in range(5, 15)} <= got                  # all the way back to the 5th
    assert len(ib.calls) <= 5 and len(ib.calls) >= 4                             # 3 per page, stops once past it
    assert news.items[0]["time"].tz is not None and str(news.items[-1]["time"].tz) == ET


def test_news_ranking_for_gaps_and_range_days():
    ib = FakeNewsIB([
        ("NVDA", utc("2026-10-14", "17:00"), "Invented: early evening story", "DJ-N", "g1"),
        ("NVDA", utc("2026-10-15", "07:15"), "Invented: premarket story", "DJ-N", "g2"),
        ("NVDA", utc("2026-10-15", "10:00"), "Invented: after the open", "DJ-N", "g3"),
        ("NVDA", utc("2026-10-16", "09:40"), "Invented: morning item", "DJ-N", "r1"),
        ("NVDA", utc("2026-10-16", "10:58"), "Press Release: Invented product", "DJ-N", "r2"),
        ("NVDA", utc("2026-10-16", "10:59"), "Invented: tariff headline -2-", "DJ-N", "r3"),
        ("NVDA", utc("2026-10-16", "10:59"), "Invented: tariff headline -3-", "DJ-N", "r4"),
    ])
    news = me.News(ib, symbols=["NVDA"], log=lambda *a: None)
    news.load("2026-10-01")
    gap = news.for_move({"day": "2026-10-15", "kind": "gap", "start": "09:30"})
    assert [g["headline"] for g in gap] == ["Invented: premarket story", "Invented: early evening story"]
    rng = news.for_move({"day": "2026-10-16", "kind": "range", "start": "09:30", "focus": "11:00"})
    # the two parts of one story count once; a press release counts as if 40 minutes further away
    assert [r["headline"] for r in rng] == ["Invented: tariff headline", "Press Release: Invented product",
                                            "Invented: morning item"]


def test_gdelt_only_for_unexplained_moves(world):
    urls = []

    def fetch(url):
        urls.append(url)
        return json.dumps({"articles": [{"title": "Invented GDELT story", "domain": "example.com"}]})

    moves = me.run(args(gdelt=True), gdelt_fetch=fetch)
    odd = [m for m in moves if m["day"] == world.odd_day and m["kind"] == "burst"][0]
    assert len(odd["headlines"]) == 1 and odd["headlines"][0].endswith("Invented GDELT story [GDELT]")
    cpi = [m for m in moves if m["day"] == world.cpi_day and m["kind"] == "burst"][0]
    assert cpi["headlines"] == []
    assert urls and all("api.gdeltproject.org" in u for u in urls)
    df = pd.read_csv(world.dir / "reports" / "significant_moves.csv")
    row = df[(df["day"] == world.odd_day) & (df["kind"] == "burst")].iloc[0]
    assert row["Type"] == "News" and row["Source"] == "GDELT (example.com)"


def test_events_study_draws_moves(world):
    from app import engine as en, studies
    me.run(args())
    ctx = en.DayContext("QQQ", world.odd_day, tf=1, events_path=world.dir / "events.json")
    out = studies.run_study(ctx, "events", {})
    kinds = {v["kind"] for v in out["verticals"]}
    assert "move" in kinds
    off = studies.run_study(ctx, "events", {"moves": False})
    assert "move" not in {v["kind"] for v in off["verticals"]}


def test_news_retries_a_timed_out_page_smaller():
    class Slow(FakeNewsIB):
        def reqHistoricalNews(self, con_id, providers, start, end, n):
            if n > 100:
                self.calls.append(("timeout", n))
                return None                                   # ib_async's answer when TWS takes over 4 s
            return super().reqHistoricalNews(con_id, providers, start, end, n)
    ib = Slow([("QQQ", "2026-10-14 14:00:00", "Invented: still found", "DJ-N", "x1")])
    news = me.News(ib, symbols=["QQQ"], log=lambda *a: None)
    news.load("2026-10-01")
    assert [it["headline"] for it in news.items] == ["Invented: still found"] and ("timeout", 300) in ib.calls
