"""The expected-move view's data (app/expected_move.py), and requests for fresh option quotes (read-only
snapshots)."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import control, expected_move
from .common import DEMO_RE, one_symbol, valid_date

router = APIRouter()

MAX_EM_SYMBOLS = 20


def _em_symbols(raw: str, demo_ok: bool = False) -> list[str]:
    parts = [x for x in re.split(r"[\s,;]+", raw or "") if x]
    if not parts:
        raise HTTPException(400, "Type at least one symbol")
    if len(parts) > MAX_EM_SYMBOLS:
        raise HTTPException(400, f"At most {MAX_EM_SYMBOLS} symbols at a time")
    return list(dict.fromkeys(one_symbol(x, demo_ok=demo_ok) for x in parts))


class ExpectedMoveRequest(BaseModel):
    symbols: str
    date: str


@router.get("/api/expected-move")
def expected_move_view(symbols: str, date: str):
    """Each symbol's expected move by the first expiry on or after `date`, from cached option quotes
    (app/expected_move.py)."""
    d = valid_date(date)
    return {"date": d, "stale_seconds": expected_move.STALE_SECONDS,
            "items": [expected_move.view(s, d) for s in _em_symbols(symbols, demo_ok=True)]}


@router.post("/api/expected-move/request")
def expected_move_request(req: ExpectedMoveRequest):
    """Ask the TWS collector for fresh option quotes (snapshots, read-only)."""
    syms = [s for s in _em_symbols(req.symbols, demo_ok=True) if not DEMO_RE.match(s)]   # synthetic: never fetched
    if not syms:
        raise HTTPException(400, "Synthetic -DEMO symbols are never fetched")
    r = control.submit(syms, options_for=valid_date(req.date))
    return {"id": r["id"], "symbols": syms}
