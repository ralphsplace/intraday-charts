"""What the API modules share: the deployment config file, and checking the symbols, dates and expiries a
request carries (each fails with a 400 that says what was wrong)."""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from fastapi import HTTPException

from .. import control, watch_fields


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT.parent / "config.json"
DEMO_RE = re.compile(r"^[A-Z]{1,6}-DEMO$")      # synthetic test data (tests/synthetic.py)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXPIRY_RE = re.compile(r"^\d{8}$")


def config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def clean_symbols(raw: list[str]) -> list[str]:
    out, bad = [], []
    for s in raw:
        c = control.clean_symbol(s)
        (out if c else bad).append(c or s)
    if bad:
        raise HTTPException(400, "Not a stock or ETF symbol: " + ", ".join(bad))
    if not out:
        raise HTTPException(400, "No symbols given")
    if len(out) > 60:
        raise HTTPException(400, "At most 60 symbols per request")
    return list(dict.fromkeys(out))


def watch_cols(cols: str) -> list[str]:
    return [c for c in (cols or "").split(",")[:80] if c in watch_fields.BY_ID]


def one_symbol(raw: str, demo_ok: bool = False) -> str:
    sym = control.clean_symbol(raw)
    if not sym and demo_ok and DEMO_RE.match((raw or "").strip().upper()):
        sym = raw.strip().upper()
    if not sym:
        raise HTTPException(400, f"Not a stock symbol: {raw}")
    return sym


def valid_date(raw: str) -> str:
    if not DATE_RE.match(raw or ""):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, "date must be a real date") from None
    return raw


def valid_expiry(raw: str) -> str:
    if not EXPIRY_RE.match(raw or ""):
        raise HTTPException(400, "expiry must be YYYYMMDD")
    valid_date(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return raw
