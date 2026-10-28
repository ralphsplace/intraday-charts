"""Web server: serves the chart page and the /api endpoints it calls."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (control, dashboards, earnings, engine, envcheck, periods, saved, security, sessions, store, studies,
               templates, timeframes, watchlist)

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT.parent / "config.json"

log = logging.getLogger("intraday-charts")


@asynccontextmanager
async def lifespan(_app):
    """Check the environment before serving; a failed check stops the server (see app/envcheck.py)."""
    checks = envcheck.run()
    for c in checks:
        log.warning("environment check: %-24s %-4s %s", c["name"], c["status"], c["detail"])
    bad = envcheck.failures(checks)
    if bad:
        raise RuntimeError("Not starting: " + " ".join(f"{c['name']}: {c['detail']}" for c in bad))
    yield


def _settings() -> security.Settings:
    try:
        return security.Settings()
    except security.ConfigError:
        return security.Settings(networks="127.0.0.1/32")      # the startup check reports the error and stops


app = FastAPI(title="Intraday charts", lifespan=lifespan)
app.add_middleware(security.LocalOnly, settings=_settings())    # home network only; see app/security.py


def config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


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


class SymbolsText(BaseModel):
    text: str


@app.get("/api/meta")
def meta():
    cfg = config()
    return {"symbols": [{"symbol": s, "days": store.list_days(s), "demo": s.endswith("-DEMO")}
                        for s in store.list_symbols()],
            "default_symbol": cfg.get("default_symbol", "QQQ"),
            "timeframes": timeframes.listing(),         # the chart's candle durations and ranges
            "recorded": sorted(control.RECORDED),      # recorded from live quotes by the collector: no history before
            "calendar": sessions.info()}


def _symbols(raw: list[str]) -> list[str]:
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


@app.post("/api/fetch")
def fetch(req: FetchRequest):
    """Ask the TWS collector for bars. Replay: the day (snapped back to a trading day) and the 5 before it.
    Live: today's bars streamed, plus the days before."""
    syms = _symbols(req.symbols)
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


@app.post("/api/live/stop")
def stop_live(req: FetchRequest):
    control.submit(_symbols(req.symbols), stop_live=True)
    return {"ok": True}


@app.get("/api/collector")
def collector_status():
    return control.read_status()


@app.post("/api/symbols/parse")
def parse_symbols(req: SymbolsText):
    return watchlist.parse_symbols(req.text[:200_000])


@app.get("/api/saved/{kind}")
def saved_list(kind: str):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    return saved.all_items(kind)


@app.put("/api/saved/{kind}/{name}")
def saved_put(kind: str, name: str, data: Annotated[Any, Body()]):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if not saved.valid_name(name):
        raise HTTPException(400, f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
    if len(json.dumps(data)) > 500_000:
        raise HTTPException(400, "too large")
    return saved.put(kind, name, data)


@app.delete("/api/saved/{kind}/{name}")
def saved_delete(kind: str, name: str):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    return saved.delete(kind, name)


@app.get("/api/studies")
def study_catalog():
    """Every study that can be added to a chart, with its settings, plus the default layout."""
    return {"studies": studies.catalog(), "default_layout": config().get("default_layout", studies.DEFAULT_LAYOUT)}


@app.post("/api/view")
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


@app.get("/api/environment")
def environment():
    """The security checks, for the Dashboards page."""
    return {"checks": envcheck.run()}


# ---------------------------------------------------------------- dashboards
class DashboardCreate(BaseModel):
    name: str
    type: str = "charts"
    copy_of: str | None = None          # id of a dashboard to copy
    start_layout: str | None = None     # charts: a saved window layout to start from
    start_template: str | None = None   # charts: or a built-in template (app/templates.py)
    start_rows: list[int] | None = None  # charts: or [top, bottom] charts, e.g. [3, 5]


class DashboardUpdate(BaseModel):
    name: str | None = None
    settings: dict | None = None


def _dash_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except dashboards.DashboardError as e:
        raise HTTPException(400, str(e)) from None
    except KeyError:
        raise HTTPException(404, "No such dashboard") from None


@app.get("/api/dashboards")
def dashboards_list():
    return {**dashboards.all_dashboards(), "types": dashboards.TYPES, "name_rule": dashboards.NAME_RULE,
            "templates": templates.labels(), "max_per_row": templates.MAX_PER_ROW}


@app.post("/api/dashboards")
def dashboards_create(req: DashboardCreate):
    settings = {}
    if req.start_layout:
        lay = saved.all_items("layouts").get(req.start_layout)
        if lay is None:
            raise HTTPException(404, f'No saved layout called "{req.start_layout}"')
        settings["start"] = lay
    elif req.start_template:
        settings["start"] = templates.start(req.start_template)
        if settings["start"] is None:
            raise HTTPException(404, f'No template called "{req.start_template}"')
    elif req.start_rows is not None:
        try:
            settings["start"] = templates.rows(*req.start_rows)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e) if isinstance(e, ValueError) else "start_rows is [top, bottom]") from None
    return _dash_call(dashboards.create, req.name.strip(), req.type, settings, req.copy_of)


@app.patch("/api/dashboards/{id}")
def dashboards_update(id: str, req: DashboardUpdate):
    if req.settings is not None and len(json.dumps(req.settings)) > 500_000:
        raise HTTPException(400, "too large")
    return _dash_call(dashboards.update, id, req.name.strip() if req.name is not None else None, req.settings)


@app.delete("/api/dashboards/{id}")
def dashboards_delete(id: str):
    return _dash_call(dashboards.delete, id)


@app.post("/api/dashboards/{id}/default")
def dashboards_default(id: str):
    return _dash_call(dashboards.set_default, id)


def _static_version() -> str:
    """A fingerprint of the page files: it changes with every update that changes any of them."""
    h = hashlib.sha256()
    for f in sorted((ROOT / "static").rglob("*")):
        if f.is_file():
            h.update(f.relative_to(ROOT).as_posix().encode() + b"\0" + f.read_bytes())
    return "_v" + h.hexdigest()[:10]


STATIC_VERSION = _static_version()
_VERSION_DIR = re.compile(r"^_v[0-9a-f]{10}$")


class Revalidated(StaticFiles):
    """The page files. Pages ask for them under a versioned address, /static/_v<fingerprint>/js/main.js, so after an
    update every browser fetches the new files instead of reusing old ones it kept (the scripts' own imports are
    relative, so they follow the version). Any version is served the current files. And the browser must still
    check with the server before reusing a file (a cheap "not modified" when unchanged)."""

    def get_path(self, scope) -> str:
        head, sep, rest = super().get_path(scope).partition(os.sep)
        return rest if sep and _VERSION_DIR.match(head) else super().get_path(scope)

    def file_response(self, *a, **kw):
        r = super().file_response(*a, **kw)
        r.headers["Cache-Control"] = "no-cache"
        return r


app.mount("/static", Revalidated(directory=ROOT / "static"), name="static")

PAGES = {"charts": "index.html"}


def _page(file: str, dash: dict | None = None) -> HTMLResponse:
    page = (ROOT / "static" / file).read_text().replace('"/static/', f'"/static/{STATIC_VERSION}/')
    if dash is not None:
        info = {"id": dash["id"], "name": dash["name"], "type": dash["type"], "settings": dash.get("settings", {}),
                "legacy": dash["id"] == "main", "copied_from": dash.get("copied_from")}
        page = page.replace("<!--DASHBOARD-->", "<script>window.DASHBOARD = " +
                            json.dumps(info).replace("<", "\\u003c") + ";</script>")
        page = page.replace("<title>", f"<title>{dash['name']} · ", 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- earnings view
def earnings_lookups_on() -> bool:
    """The collector looks earnings dates up on SEC EDGAR only when SEC_CONTACT is set (.env)."""
    return bool(os.environ.get("SEC_CONTACT", "").strip())


class SymbolRequest(BaseModel):
    symbol: str


DEMO_RE = re.compile(r"^[A-Z]{1,6}-DEMO$")      # synthetic test data (tests/synthetic.py)


def _one_symbol(raw: str, demo_ok: bool = False) -> str:
    sym = control.clean_symbol(raw)
    if not sym and demo_ok and DEMO_RE.match((raw or "").strip().upper()):
        sym = raw.strip().upper()
    if not sym:
        raise HTTPException(400, f"Not a stock symbol: {raw}")
    return sym


@app.get("/api/earnings")
def earnings_view(symbol: str, before: Annotated[int, Query(ge=1, le=earnings.MAX_DAYS)] = earnings.BEFORE,
                  after: Annotated[int, Query(ge=1, le=earnings.MAX_DAYS)] = earnings.AFTER):
    """The last earnings reports of a stock, each as % change around its reaction day (app/earnings.py), with
    `before` trading days before day 0 and `after` after."""
    v = earnings.view(_one_symbol(symbol, demo_ok=True), before=before, after=after)
    v["lookups_on"] = earnings_lookups_on()
    if v["status"] == "missing" and "earnings dates" in v["missing"] and not v["lookups_on"]:
        v.update(status="off", message="Earnings-date lookups are off. Set SEC_CONTACT in .env (README, "
                 "\"Earnings view\") so the TWS collector can look them up on SEC EDGAR.")
    return v


@app.post("/api/earnings/request")
def earnings_request(req: SymbolRequest):
    """Ask the TWS collector for a stock's daily prices and (when lookups are on) its earnings dates."""
    sym = _one_symbol(req.symbol)          # synthetic -DEMO symbols are never sent to the collector
    r = control.submit([sym], daily_only=True, earnings=earnings_lookups_on())
    return {"id": r["id"], "symbol": sym}


@app.get("/earnings")
def earnings_page():
    return _page("earnings.html")


@app.get("/")
def index():
    d = dashboards.default()
    return _page(PAGES[d["type"]], d)


@app.get("/dashboards")
def dashboards_page():
    return _page("dashboards.html")


@app.get("/{name}")
def dashboard_page(name: str):
    d = dashboards.find(name)
    if not d:
        return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>No such dashboard</title>
<body style="font:15px system-ui;background:#0b0d10;color:#e3e6ea;padding:40px">
<p>There is no dashboard called <b>{html.escape(name)}</b>.</p>
<p><a style="color:#7fb8ff" href="/dashboards">Manage dashboards</a> · <a style="color:#7fb8ff" href="/">Default dashboard</a></p>""",
                            status_code=404)
    return _page(PAGES[d["type"]], d)
