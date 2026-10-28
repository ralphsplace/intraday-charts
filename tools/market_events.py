"""Find QQQ's significant moves in the cached bars and match each to its likely cause.

    python tools/market_events.py                      # scheduled events only
    python tools/market_events.py --news               # also IBKR headlines (needs TWS; ~6 months of news)
    python tools/market_events.py --news --gdelt       # also GDELT news for moves the others don't explain
    docker compose run --rm collector python tools/market_events.py --news --client-id 20

What counts as a significant move (all settings below):
  - gap:    the 09:30 open is at least --gap-atr x ATR(14) away from the prior close
  - range:  the regular-session range is at least --range-atr x ATR(14)
  - burst:  a 15-minute move (07:00-16:00) at least --burst-mult x the median 15-minute move of the
            previous 20 days (default 6; at most --max-bursts per day, largest first)

Likely causes, in order:
  - scheduled events from app/data/market_calendar.json (Fed, CPI, jobs, GDP, PCE, big-holding earnings)
    plus monthly options expiration: a burst starting within -5 / +30 minutes of a release (Fed: +60),
    a gap after earnings the evening before or a release before the open, a range day with a release
  - IBKR headlines (--news): each symbol's headlines are read once (about 6 months back), then matched:
    15-minute move: 45 minutes before it to 15 minutes into it; gap: from the previous close to the open;
    range day: the session, closest to its biggest 15-minute move. Best first: just before the move, filed
    under QQQ or SPY, not press releases.
  - GDELT news (--gdelt) for moves still unexplained (needs internet from where this runs)

Writes:
  - data/events.json: the scheduled events and the moves (with their causes), drawn by the chart's
    Events study. Entries you added yourself are kept; this tool only replaces its own.
  - data/reports/significant_moves.csv and .html: one row per move. Moves with a scheduled cause have
    Type "Scheduled", the causes in Notes, and who publishes each one in Source. Moves without one but with
    headlines (--news, --gdelt) have Type "News", the best 2 headlines in Notes and their news feed in Source.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import envcheck, sessions, store  # noqa: E402

ET = "America/New_York"
SOURCE = "market_events"
CALENDAR = Path(__file__).resolve().parent.parent / "app" / "data" / "market_calendar.json"
# headlines are searched under these symbols: the ETFs, then QQQ's largest holdings
NEWS_SYMBOLS = ["QQQ", "SPY", "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "NFLX", "COST", "AMD"]
MARKET_SYMBOLS = {"QQQ", "SPY"}
WINDOW_AFTER = {"fed": 60}
OPEX_SOURCE = "Options Clearing Corporation (OCC) expiration calendar"


# ---------------------------------------------------------------- calendar
def third_fridays(start: str, end: str) -> list[dict]:
    out = []
    for m in pd.period_range(start[:7], end[:7], freq="M"):
        fridays = [d for d in pd.date_range(m.start_time, m.end_time) if d.weekday() == 4]
        d = fridays[2].strftime("%Y-%m-%d")
        if not sessions.is_trading_day(d):
            d = sessions.previous_session(d)
        quad = m.month in (3, 6, 9, 12)
        out.append({"date": d, "time": "16:00", "label": "Quad witching" if quad else "Monthly options expiration",
                    "category": "opex", "source": OPEX_SOURCE})
    return out


def load_calendar(start: str, end: str, path: Path | None = None) -> list[dict]:
    doc = json.loads(Path(path or CALENDAR).read_text())
    ev = [e for e in doc["events"] if start <= e["date"] <= end] + third_fridays(start, end)
    return sorted(ev, key=lambda e: (e["date"], e["time"]))


# ---------------------------------------------------------------- moves
def daily_table(symbol: str, days: list[str]) -> pd.DataFrame:
    rows = []
    for d in days:
        df = store.read_day(symbol, d)
        if df.empty:
            continue
        m = df["time"].dt.hour * 60 + df["time"].dt.minute
        rth = df[(m >= 570) & (m < 960)]
        if rth.empty:
            continue
        rows.append({"day": d, "open": float(rth["open"].iloc[0]), "high": float(rth["high"].max()),
                     "low": float(rth["low"].min()), "close": float(rth["close"].iloc[-1])})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["prev_close"] = t["close"].shift(1)
    tr = np.maximum(t["high"], t["prev_close"]) - np.minimum(t["low"], t["prev_close"])
    tr = tr.fillna(t["high"] - t["low"])
    t["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean().shift(1)     # ATR known before the day starts
    return t


def find_moves(symbol: str, days: list[str], gap_atr=0.75, range_atr=1.5, burst_mult=6.0, max_bursts=3):
    daily = daily_table(symbol, days)
    moves = []
    if daily.empty:
        return moves
    base_hist: list[np.ndarray] = []                   # each day's regular-hours 15-minute moves
    for _, r in daily.iterrows():
        d = r["day"]
        if pd.notna(r["atr"]) and pd.notna(r["prev_close"]):
            gap = r["open"] - r["prev_close"]
            if abs(gap) >= gap_atr * r["atr"]:
                moves.append({"day": d, "kind": "gap", "start": "09:30", "end": "09:30", "move": gap,
                              "pct": 100 * gap / r["prev_close"], "size_atr": abs(gap) / r["atr"]})
            rng = r["high"] - r["low"]
            if rng >= range_atr * r["atr"]:
                moves.append({"day": d, "kind": "range", "start": "09:30", "end": "16:00", "move": r["close"] - r["open"],
                              "pct": 100 * (r["close"] - r["open"]) / r["open"], "size_atr": rng / r["atr"]})
        # 15-minute bursts, 07:00-16:00, against the median of the previous 20 days
        df = store.read_day(symbol, d)
        m = df["time"].dt.hour * 60 + df["time"].dt.minute
        w = df[(m >= 420) & (m < 960)].reset_index(drop=True)
        if len(w) < 30:
            continue
        c = w["close"].to_numpy(float)
        o = w["open"].to_numpy(float)
        mins = (w["time"].dt.hour * 60 + w["time"].dt.minute).to_numpy()
        n = 15
        moves15 = np.array([c[min(i + n - 1, len(c) - 1)] - o[i] for i in range(len(c))])
        rth_abs = np.abs(moves15[(mins >= 570) & (mins <= 960 - n)])
        rth_i = np.where((mins >= 570) & (mins <= 960 - n))[0]
        for mv in moves:
            if mv["day"] == d and mv["kind"] == "range" and len(rth_i):
                k = rth_i[np.argmax(np.abs(moves15[rth_i]))]
                mv["focus"] = f"{mins[k] // 60:02d}:{mins[k] % 60:02d}"     # the day's biggest 15-minute move
        if len(base_hist) >= 5:                          # needs 5 prior days; uses up to 20
            base = float(np.median(np.concatenate(base_hist[-20:])))
            if base > 0:
                order = np.argsort(-np.abs(moves15))
                taken = []
                for i in order:
                    if abs(moves15[i]) < burst_mult * base or len(taken) >= max_bursts:
                        break
                    if any(abs(mins[i] - mins[j]) < n for j in taken):
                        continue
                    taken.append(i)
                    ref = o[i]
                    moves.append({"day": d, "kind": "burst", "start": f"{mins[i] // 60:02d}:{mins[i] % 60:02d}",
                                  "end": f"{(mins[i] + n) // 60:02d}:{(mins[i] + n) % 60:02d}", "move": moves15[i],
                                  "pct": 100 * moves15[i] / ref, "size_atr": abs(moves15[i]) / base})
        base_hist.append(rth_abs)
    return moves


# ---------------------------------------------------------------- causes
def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def scheduled_matches(move: dict, calendar: list[dict]) -> list[tuple[str, str]]:
    """(note, source) for each scheduled event that may explain the move; source = who publishes the event."""
    d = move["day"]
    out = []
    today = [e for e in calendar if e["date"] == d]
    prev = sessions.previous_session(d)
    src = lambda e: e.get("source", "")                                         # noqa: E731
    last_night = [(e["label"].replace(" (after close)", "") + " last night", src(e)) for e in calendar
                  if e["date"] == prev and e["category"] == "earnings"]
    if move["kind"] == "burst":
        t = _minutes(move["start"])
        for e in today:
            et = _minutes(e["time"])
            if et - 5 <= t <= et + WINDOW_AFTER.get(e["category"], 30) and e["category"] != "earnings":
                out.append((f"{e['label']} {e['time']}", src(e)))
        if t <= 600:                                          # first half hour: last night's earnings
            out += last_night
    elif move["kind"] == "gap":
        out += last_night
        out += [(f"{e['label']} {e['time']}", src(e)) for e in today
                if _minutes(e["time"]) < 570 and e["category"] != "earnings"]
        out += [(f"{e['label']} {e['time']} (prior day)", src(e)) for e in calendar
                if e["date"] == prev and e["category"] == "fed"]
    else:   # range day
        out += [(f"{e['label']} {e['time']}", src(e)) for e in today if e["category"] in ("fed", "macro", "opex")]
        out += last_night
    return list(dict.fromkeys(out))


def clean_headline(h: str) -> str:
    return re.sub(r"^\{[^}]*\}", "", str(h)).strip()


class News:
    """Headlines from TWS (reqHistoricalNews), downloaded once per symbol and then matched to moves locally.

    IBKR returns the newest headlines up to the end time (at most 300 per request) and keeps about 6 months of
    them; the start time doesn't limit the results, so each symbol's history is read page by page, walking the
    end time back. Times come back without a time zone; IBKR sends them in UTC (GMT).
    """

    def __init__(self, ib, symbols=NEWS_SYMBOLS, per_request=300, max_pages=40, pause=0.5, log=print):
        self.ib, self.per_request, self.max_pages, self.pause, self.log = ib, per_request, max_pages, pause, log
        from ib_async import Stock
        provs = ib.reqNewsProviders() or []
        self.names = {p.code: getattr(p, "name", p.code) for p in provs}
        self.providers = "+".join(self.names)
        self.ids = {}
        for sym in symbols:
            c = Stock(sym, "SMART", "USD")
            if ib.qualifyContracts(c):
                self.ids[sym] = c.conId
        self.items: list[dict] = []
        self.oldest = None

    def source(self, code: str) -> str:
        name = self.names.get(code)
        return f"{name} ({code})" if name and name != code else code

    def load(self, since: str) -> None:
        """Every headline for each symbol back to the day `since` (or as far as IBKR keeps them)."""
        if not self.providers:
            return
        stop = pd.Timestamp(since, tz=ET).tz_convert("UTC")
        by_id: dict[str, dict] = {}
        for sym, cid in self.ids.items():
            end, n_sym, pages = None, 0, 0
            while pages < self.max_pages:
                pages += 1
                end_s = "" if end is None else end.strftime("%Y-%m-%d %H:%M:%S.0")
                got = None
                for size in (self.per_request, max(self.per_request // 3, 1)):   # ib_async gives up after 4 s
                    try:
                        got = self.ib.reqHistoricalNews(cid, self.providers, "", end_s, size)
                    except Exception:  # noqa: BLE001
                        got = None
                    if got is not None:
                        break
                    self.ib.sleep(1)
                got = [] if got is None else got if isinstance(got, list) else [got]
                self.ib.sleep(self.pause)
                fresh, oldest = 0, None
                for it in got:
                    ts = pd.Timestamp(str(it.time))
                    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
                    oldest = ts if oldest is None or ts < oldest else oldest
                    key = getattr(it, "articleId", None) or f"{ts}{it.headline}"
                    h = clean_headline(it.headline)
                    if not h:
                        continue
                    if key in by_id:
                        if sym not in by_id[key]["symbols"]:
                            by_id[key]["symbols"].append(sym)
                        continue
                    by_id[key] = {"time": ts.tz_convert(ET), "headline": h, "provider": getattr(it, "providerCode", ""),
                                  "symbols": [sym]}
                    fresh += 1
                    n_sym += 1
                if not got or oldest is None or oldest <= stop or len(got) < size:
                    break
                # next page: older than this one; if nothing new came back (TWS may read the end time in its own
                # time zone), step back an hour at a time
                end = oldest - pd.Timedelta(seconds=1) if fresh else (end or oldest) - pd.Timedelta(hours=1)
            self.log(f"  {sym}: {n_sym} headlines")
        self.items = sorted(by_id.values(), key=lambda x: x["time"])
        self.oldest = self.items[0]["time"] if self.items else None

    def for_move(self, mv: dict, limit=5) -> list[dict]:
        """Headlines around a move, best first: just before it starts, from the market ETFs, not press releases."""
        day = pd.Timestamp(mv["day"], tz=ET)
        if mv["kind"] == "gap":           # overnight: from the previous close to just after the open
            t0 = pd.Timestamp(sessions.previous_session(mv["day"]), tz=ET) + pd.Timedelta(minutes=960)
            ref, t1 = day + pd.Timedelta(minutes=570), day + pd.Timedelta(minutes=575)
        elif mv["kind"] == "range":       # the session, centred on its biggest 15-minute move
            ref = day + pd.Timedelta(minutes=_minutes(mv.get("focus", "09:30")))
            t0, t1 = day + pd.Timedelta(minutes=420), day + pd.Timedelta(minutes=960)
        else:                             # a 15-minute move: 45 minutes before it to 15 minutes into it
            ref = day + pd.Timedelta(minutes=_minutes(mv["start"]))
            t0, t1 = ref - pd.Timedelta(minutes=45), ref + pd.Timedelta(minutes=15)
        out, seen = [], set()
        for it in self.items:
            if not (t0 <= it["time"] <= t1):
                continue
            base = re.sub(r"\s*-\d+-\s*$", "", it["headline"])     # "... -2-", "-3-": parts of one story
            if base.lower() in seen:
                continue
            seen.add(base.lower())
            before = (ref - it["time"]).total_seconds() / 60          # minutes before the move (negative = after)
            score = -abs(before) * (2 if before < 0 else 1)
            if mv["kind"] == "gap":
                score = -max(before, 0) / 30                           # overnight: the latest news counts most
            if MARKET_SYMBOLS & set(it["symbols"]):
                score += 20
            if base.lower().startswith("press release"):
                score -= 40
            out.append((score, {**it, "headline": base}))
        out.sort(key=lambda x: -x[0])
        return [it for _, it in out[:limit]]


def news_text(it: dict) -> str:
    """A headline for the report: its time, the text, and the symbols it was filed under."""
    syms = ",".join(it["symbols"])
    return f"{it['time']:%H:%M} {it['headline'].replace(';', ',')} [{syms}]"


def gdelt_headlines(day: str, start_min: int, before=60, after=30, limit=3, fetch=None) -> list[dict]:
    """Top headlines from the GDELT DOC API around a time (UTC window). Needs internet access."""
    import urllib.parse
    import urllib.request
    t0 = (pd.Timestamp(day, tz=ET) + pd.Timedelta(minutes=start_min - before)).tz_convert("UTC")
    t1 = (pd.Timestamp(day, tz=ET) + pd.Timedelta(minutes=start_min + after)).tz_convert("UTC")
    q = {"query": '("stock market" OR nasdaq OR "wall street" OR "federal reserve") sourcelang:english',
         "mode": "artlist", "format": "json", "maxrecords": "25", "sort": "hybridrel",
         "startdatetime": t0.strftime("%Y%m%d%H%M%S"), "enddatetime": t1.strftime("%Y%m%d%H%M%S")}
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(q)
    try:
        raw = fetch(url) if fetch else urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "replace")
        arts = json.loads(raw).get("articles", [])
    except Exception:  # noqa: BLE001
        return []
    out, seen = [], set()
    for a in arts:
        t = (a.get("title") or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        try:
            when = pd.Timestamp(a.get("seendate") or "", tz="UTC").tz_convert(ET)      # e.g. 20261015T143000Z
        except (ValueError, TypeError):
            when = pd.NaT
        if pd.isna(when):
            when = pd.Timestamp(day, tz=ET) + pd.Timedelta(minutes=start_min)
        out.append({"time": when, "headline": t, "provider": "GDELT", "symbols": ["GDELT"],
                    "source": f"GDELT ({a.get('domain') or 'web'})"})
    return out[:limit]


# ---------------------------------------------------------------- outputs
def write_events(moves: list[dict], calendar: list[dict], path: Path) -> int:
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = []
    keep = [e for e in old if isinstance(e, dict) and e.get("source") != SOURCE]
    new = [{"date": e["date"], "time": e["time"], "label": e["label"], "kind": "scheduled",
            "category": e.get("category", "other"), "source": SOURCE} for e in calendar]
    for mv in moves:
        if mv["causes"]:
            cause = "; ".join(mv["causes"][:2])
        elif mv.get("news"):
            cause = "news: " + mv["news"][0]["headline"][:70]
        else:
            cause = "no scheduled cause"
        what = {"gap": "Gap", "range": "Range day", "burst": "Move"}[mv["kind"]]
        if mv["kind"] == "range":
            continue                                          # a whole-day range has no single time to mark
        new.append({"date": mv["day"], "time": mv["start"], "kind": "move", "source": SOURCE,
                    "label": f"{what} {mv['pct']:+.2f}%: {cause}"})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep + new, indent=1))
    tmp.replace(path)
    return len(new)


REPORT_COLUMNS = ["day", "kind", "start", "end", "move_$", "move_%", "size", "Type", "Notes", "Source", "headlines"]
NEWS_IN_NOTES = 2     # headlines put in Notes for a move without a scheduled cause


def report_row(m: dict) -> dict:
    """One row of the moves report.
    Scheduled cause: Type "Scheduled", the causes in Notes, who publishes each one in Source.
    Otherwise, with headlines: Type "News", the best headlines in Notes (time, text, symbols), their news feed in
    Source. Notes and Source are in the same order, separated by "; ". All headlines found are in headlines."""
    causes = m.get("causes") or []
    news = m.get("news") or []
    typ, notes, srcs = "", [], []
    if causes:
        typ, notes = "Scheduled", causes
        srcs = [s or "unknown" for s in (m.get("sources") or [""] * len(causes))]
    elif news:
        typ, notes = "News", [news_text(n) for n in news[:NEWS_IN_NOTES]]
        srcs = [n.get("source", "") for n in news[:NEWS_IN_NOTES]]
    return {"day": m["day"], "kind": m["kind"], "start": m["start"], "end": m["end"], "move_$": round(m["move"], 2),
            "move_%": round(m["pct"], 2), "size": round(m["size_atr"], 2),
            "Type": typ, "Notes": "; ".join(notes), "Source": "; ".join(srcs),
            "headlines": " | ".join(m.get("headlines", []))}


def write_report(moves: list[dict], out_dir: Path, symbol: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [report_row(m) for m in moves]
    df = pd.DataFrame(rows, columns=REPORT_COLUMNS)
    csv = out_dir / "significant_moves.csv"
    df.to_csv(csv, index=False)
    explained = sum(1 for m in moves if m["causes"])
    by_news = sum(1 for m in moves if not m["causes"] and m.get("news"))
    shown = ("day", "kind", "start", "move_$", "move_%", "size", "Type", "Notes", "Source", "headlines")
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r[k]))}</td>" for k in shown) + "</tr>" for r in rows)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{symbol} significant moves</title>
<style>body{{font:13px system-ui;background:#0b0d10;color:#e3e6ea;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #262c35;padding:4px 6px;text-align:left;vertical-align:top}}th{{color:#8b939e}}
td:nth-child(5){{white-space:nowrap}}</style></head><body>
<h2>{symbol}: {len(moves)} significant moves, {explained} with a scheduled cause, {by_news} more with news</h2>
<p>size = gap or range in ATR(14) multiples; for 15-minute moves, multiples of the typical 15-minute move.
Source = who publishes each scheduled event, or the news feed of each headline, in Notes (same order).</p>
<table><tr><th>Day</th><th>Kind</th><th>Start</th><th>Move $</th><th>Move %</th><th>Size</th><th>Type</th><th>Notes</th>
<th>Source</th><th>Headlines</th></tr>{body}</table></body></html>"""
    page_path = out_dir / "significant_moves.html"
    page_path.write_text(page)
    return csv, page_path


def connect_tws(args):
    from ib_async import IB
    envcheck.require_local_tws(args.host)        # TWS must be on this machine or the home network
    ib = IB()
    ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=30)
    return ib


def run(args, ib=None, gdelt_fetch=None) -> list[dict]:
    sym = args.symbol.upper()
    days = [d for d in store.list_days(sym) if (not args.start or d >= args.start) and (not args.end or d <= args.end)]
    if not days:
        raise SystemExit(f"No cached {sym} bars. Fetch them first (collector --days N).")
    last = days[-1]
    if args.upcoming:   # also mark the next 60 days' scheduled events, so they show on live charts
        last = (max(pd.Timestamp(days[-1]), pd.Timestamp(sessions.today())) + pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    cal = load_calendar(days[0], last)
    moves = find_moves(sym, days, args.gap_atr, args.range_atr, args.burst_mult, args.max_bursts)
    for mv in moves:
        found = scheduled_matches(mv, cal)
        mv["causes"], mv["sources"] = [n for n, _ in found], [src for _, src in found]
    news = None
    if args.news:
        ib = ib or connect_tws(args)
        news = News(ib)
        print(f"News feeds: {news.providers or 'none'}; reading headlines for {', '.join(news.ids)}")
        news.load(days[0])
        if news.oldest is not None:
            print(f"  {len(news.items)} headlines, back to {news.oldest:%Y-%m-%d} (IBKR keeps about 6 months)")
    for mv in moves:
        mv["news"] = []
        if news is not None:
            mv["news"] = [{**it, "source": news.source(it["provider"])} for it in news.for_move(mv)]
        if args.gdelt and not mv["causes"] and not mv["news"]:
            t = _minutes(mv.get("focus") or mv["start"])
            mv["news"] = gdelt_headlines(mv["day"], t, fetch=gdelt_fetch)
            time.sleep(1 if gdelt_fetch is None else 0)
        mv["headlines"] = [news_text(n) for n in mv["news"]]
    moves.sort(key=lambda m: (m["day"], m["start"]))
    n_ev = write_events(moves, cal, store.DATA_DIR / "events.json")
    csv, page = write_report(moves, store.DATA_DIR / "reports", sym)
    explained = sum(1 for m in moves if m["causes"])
    with_news = sum(1 for m in moves if m.get("headlines"))
    print(f"{sym}: {len(days)} days, {len(moves)} significant moves "
          f"({sum(m['kind'] == 'gap' for m in moves)} gaps, {sum(m['kind'] == 'range' for m in moves)} range days, "
          f"{sum(m['kind'] == 'burst' for m in moves)} 15-minute moves)")
    print(f"  {explained} with a scheduled cause, {sum(1 for m in moves if not m['causes'] and m['news'])} more "
          f"explained by news (Type News), {sum(1 for m in moves if not m['causes'] and not m['news'])} unexplained; "
          f"{with_news} with headlines in all")
    print(f"  {n_ev} entries written to {store.DATA_DIR / 'events.json'} (your own entries kept)")
    print(f"  report: {csv} and {page}")
    return moves


def main(argv=None):
    import os
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", default="QQQ")
    p.add_argument("--start"), p.add_argument("--end")
    p.add_argument("--gap-atr", type=float, default=0.75, help="gap size in ATR(14) multiples (default 0.75)")
    p.add_argument("--range-atr", type=float, default=1.5, help="day range in ATR(14) multiples (default 1.5)")
    p.add_argument("--burst-mult", type=float, default=6.0,
                   help="15-minute move vs the median 15-minute move of the prior 20 days (default 6)")
    p.add_argument("--max-bursts", type=int, default=3, help="largest 15-minute moves kept per day (default 3)")
    p.add_argument("--no-upcoming", dest="upcoming", action="store_false",
                   help="don't add the next 60 days' scheduled events to the charts")
    p.add_argument("--news", action="store_true", help="add IBKR headlines (needs TWS)")
    p.add_argument("--gdelt", action="store_true", help="add GDELT headlines for moves still unexplained")
    p.add_argument("--host", default=os.environ.get("IB_HOST", "host.docker.internal"))
    p.add_argument("--port", type=int, default=int(os.environ.get("IB_PORT", "7496")))
    p.add_argument("--client-id", type=int, default=20)
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR"))
    args = p.parse_args(argv)
    if args.data_dir:
        store.DATA_DIR = Path(args.data_dir)
    return run(args)


if __name__ == "__main__":
    main()
