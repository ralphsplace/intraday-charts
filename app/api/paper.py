"""Paper trading (app/paper/): named accounts and their history. Simulated on the NAS; nothing here talks to TWS or
IBKR, and nothing here places, changes or cancels a real order."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import app_config
from ..paper import accounts, engine, jobs, practice, rules
from .common import one_symbol, valid_date

router = APIRouter()


class AccountBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    start_cash: float | None = None
    settings: dict | None = None


class RenameBody(BaseModel):
    to: str = Field(max_length=200)


def _call(fn, *a):
    try:
        return fn(*a)
    except engine.PaperError as e:                         # an order the account can't take: say why
        raise HTTPException(409, str(e)) from None
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    except ValueError as e:
        raise HTTPException(409 if "already" in str(e) else 400, str(e)) from None


@router.get("/api/paper/accounts")
def paper_accounts():
    return {"accounts": accounts.all_accounts(), "defaults": accounts.defaults()}


@router.post("/api/paper/accounts")
def paper_account_create(req: AccountBody):
    name, item = _call(accounts.create, req.name, req.start_cash, req.settings)
    return {"name": name, "item": item, "accounts": accounts.all_accounts()}


@router.put("/api/paper/accounts/{name}")
def paper_account_update(name: str, req: AccountBody):
    changes = req.model_dump(exclude_none=True, exclude={"name"})
    item = _call(accounts.update, name, changes)
    return {"name": name, "item": item, "accounts": accounts.all_accounts()}


@router.post("/api/paper/accounts/{name}/rename")
def paper_account_rename(name: str, req: RenameBody):
    item = _call(accounts.rename, name, req.to)
    return {"name": req.to.strip(), "item": item, "accounts": accounts.all_accounts()}


@router.post("/api/paper/accounts/{name}/reset")
def paper_account_reset(name: str):
    _call(accounts.reset, name)
    return {"accounts": accounts.all_accounts()}


@router.delete("/api/paper/accounts/{name}")
def paper_account_delete(name: str):
    accounts.delete(name)
    return {"accounts": accounts.all_accounts()}


@router.get("/api/paper/accounts/{name}/history")
def paper_account_history(name: str):
    n, item = _call(accounts.find, name)
    return {"name": n, "item": {**item, "balance": accounts.balance(item)}, **accounts.history(item)}


@router.put("/api/paper/defaults")
def paper_defaults(req: AccountBody):
    """A new account's starting cash and settings (the Config page)."""
    d = _call(accounts.check, {"start_cash": req.start_cash if req.start_cash is not None else accounts.defaults()["start_cash"],
                               "settings": req.settings or accounts.defaults()["settings"]}, False)
    with app_config.editing() as cfg:
        cfg.setdefault("paper", {})["defaults"] = d
    return accounts.defaults()


@router.delete("/api/paper/defaults")
def paper_defaults_reset():
    with app_config.editing() as cfg:
        cfg.setdefault("paper", {}).pop("defaults", None)
    return accounts.defaults()


# ---------------------------------------------------------------- Replay practice (app/paper/practice.py)
class PracticeBody(BaseModel):
    account: str = Field(max_length=200)
    symbol: str
    day: str
    cursor: int = Field(ge=0, le=24 * 60)


class OrderBody(PracticeBody):
    kind: str = "order"                     # order | bracket | cancel | modify | flatten
    order: dict | None = None               # order, bracket: the order (the bracket's entry)
    stop: dict | None = None                # bracket: {"price"} or {"trail": {"amount" | "pct"}}
    target: dict | None = None              # bracket: {"price"}
    id: int | None = None                   # cancel, modify: the order
    changes: dict | None = None             # modify


def _where(req: PracticeBody) -> tuple:
    return req.account, one_symbol(req.symbol, demo_ok=True), valid_date(req.day), req.cursor


@router.post("/api/paper/practice")
def paper_practice(req: PracticeBody):
    """The account's practice session for this symbol and day, at the replay cursor."""
    return _call(practice.view, *_where(req))


@router.post("/api/paper/practice/act")
def paper_practice_act(req: OrderBody):
    """Place, change or cancel an order, or flatten, at the replay cursor. Simulated: never sent to the broker."""
    if req.kind not in ("order", "bracket", "cancel", "modify", "flatten"):
        raise HTTPException(400, "kind must be order, bracket, cancel, modify or flatten")
    action = {"kind": req.kind, **({"order": req.order} if req.order else {}), **({"stop": req.stop} if req.stop else {}),
              **({"target": req.target} if req.target else {}), **({"id": req.id} if req.id is not None else {}),
              **({"changes": req.changes} if req.changes else {})}
    return _call(practice.act, *_where(req), action)


@router.post("/api/paper/practice/rewind")
def paper_practice_rewind(req: PracticeBody):
    """The replay stepped back: drop what was done after the cursor (the page asks first)."""
    return _call(practice.rewind, *_where(req))


# ---------------------------------------------------------------- rules (app/paper/rules.py)
class RuleBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    rule: dict


@router.get("/api/paper/rules")
def paper_rules():
    return {"rules": rules.all_rules(), "ops": rules.OPS, "prices": rules.PRICES, "tfs": rules.TFS}


@router.post("/api/paper/rules")
def paper_rule_save(req: RuleBody):
    """A new rule (under its name, or "Rule N"), or new contents for the rule of that name."""
    name, item = _call(rules.save, req.name, req.rule)
    return {"name": name, "item": item, "rules": rules.all_rules()}


@router.post("/api/paper/rules/{name}/rename")
def paper_rule_rename(name: str, req: RenameBody):
    _call(rules.RULES.rename, name, req.to)
    return {"name": req.to.strip(), "rules": rules.all_rules()}


@router.delete("/api/paper/rules/{name}")
def paper_rule_delete(name: str):
    rules.RULES.delete(name)
    return {"rules": rules.all_rules()}


# ---------------------------------------------------------------- backtests (app/paper/backtest.py, jobs.py)
class BacktestBody(BaseModel):
    rule: dict | None = None                # the rule itself, or
    rule_name: str | None = None            # a saved rule by name
    symbol: str
    start: str
    end: str
    missing: str = "stop"                   # days without cached bars: "stop" or "skip"
    account: str | None = None              # whose starting cash and settings (else the defaults for new accounts)
    baseline_runs: int = Field(5, ge=0, le=20)


class SaveBody(BaseModel):
    account: str = Field(max_length=200)


@router.post("/api/paper/backtests")
def paper_backtest_start(req: BacktestBody):
    """Start a backtest in the background; follow it with GET /api/paper/backtests/{id}."""
    if req.rule is None and not req.rule_name:
        raise HTTPException(400, "Give a rule, or the name of a saved one")
    rule, name = req.rule, req.rule_name or "(unsaved rule)"
    if rule is None:
        item = rules.all_rules().get(req.rule_name)
        if not item:
            raise HTTPException(404, f'No rule called "{req.rule_name}"')
        rule = item["rule"]
    if req.missing not in ("stop", "skip"):
        raise HTTPException(400, "missing is stop or skip")
    a = _call(accounts.find, req.account)[1] if req.account else accounts.defaults()
    return _call(jobs.start, rule, name, one_symbol(req.symbol, demo_ok=True), valid_date(req.start), valid_date(req.end),
                 req.missing, a["start_cash"], a["settings"], req.baseline_runs)


@router.get("/api/paper/backtests")
def paper_backtests():
    return {"runs": jobs.listing()}


@router.get("/api/paper/backtests/{run_id}")
def paper_backtest(run_id: str):
    return _call(jobs.read, run_id)


@router.delete("/api/paper/backtests/{run_id}")
def paper_backtest_delete(run_id: str):
    _call(jobs.delete, run_id)
    return {"runs": jobs.listing()}


@router.post("/api/paper/backtests/{run_id}/save")
def paper_backtest_save(run_id: str, req: SaveBody):
    """A finished backtest's days into a paper account, as sessions that open on a chart."""
    run = _call(jobs.read, run_id)
    if run.get("status") != "done":
        raise HTTPException(409, "The backtest hasn't finished")
    n = _call(practice.save_backtest, req.account, run["report"], run_id)
    return {"saved_days": n, "accounts": accounts.all_accounts()}


# ---------------------------------------------------------------- an account's trades and notes (the Paper page)
class NoteBody(BaseModel):
    key: str = Field(max_length=40)
    text: str = Field("", max_length=2000)


@router.get("/api/paper/accounts/{name}/trades")
def paper_account_trades(name: str):
    return _call(practice.trades, name)


@router.put("/api/paper/accounts/{name}/notes")
def paper_account_note(name: str, req: NoteBody):
    _call(practice.note, name, req.key, req.text)
    return _call(practice.trades, name)
