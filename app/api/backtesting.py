"""Backtesting (app/backtesting/): the backtesting accounts (starting cash and costs) and the backtests, run in the
background by the backtest worker. Simulated on the NAS from the cached bars: nothing here places an order."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import app_config
from ..backtesting import accounts, backtest, engine, jobs, review
from ..signals import strategies
from .common import call, one_symbol, valid_date

router = APIRouter()
ERRORS = ((jobs.QueueFull, 429), (engine.OrderError, 409))


def _call(fn, *a):
    return call(fn, *a, errors=ERRORS)


class AccountBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    start_cash: float | None = None
    settings: dict | None = None


class RenameBody(BaseModel):
    to: str = Field(max_length=200)


# ---------------------------------------------------------------- accounts (app/backtesting/accounts.py)
@router.get("/api/backtest-accounts")
def backtest_accounts():
    return {"accounts": accounts.all_accounts(), "defaults": accounts.defaults()}


@router.post("/api/backtest-accounts")
def backtest_account_create(req: AccountBody):
    name, item = _call(accounts.create, req.name, req.start_cash, req.settings)
    return {"name": name, "item": item, "accounts": accounts.all_accounts()}


@router.put("/api/backtest-accounts/{name}")
def backtest_account_update(name: str, req: AccountBody):
    changes = req.model_dump(exclude_none=True, exclude={"name"})
    item = _call(accounts.update, name, changes)
    return {"name": name, "item": item, "accounts": accounts.all_accounts()}


@router.post("/api/backtest-accounts/{name}/rename")
def backtest_account_rename(name: str, req: RenameBody):
    item = _call(accounts.rename, name, req.to)
    return {"name": req.to.strip(), "item": item, "accounts": accounts.all_accounts()}


@router.delete("/api/backtest-accounts/{name}")
def backtest_account_delete(name: str):
    accounts.delete(name)
    return {"accounts": accounts.all_accounts()}


@router.put("/api/backtest-account-defaults")
def backtest_account_defaults(req: AccountBody):
    """A new account's starting cash and settings (the Config page)."""
    d = _call(accounts.check, {"start_cash": req.start_cash if req.start_cash is not None else accounts.defaults()["start_cash"],
                               "settings": req.settings or accounts.defaults()["settings"]}, False)
    with app_config.editing() as cfg:
        cfg.setdefault("backtesting", {})["defaults"] = d
    return accounts.defaults()


@router.delete("/api/backtest-account-defaults")
def backtest_account_defaults_reset():
    with app_config.editing() as cfg:
        cfg.setdefault("backtesting", {}).pop("defaults", None)
    return accounts.defaults()


# ---------------------------------------------------------------- backtests (app/backtesting/backtest.py, jobs.py)
class BacktestBody(BaseModel):
    strategy: dict | None = None            # the strategy itself, or
    strategy_name: str | None = None        # a saved strategy by name
    symbol: str
    start: str
    end: str
    missing: str | None = None              # days without cached bars: "fetch", "skip" or "stop" (else Config's default)
    account: str | None = None              # whose starting cash and settings (else the defaults for new accounts)
    baseline_runs: int | None = Field(None, ge=0, le=20)   # random-entry runs (else Config's default)


@router.post("/api/backtests")
def backtest_start(req: BacktestBody):
    """Queue a backtest; follow it with GET /api/backtests/{id}."""
    if req.strategy is None and not req.strategy_name:
        raise HTTPException(400, "Give a strategy, or the name of a saved one")
    st, name = req.strategy, req.strategy_name or "(unsaved strategy)"
    if st is None:
        st = strategies.all_strategies().get(req.strategy_name)
        if not st:
            raise HTTPException(404, f'No strategy called "{req.strategy_name}"')
    d = backtest.defaults()
    missing = req.missing or d["missing"]
    if missing not in backtest.MISSING:
        raise HTTPException(400, "missing is fetch, skip or stop")
    runs = d["baseline_runs"] if req.baseline_runs is None else req.baseline_runs
    a = _call(accounts.find, req.account)[1] if req.account else accounts.defaults()
    return _call(jobs.start, st, name, one_symbol(req.symbol, demo_ok=True), valid_date(req.start), valid_date(req.end),
                 missing, a["start_cash"], a["settings"], runs)


@router.get("/api/backtest-defaults")
def backtest_defaults():
    return backtest.defaults()


@router.put("/api/backtest-defaults")
def backtest_defaults_set(d: Annotated[dict, Body()]):
    """What the Backtests form starts with (the Config page): symbol, account, random runs, days without bars,
    workers."""
    d = _call(backtest.check_defaults, d)
    with app_config.editing() as cfg:
        cfg.setdefault("backtesting", {})["backtest"] = d
    return backtest.defaults()


@router.delete("/api/backtest-defaults")
def backtest_defaults_reset():
    with app_config.editing() as cfg:
        cfg.setdefault("backtesting", {}).pop("backtest", None)
    return backtest.defaults()


@router.get("/api/backtests")
def backtests():
    return {"runs": jobs.listing()}


@router.get("/api/backtests/{run_id}")
def backtest_read(run_id: str):
    return _call(jobs.read, run_id)


@router.get("/api/backtests/{run_id}/review")
def backtest_review(run_id: str, day: str):
    """A finished backtest's day for a chart: its symbol, timeframe, the studies its rules read, and its trades as
    entry and exit markers (the chart page's review mode, /review)."""
    return _call(review.day_view, _call(jobs.read, run_id), valid_date(day))


@router.delete("/api/backtests/{run_id}")
def backtest_delete(run_id: str):
    deleted = _call(jobs.delete, run_id)
    return JSONResponse({"runs": jobs.listing(), "deleting": not deleted}, status_code=200 if deleted else 202)
