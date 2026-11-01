"""The watch list's data: rows and columns, study values by name, the Holdings positions, pasted symbols,
FinViz sources, and the named watch lists themselves (app/watchlists.py)."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import control, list_sources, positions, saved, study_values, watch_fields, watchlist, watchlists
from .common import one_symbol, valid_date, watch_cols

router = APIRouter()


class SymbolsText(BaseModel):
    text: str


MAX_QUOTE_SYMBOLS = 100


@router.get("/api/quotes")
def quote_rows(symbols: str, day: str, cursor: int | None = Query(None, ge=0, le=24 * 60), cols: str = ""):
    """Watch list rows from the cached 1-minute bars of `day` (up to the Replay cursor, when given), with the
    values of the columns asked for (app/watch_fields.py)."""
    parts = [x for x in re.split(r"[\s,;]+", symbols or "") if x]
    if len(parts) > MAX_QUOTE_SYMBOLS:
        raise HTTPException(400, f"At most {MAX_QUOTE_SYMBOLS} symbols")
    syms = list(dict.fromkeys(one_symbol(x, demo_ok=True) for x in parts))
    return {"day": valid_date(day), "items": watch_fields.rows(syms, day, cursor, watch_cols(cols))}


@router.get("/api/watch/columns")
def watch_columns():
    """The columns a watch list can show (app/watch_fields.py), and each list kind's default set."""
    return watch_fields.catalog()


@router.get("/api/study-value")
def study_value(symbol: str, day: str, type: str, output: str = "", tf: int = 1, params: str = "{}",
                cursor: int | None = Query(None, ge=0, le=24 * 60)):
    """One study's line or level at the cursor (app/study_values.py), e.g. type=vwap&output=vwap, or
    type=sma&params={"length":50}&tf=5&output=sma."""
    try:
        p = json.loads(params or "{}")
        if not isinstance(p, dict):
            raise ValueError("params must be an object")
        return {"symbol": one_symbol(symbol, demo_ok=True), "day": valid_date(day),
                **study_values.value(symbol, day, {"type": type, "params": p, "output": output or type, "tf": tf}, cursor)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/api/positions")
def position_rows(day: str, cursor: int | None = Query(None, ge=0, le=24 * 60), cols: str = ""):
    """The watch list's Holdings list: the account's stock and ETF positions (read by the collector when
    HOLDINGS=on) with market value and P/L at the price of `day` (up to the Replay cursor, when given)."""
    return {"day": valid_date(day), **positions.view(day, cursor, watch_cols(cols))}


@router.post("/api/symbols/parse")
def parse_symbols(req: SymbolsText):
    return watchlist.parse_symbols(req.text[:200_000])


class ListSourceRequest(BaseModel):
    source: str = Field(max_length=20)
    address: str = Field(max_length=4000)
    refresh: bool = False          # fetch again now
    ask: bool = True               # ask the collector when missing or stale (False: just read, while waiting)


@router.post("/api/lists/source")
def list_source(req: ListSourceRequest):
    """A watch list from an outside source (a FinViz screen or portfolio): the symbols fetched for it, and a
    request to the collector when there are none yet, they're older than the source's limit, or on refresh."""
    try:
        ref = list_sources.normalize(req.source, req.address)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    v = list_sources.view(ref)
    if not v["on"]:
        return {**v, "status": "off" if v["status"] == "missing" else v["status"], "requested": False}
    asked = req.refresh or (req.ask and (v["status"] in ("missing", "off") or bool(v.get("stale"))))
    if asked:
        control.submit_list(ref)
    return {**v, "requested": bool(asked)}


class WatchListBody(BaseModel):
    source: str = "symbols"
    name: str | None = Field(None, max_length=saved.NAME_MAX)
    symbols: list[str] | None = Field(None, max_length=watchlists.MAX_SYMBOLS)
    feed: dict | None = None


class RenameBody(BaseModel):
    to: str = Field(max_length=200)


@router.get("/api/watchlists")
def watch_lists():
    return watchlists.all_lists()


@router.post("/api/watchlists")
def watch_list_create(req: WatchListBody):
    """A new named watch list: under the name given, or the next "Watch list N"."""
    try:
        name, item = watchlists.create(req.source, req.model_dump(exclude_none=True), req.name)
    except ValueError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e)) from None
    return {"name": name, "item": item, "lists": watchlists.all_lists()}


@router.put("/api/watchlists/{name}")
def watch_list_update(name: str, req: WatchListBody):
    if name not in watchlists.all_lists():
        raise HTTPException(404, f'No watch list called "{name}"')
    try:
        item = watchlists.update(name, req.source, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"name": name, "item": item, "lists": watchlists.all_lists()}


@router.post("/api/watchlists/{name}/rename")
def watch_list_rename(name: str, req: RenameBody):
    try:
        item = watchlists.rename(name, req.to)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    except ValueError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e)) from None
    return {"name": req.to.strip(), "item": item, "lists": watchlists.all_lists()}


@router.delete("/api/watchlists/{name}")
def watch_list_delete(name: str):
    watchlists.delete(name)
    return {"lists": watchlists.all_lists()}
