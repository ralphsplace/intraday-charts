"""The chart page's data: symbols and days cached, fetch requests to the TWS collector, its status, the study
catalog and the chart view itself; plus the environment check the Dashboards page shows."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import control, engine, envcheck, periods, sessions, store, studies, timeframes
from .common import clean_symbols, config

router = APIRouter()

class StudyRequest(BaseModel):
    uid: str
    type: str
    params: dict = Field(default_factory=dict)


class ViewRequest(BaseModel):
    symbol: str
    day: str
    tf: int | str = 5               # minutes (1, 3, 5, 15) or a period ("1d", "1w", "1M"); app/timeframes.py
    cursor: int | None = None
    days: int = 1                   # intraday: days shown
    span: int | None = None         # periods: months shown
    studies: list[StudyRequest] = Field(default_factory=list)


class FetchRequest(BaseModel):
    symbols: list[str]
    day: str | None = None      # replay: the day to load (plus the days before it); omitted in live mode
    live: bool = False          # also stream these symbols in live mode


@router.get("/api/meta")
def meta():
    cfg = config()
    return {"symbols": [{"symbol": s, "days": store.list_days(s), "demo": s.endswith("-DEMO")}
                        for s in store.list_symbols()],
            "default_symbol": cfg.get("default_symbol", "QQQ"),
            "timeframes": timeframes.listing(),         # the chart's candle durations and ranges
            "recorded": sorted(control.RECORDED),      # recorded from live quotes by the collector: no history before
            "calendar": sessions.info()}


@router.post("/api/fetch")
def fetch(req: FetchRequest):
    """Ask the TWS collector for bars. Replay: the day (snapped back to a trading day) and the 5 before it.
    Live: today's bars streamed, plus the days before."""
    syms = clean_symbols(req.symbols)
    day = None
    if req.day:
        try:
            day = sessions.session_on_or_before(req.day)
        except ValueError:
            raise HTTPException(400, "day must be YYYY-MM-DD") from None
        if day > sessions.live_day():
            raise HTTPException(400, "That day hasn't traded yet")
    r = control.submit(syms, day=day, live=req.live)
    return {"id": r["id"], "symbols": syms, "day": day or sessions.live_day(), "requested_day": req.day}


@router.post("/api/live/stop")
def stop_live(req: FetchRequest):
    control.submit(clean_symbols(req.symbols), stop_live=True)
    return {"ok": True}


@router.get("/api/collector")
def collector_status():
    return control.read_status()


@router.get("/api/studies")
def study_catalog():
    """Every study that can be added to a chart, with its settings, plus the default layout."""
    return {"studies": studies.catalog(), "default_layout": config().get("default_layout", studies.DEFAULT_LAYOUT)}


@router.post("/api/view")
def view(req: ViewRequest):
    tf = timeframes.parse(req.tf)
    if tf is None:
        raise HTTPException(400, "tf must be 1, 3, 5, 15, 1d, 1w or 1M")
    if timeframes.is_period(tf):
        if req.span is not None and req.span not in dict(timeframes.SPANS):
            raise HTTPException(400, "span must be one of " + ", ".join(str(m) for m, _ in timeframes.SPANS) + " months")
        try:
            return periods.build_view(req.symbol.upper(), req.day, tf, cursor=req.cursor,
                                      studies=[s.model_dump() for s in req.studies], config=config(), span=req.span)
        except ValueError as e:
            raise HTTPException(404, str(e)) from None
    if not 1 <= req.days <= engine.MAX_SHOWN_DAYS:
        raise HTTPException(400, f"days must be 1 to {engine.MAX_SHOWN_DAYS}")
    try:
        return engine.build_view(req.symbol.upper(), req.day, tf=tf, cursor=req.cursor,
                                 studies=[s.model_dump() for s in req.studies],
                                 events_path=store.DATA_DIR / "events.json", config=config(), days=req.days)
    except ValueError as e:
        raise HTTPException(404, str(e)) from None


@router.get("/api/environment")
def environment():
    """The security checks, for the Dashboards page."""
    return {"checks": envcheck.run()}
