"""Where the TWS collector gets earnings dates. Each source has the same shape:

    name                    shown on the earnings page ("SEC EDGAR (8-K Item 2.02)")
    lookup(symbol) -> dict  {"status": "ok", "earnings": [{"date", "time", ...}, ...]}  (US/Eastern dates and times)
                            or {"status": "not_found" | "error", "message": ...}

The collector writes the result to data/earnings/<SYMBOL>.json (app/earnings.py reads it). To add a source, add
a class here and choose it in make_source().

SEC EDGAR: US companies publish quarterly results with a form 8-K, Item 2.02 ("Results of Operations and Financial
Condition"), filed when the press release goes out. EDGAR records the acceptance time of every filing, which says
whether the report came before the open or after the close. Public data; the SEC asks every program to name a
contact in its requests (SEC_CONTACT in .env) and to stay under 10 requests a second. Only companies that file
with the SEC are covered; foreign companies filing 6-K reports (e.g. ASML) aren't.
"""
from __future__ import annotations

import json
import time
import urllib.request

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
TICKER_MAP_DAYS = 30
MIN_INTERVAL = 0.2                 # seconds between requests (the SEC allows 10 a second)
WANT = 8                           # Item 2.02 filings to look for: 6 reports, plus room for preliminary notices
MAX_OLDER_FILES = 4                # older filing lists to read for companies that file a lot


class SecEdgar:
    name = "SEC EDGAR (8-K Item 2.02)"

    def __init__(self, contact: str, cache_dir=None, fetch=None, clock=time.monotonic):
        self.agent = f"intraday-charts (personal, read-only) {contact}"
        self.cache_dir, self.clock, self.last = cache_dir, clock, 0.0
        self.fetch = fetch or self._http

    def _http(self, url: str) -> bytes:
        wait = MIN_INTERVAL - (self.clock() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = self.clock()
        req = urllib.request.Request(url, headers={"User-Agent": self.agent, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:          # noqa: S310  (fixed https URLs)
            return r.read()

    def _json(self, url: str):
        return json.loads(self.fetch(url))

    # ---------------------------------------------------------------- ticker -> company (CIK)
    def tickers(self) -> dict:
        cached = self.cache_dir / "_sec_tickers.json" if self.cache_dir else None
        if cached and cached.exists() and time.time() - cached.stat().st_mtime < TICKER_MAP_DAYS * 86400:
            return json.loads(cached.read_text())
        rows = self._json(TICKERS_URL)
        out = {str(r["ticker"]).upper(): int(r["cik_str"]) for r in rows.values()}
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(out))
        return out

    # ---------------------------------------------------------------- filings
    @staticmethod
    def earnings_filings(block: dict) -> list[dict]:
        """The 8-K filings with Item 2.02 in one block of EDGAR's parallel filing arrays. acceptanceDateTime reads
        like "2026-08-26T16:20:43.000Z"; the date and time are taken as US/Eastern (the SEC's clock)."""
        out = []
        forms, items, accepted = block.get("form", []), block.get("items", []), block.get("acceptanceDateTime", [])
        acc = block.get("accessionNumber", [""] * len(forms))
        for f, it, a, n in zip(forms, items, accepted, acc, strict=False):
            if f == "8-K" and "2.02" in str(it).split(",") and a:      # amendments (8-K/A) repeat a report
                out.append({"date": a[:10], "time": a[11:16], "form": f, "accession": n})
        return out

    def lookup(self, symbol: str) -> dict:
        try:
            cik = self.tickers().get(symbol.upper().replace(".", "-"))
            if cik is None:
                return {"status": "not_found", "message": f"{symbol} isn't on the SEC's list of companies. Only "
                        "companies that file with the SEC are covered (not funds' holdings or foreign 6-K filers)."}
            sub = self._json(SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"))
            found = self.earnings_filings(sub.get("filings", {}).get("recent", {}))
            for older in sub.get("filings", {}).get("files", [])[:MAX_OLDER_FILES]:
                if len(found) >= WANT:
                    break
                found += self.earnings_filings(self._json(SUBMISSIONS_URL.format(name=older["name"])))
            found.sort(key=lambda e: (e["date"], e["time"]), reverse=True)
            return {"status": "ok", "company": sub.get("name", ""), "cik": cik, "earnings": found[:WANT * 2]}
        except Exception as e:  # noqa: BLE001  (network, HTTP or format trouble: report it, keep collecting bars)
            return {"status": "error", "message": f"SEC EDGAR lookup failed: {e}"}


def make_source(contact: str | None, cache_dir=None):
    """The configured source, or None when earnings lookups are off (no SEC_CONTACT)."""
    return SecEdgar(contact, cache_dir) if contact else None
