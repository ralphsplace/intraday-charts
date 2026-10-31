"""Where the TWS collector fetches watch lists from outside sources (app/list_sources.py checks and stores them).

Each fetcher has the same shape:
    name                    shown in the collector's log
    load(ref) -> dict       {"status": "ok", "symbols": [...], "total": n}  or  {"status": "error", "message": ...}

FinViz: an Elite subscription exports any screen (export.ashx) or portfolio (portfolio_export.ashx) as CSV, signed
in with the API token from your FinViz account settings (FINVIZ_TOKEN in .env, sent only to finviz.com). The
address is rebuilt from the checked reference; the token is never logged or written to the data folder.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import list_sources, watchlist  # noqa: E402

MIN_INTERVAL = 1.0           # seconds between requests to FinViz


class FinVizExport:
    name = "FinViz Elite export"
    base = "https://elite.finviz.com/"

    def __init__(self, token: str, fetch=None, clock=time.monotonic):
        self.token, self.clock, self.last = token.strip(), clock, -MIN_INTERVAL
        self.fetch = fetch or self._http

    def url(self, ref: dict) -> str:
        page = "portfolio_export.ashx" if ref["kind"] == "portfolio" else "export.ashx"
        return f"{self.base}{page}?{ref['query']}&auth={self.token}"

    def _http(self, url: str) -> bytes:
        wait = MIN_INTERVAL - (self.clock() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = self.clock()
        req = urllib.request.Request(url, headers={"User-Agent": "intraday-charts (personal, read-only)"})
        with urllib.request.urlopen(req, timeout=30) as r:          # noqa: S310  (rebuilt https URL, finviz.com only)
            return r.read(5_000_000)

    def load(self, ref: dict) -> dict:
        if not list_sources.valid(ref) or ref["source"] != "finviz":
            return {"status": "error", "message": "Not a FinViz screen or portfolio"}
        try:
            body = self.fetch(self.url(ref)).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            why = ("FinViz refused the token: check FINVIZ_TOKEN (exports need FinViz Elite)" if e.code in (401, 403)
                   else "FinViz is limiting requests: try again in a minute" if e.code == 429
                   else f"FinViz answered {e.code}")
            return {"status": "error", "message": why}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"status": "error", "message": f"Couldn't reach FinViz: {getattr(e, 'reason', e)}"}
        head = body.lstrip()[:200].lower()
        if head.startswith(("<!doctype", "<html")):
            return {"status": "error", "message": "FinViz sent a web page instead of a list: check FINVIZ_TOKEN "
                                                  "(exports need FinViz Elite)"}
        first = body.lstrip("\ufeff").split("\n", 1)[0]
        if "ticker" not in first.lower():
            return {"status": "error", "message": "FinViz's answer has no Ticker column"}
        got = watchlist.parse_symbols(body)
        syms = got["symbols"]
        return {"status": "ok", "symbols": syms[:list_sources.MAX_SYMBOLS], "total": len(syms),
                "skipped": got["skipped"][:50]}


def make_fetchers(finviz_token: str | None) -> dict:
    """The fetchers turned on in .env, by source name."""
    return {"finviz": FinVizExport(finviz_token)} if (finviz_token or "").strip() else {}
