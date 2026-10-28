"""Pull ticker symbols out of pasted text or an exported watchlist file.

Accepts plain lists ("QQQ, spy nvda"), CSV exports with a Symbol or Ticker column (thinkorswim, FinViz,
most brokers), and TWS watchlist exports (lines like "DES,AAPL,STK,SMART"). Futures (/ES), indexes
($SPX) and option symbols are skipped: the dashboard charts stocks and ETFs.
"""
from __future__ import annotations

import csv
import io
import re

from .control import clean_symbol

_TOKEN = re.compile(r"[A-Za-z$/.][A-Za-z0-9./_-]*")


def _add(sym: str, out: list, skipped: list) -> None:
    raw = sym.strip().strip('"').strip()
    if not raw:
        return
    s = clean_symbol(raw)
    if s:
        if s not in out:
            out.append(s)
    elif raw not in skipped:
        skipped.append(raw)


def parse_symbols(text: str) -> dict:
    text = (text or "").replace("﻿", "")
    out: list[str] = []
    skipped: list[str] = []
    lines = [ln for ln in text.splitlines() if ln.strip()]

    # TWS export: DES,<symbol>,<secType>,<exchange>...
    des = [ln.split(",") for ln in lines if ln.upper().startswith("DES,")]
    if des:
        for f in des:
            if len(f) > 2 and f[2].strip().upper() in ("STK", "ETF", ""):
                _add(f[1], out, skipped)
            elif len(f) > 1:
                skipped.append(f[1].strip())
        return {"symbols": out, "skipped": skipped}

    # CSV with a header row naming the symbol column (it may follow a few preamble lines)
    for i, ln in enumerate(lines[:20]):
        cells = [c.strip().strip('"').lower() for c in next(csv.reader([ln]))]
        col = next((cells.index(k) for k in ("symbol", "ticker") if k in cells), None)
        if col is not None and len(cells) > 1:
            for row in csv.reader(io.StringIO("\n".join(lines[i + 1:]))):
                if len(row) > col:
                    _add(row[col], out, skipped)
            return {"symbols": out, "skipped": skipped}

    # anything else: a list of words
    for tok in _TOKEN.findall(text):
        _add(tok, out, skipped)
    return {"symbols": out, "skipped": skipped}
