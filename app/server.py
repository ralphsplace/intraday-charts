"""Web server: serves the chart page and the /api endpoints it calls."""
from __future__ import annotations

import datetime
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

from . import (control, dashboards, earnings, engine, envcheck, expected_move, list_sources, option_chain, periods,
               app_config, positions, saved, security, sessions, store, structures, studies, study_values, templates, timeframes,
               watch_fields, watchlist, watchlists)

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


MAX_QUOTE_SYMBOLS = 100


@app.get("/api/quotes")
def quote_rows(symbols: str, day: str, cursor: int | None = Query(None, ge=0, le=24 * 60), cols: str = ""):
    """Watch list rows from the cached 1-minute bars of `day` (up to the Replay cursor, when given), with the
    values of the columns asked for (app/watch_fields.py)."""
    parts = [x for x in re.split(r"[\s,;]+", symbols or "") if x]
    if len(parts) > MAX_QUOTE_SYMBOLS:
        raise HTTPException(400, f"At most {MAX_QUOTE_SYMBOLS} symbols")
    syms = list(dict.fromkeys(_one_symbol(x, demo_ok=True) for x in parts))
    return {"day": _date(day), "items": watch_fields.rows(syms, day, cursor, _cols(cols))}


def _cols(cols: str) -> list[str]:
    return [c for c in (cols or "").split(",")[:80] if c in watch_fields.BY_ID]


@app.get("/api/watch/columns")
def watch_columns():
    """The columns a watch list can show (app/watch_fields.py), and each list kind's default set."""
    return watch_fields.catalog()


@app.get("/api/study-value")
def study_value(symbol: str, day: str, type: str, output: str = "", tf: int = 1, params: str = "{}",
                cursor: int | None = Query(None, ge=0, le=24 * 60)):
    """One study's line or level at the cursor (app/study_values.py), e.g. type=vwap&output=vwap, or
    type=sma&params={"length":50}&tf=5&output=sma."""
    try:
        p = json.loads(params or "{}")
        if not isinstance(p, dict):
            raise ValueError("params must be an object")
        return {"symbol": _one_symbol(symbol, demo_ok=True), "day": _date(day),
                **study_values.value(symbol, day, {"type": type, "params": p, "output": output or type, "tf": tf}, cursor)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/positions")
def position_rows(day: str, cursor: int | None = Query(None, ge=0, le=24 * 60), cols: str = ""):
    """The watch list's Holdings list: the account's stock and ETF positions (read by the collector when
    HOLDINGS=on) with market value and P/L at the price of `day` (up to the Replay cursor, when given)."""
    return {"day": _date(day), **positions.view(day, cursor, _cols(cols))}


@app.post("/api/symbols/parse")
def parse_symbols(req: SymbolsText):
    return watchlist.parse_symbols(req.text[:200_000])


class ListSourceRequest(BaseModel):
    source: str = Field(max_length=20)
    address: str = Field(max_length=4000)
    refresh: bool = False          # fetch again now
    ask: bool = True               # ask the collector when missing or stale (False: just read, while waiting)


@app.post("/api/lists/source")
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


@app.get("/api/saved/{kind}")
def saved_list(kind: str):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if kind == "watchlists":                       # kept in the application config (app/watchlists.py)
        return watchlists.all_lists()
    return saved.all_items(kind)


@app.put("/api/saved/{kind}/{name}")
def saved_put(kind: str, name: str, data: Annotated[Any, Body()]):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if not saved.valid_name(name):
        raise HTTPException(400, f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
    if len(json.dumps(data)) > 500_000:
        raise HTTPException(400, "too large")
    if kind == "watchlists":                       # Load data's "Save as watchlist": keep the list's id
        if not isinstance(data, list):
            raise HTTPException(400, "A watchlist saved here is a list of symbols")
        watchlists.set_symbols(name, data)
        return watchlists.all_lists()
    return saved.put(kind, name, data)


# ---------------------------------------------------------------- named watch lists (app/watchlists.py)
class WatchListBody(BaseModel):
    source: str = "symbols"
    name: str | None = Field(None, max_length=saved.NAME_MAX)
    symbols: list[str] | None = Field(None, max_length=watchlists.MAX_SYMBOLS)
    feed: dict | None = None


class RenameBody(BaseModel):
    to: str = Field(max_length=200)


@app.get("/api/watchlists")
def watch_lists():
    return watchlists.all_lists()


@app.post("/api/watchlists")
def watch_list_create(req: WatchListBody):
    """A new named watch list: under the name given, or the next "Watch list N"."""
    try:
        name, item = watchlists.create(req.source, req.model_dump(exclude_none=True), req.name)
    except ValueError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e)) from None
    return {"name": name, "item": item, "lists": watchlists.all_lists()}


@app.put("/api/watchlists/{name}")
def watch_list_update(name: str, req: WatchListBody):
    if name not in watchlists.all_lists():
        raise HTTPException(404, f'No watch list called "{name}"')
    try:
        item = watchlists.update(name, req.source, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"name": name, "item": item, "lists": watchlists.all_lists()}


@app.post("/api/watchlists/{name}/rename")
def watch_list_rename(name: str, req: RenameBody):
    try:
        item = watchlists.rename(name, req.to)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    except ValueError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e)) from None
    return {"name": req.to.strip(), "item": item, "lists": watchlists.all_lists()}


@app.delete("/api/watchlists/{name}")
def watch_list_delete(name: str):
    watchlists.delete(name)
    return {"lists": watchlists.all_lists()}


@app.delete("/api/saved/{kind}/{name}")
def saved_delete(kind: str, name: str):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if kind == "watchlists":
        watchlists.delete(name)
        return watchlists.all_lists()
    return saved.delete(kind, name)


# ---------------------------------------------------------------- the application config (the Config page)
@app.get("/api/config")
def app_config_view():
    """Everything the Config page edits: study defaults (with the built-in ones), each watch list kind's default
    columns, and the named watch lists."""
    return {"studies": studies.catalog(), "watch_columns": watch_fields.catalog(), "watchlists": watchlists.all_lists(),
            "path": "data/user/config.json"}


@app.put("/api/config/studies/{type}")
def config_study_defaults(type: str, params: Annotated[dict, Body()]):
    """New defaults for a study: kept only where they differ from the built-in ones."""
    spec = studies.base.REGISTRY.get(type)
    if not spec:
        raise HTTPException(404, f"Unknown study '{type}'")
    full = studies.base.coerce(spec, params)
    mine = {p["key"]: full[p["key"]] for p in spec["params"] if p["key"] in params and full[p["key"]] != p["default"]}
    with app_config.editing() as d:
        st = d.setdefault("studies", {})
        if mine:
            st[type] = mine
        else:
            st.pop(type, None)
    return next(s for s in studies.catalog() if s["type"] == type)


@app.delete("/api/config/studies/{type}")
def config_study_reset(type: str):
    with app_config.editing() as d:
        d.setdefault("studies", {}).pop(type, None)
    return {"ok": True}


@app.put("/api/config/watch-columns/{kind}")
def config_watch_columns(kind: str, ids: Annotated[list[str], Body()]):
    try:
        cols = watch_fields.check_columns(kind, ids)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    with app_config.editing() as d:
        d.setdefault("watch_columns", {})[kind] = cols
    return watch_fields.catalog()


@app.delete("/api/config/watch-columns/{kind}")
def config_watch_columns_reset(kind: str):
    with app_config.editing() as d:
        d.setdefault("watch_columns", {}).pop(kind, None)
    return watch_fields.catalog()


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
        v.update(status="off", message="Earnings-date lookups are off. Set SEC_CONTACT in .env (user guide, "
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


# ---------------------------------------------------------------- expected-move view
MAX_EM_SYMBOLS = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _em_symbols(raw: str, demo_ok: bool = False) -> list[str]:
    parts = [x for x in re.split(r"[\s,;]+", raw or "") if x]
    if not parts:
        raise HTTPException(400, "Type at least one symbol")
    if len(parts) > MAX_EM_SYMBOLS:
        raise HTTPException(400, f"At most {MAX_EM_SYMBOLS} symbols at a time")
    return list(dict.fromkeys(_one_symbol(x, demo_ok=demo_ok) for x in parts))


def _date(raw: str) -> str:
    if not DATE_RE.match(raw or ""):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, "date must be a real date") from None
    return raw


class ExpectedMoveRequest(BaseModel):
    symbols: str
    date: str


@app.get("/api/expected-move")
def expected_move_view(symbols: str, date: str):
    """Each symbol's expected move by the first expiry on or after `date`, from cached option quotes
    (app/expected_move.py)."""
    d = _date(date)
    return {"date": d, "stale_seconds": expected_move.STALE_SECONDS,
            "items": [expected_move.view(s, d) for s in _em_symbols(symbols, demo_ok=True)]}


@app.post("/api/expected-move/request")
def expected_move_request(req: ExpectedMoveRequest):
    """Ask the TWS collector for fresh option quotes (snapshots, read-only)."""
    syms = [s for s in _em_symbols(req.symbols, demo_ok=True) if not DEMO_RE.match(s)]   # synthetic: never fetched
    if not syms:
        raise HTTPException(400, "Synthetic -DEMO symbols are never fetched")
    r = control.submit(syms, options_for=_date(req.date))
    return {"id": r["id"], "symbols": syms}


@app.get("/expected-move")
def expected_move_page():
    return _page("expected-move.html")


# ---------------------------------------------------------------- option chain and structures (read-only)
EXPIRY_RE = re.compile(r"^\d{8}$")


def _expiry(raw: str) -> str:
    if not EXPIRY_RE.match(raw or ""):
        raise HTTPException(400, "expiry must be YYYYMMDD")
    _date(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return raw


class ChainRequest(BaseModel):
    symbol: str
    expiries: list[str] = Field(default_factory=list, max_length=option_chain.MAX_EXPIRIES)
    window: int = option_chain.DEFAULT_WINDOW


class Leg(BaseModel):
    qty: int = Field(ge=-50, le=50)
    expiry: str
    strike: float = Field(gt=0, lt=1e6)
    right: str


class StructureRequest(BaseModel):
    symbol: str
    legs: list[Leg] = Field(default_factory=list, max_length=12)
    at: str = "front_close"
    iv_shift: float = Field(0.0, ge=-0.5, le=0.5)
    stop: float | None = Field(None, ge=-1e7, le=0)


class TemplateRequest(BaseModel):
    symbol: str
    template: str
    front: str
    back: str | None = None


def _legs(legs: list[Leg]) -> list[dict]:
    out = []
    for leg in legs:
        if leg.right not in ("C", "P"):
            raise HTTPException(400, "right must be C or P")
        if leg.qty:
            out.append({"qty": leg.qty, "expiry": _expiry(leg.expiry), "strike": leg.strike, "right": leg.right})
    if not out:
        raise HTTPException(400, "Add at least one leg")
    return out


@app.get("/api/options/chain")
def options_chain(symbol: str, expiry: str | None = None):
    """The cached option chain for one expiry, with the expiry strip (app/option_chain.py)."""
    return option_chain.view(_one_symbol(symbol, demo_ok=True), _expiry(expiry) if expiry else None)


@app.post("/api/options/request")
def options_request(req: ChainRequest):
    """Ask the TWS collector for fresh option-chain snapshots (read-only)."""
    sym = _one_symbol(req.symbol, demo_ok=True)
    if DEMO_RE.match(sym):
        raise HTTPException(400, "Synthetic -DEMO symbols are never fetched")
    if req.window not in option_chain.WINDOWS:
        raise HTTPException(400, f"window must be one of {option_chain.WINDOWS}")
    r = control.submit([sym], chain={"expiries": [_expiry(e) for e in req.expiries], "window": req.window})
    return {"id": r["id"], "symbol": sym}


@app.post("/api/options/template")
def options_template(req: TemplateRequest):
    """A template's legs, from the strikes in the cached chain (app/structures.py)."""
    cache = option_chain.read(_one_symbol(req.symbol, demo_ok=True))
    if not cache or cache.get("error"):
        raise HTTPException(409, "No option quotes yet: wait for the chain to load")
    try:
        legs = structures.template(req.template, cache, _expiry(req.front), _expiry(req.back) if req.back else None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"legs": legs}


@app.post("/api/options/evaluate")
def options_evaluate(req: StructureRequest):
    """A structure's numbers: risk graph, breakevens, chance of profit, Greeks, grid (estimates; no orders)."""
    return option_chain.evaluate(_one_symbol(req.symbol, demo_ok=True), _legs(req.legs), req.at, req.iv_shift, req.stop)


@app.get("/options")
def options_page():
    return _page("options.html")


@app.get("/config")
def config_page():
    return _page("config.html")


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
