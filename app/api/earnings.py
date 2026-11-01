"""The earnings view's data (app/earnings.py), and requests to the TWS collector for it."""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .. import control, earnings
from .common import one_symbol

router = APIRouter()

def earnings_lookups_on() -> bool:
    """The collector looks earnings dates up on SEC EDGAR only when SEC_CONTACT is set (.env)."""
    return bool(os.environ.get("SEC_CONTACT", "").strip())


class SymbolRequest(BaseModel):
    symbol: str


@router.get("/api/earnings")
def earnings_view(symbol: str, before: Annotated[int, Query(ge=1, le=earnings.MAX_DAYS)] = earnings.BEFORE,
                  after: Annotated[int, Query(ge=1, le=earnings.MAX_DAYS)] = earnings.AFTER):
    """The last earnings reports of a stock, each as % change around its reaction day (app/earnings.py), with
    `before` trading days before day 0 and `after` after."""
    v = earnings.view(one_symbol(symbol, demo_ok=True), before=before, after=after)
    v["lookups_on"] = earnings_lookups_on()
    if v["status"] == "missing" and "earnings dates" in v["missing"] and not v["lookups_on"]:
        v.update(status="off", message="Earnings-date lookups are off. Set SEC_CONTACT in .env (user guide, "
                 "\"Earnings view\") so the TWS collector can look them up on SEC EDGAR.")
    return v


@router.post("/api/earnings/request")
def earnings_request(req: SymbolRequest):
    """Ask the TWS collector for a stock's daily prices and (when lookups are on) its earnings dates."""
    sym = one_symbol(req.symbol)          # synthetic -DEMO symbols are never sent to the collector
    r = control.submit([sym], daily_only=True, earnings=earnings_lookups_on())
    return {"id": r["id"], "symbol": sym}
