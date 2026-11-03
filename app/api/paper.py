"""Paper trading (app/paper/): named accounts and their history. Simulated on the NAS; nothing here talks to TWS or
IBKR, and nothing here places, changes or cancels a real order."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from .. import app_config
from ..paper import accounts, backtest, engine, expr, jobs, practice, presets, review, rules, strategies
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
        raise HTTPException(409 if "already" in str(e) or "is used by" in str(e) else 400, str(e)) from None


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


# ---------------------------------------------------------------- rules and strategies (app/paper/rules.py, strategies.py)
class RuleBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    rule: dict


class StrategyBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    strategy: dict


class ExprBody(BaseModel):
    text: str | None = Field(None, max_length=expr.MAX_TEXT)      # typed, or
    tree: dict | None = None                                     # from the group editor


def _rules_view() -> dict:
    """The saved rules, each with its expression as a tree too (for the group editor)."""
    return {n: {**v, "tree": expr.parse(v["when"])} for n, v in rules.all_rules().items()}


def _strategies_view() -> dict:
    return {n: {**v, "trees": {k: expr.parse(v[k]) if v.get(k) else None for k, _ in strategies.SIGNALS}}
            for n, v in strategies.all_strategies().items()}


@router.get("/api/paper/rules")
def paper_rules():
    return {"rules": _rules_view(), "ops": rules.OPS, "prices": rules.PRICES, "tfs": rules.TFS,
            "letters": rules.MAX_CONDITIONS}


@router.post("/api/paper/expr")
def paper_expr(req: ExprBody):
    """An expression checked and turned into its other form: text to a tree, a tree to text. 400 says what's wrong
    and where ("pos", 0-based)."""
    try:
        tree = expr.valid_tree(req.tree) if req.tree is not None else expr.parse(req.text or "")
    except expr.ExprError as e:
        raise HTTPException(400, {"message": str(e), "pos": e.pos}) from None
    letters, names = expr.refs(tree)
    return {"tree": tree, "text": expr.text(tree), "letters": letters, "rules": names}


@router.post("/api/paper/rules")
def paper_rule_save(req: RuleBody):
    """A new rule (under its name, or "Rule N"), or new contents for the rule of that name."""
    name, item = _call(rules.save, req.name, req.rule)
    return {"name": name, "item": item, "rules": _rules_view()}


class PresetsBody(BaseModel):
    names: list[str] | None = None                         # the recommended rules to add, or all of them


@router.get("/api/paper/rules/presets")
def paper_rule_presets():
    """The recommended rules (app/paper/presets.py), and which are saved already."""
    return {"presets": presets.listing()}


@router.post("/api/paper/rules/presets")
def paper_rule_presets_add(req: PresetsBody):
    """Save recommended rules (with the rules they're made of); a saved rule of the same name is kept."""
    r = _call(presets.add, req.names)
    return {**r, "rules": _rules_view(), "presets": presets.listing()}


@router.post("/api/paper/rules/{name}/rename")
def paper_rule_rename(name: str, req: RenameBody):
    """A new name; the rules and strategies that use it say the new one."""
    _call(rules.rename, name, req.to)
    return {"name": req.to.strip(), "rules": _rules_view(), "strategies": _strategies_view()}


@router.delete("/api/paper/rules/{name}")
def paper_rule_delete(name: str):
    """409 when a rule or strategy uses it."""
    _call(rules.delete, name)
    return {"rules": _rules_view()}


@router.get("/api/paper/strategies")
def paper_strategies():
    return {"strategies": _strategies_view(), "rules": sorted(rules.all_rules()), "tfs": rules.TFS}


@router.post("/api/paper/strategies")
def paper_strategy_save(req: StrategyBody):
    """A new strategy (under its name, or "Strategy N"), or new contents for the strategy of that name."""
    name, item = _call(strategies.save, req.name, req.strategy)
    return {"name": name, "item": item, "strategies": _strategies_view()}


@router.post("/api/paper/strategies/{name}/rename")
def paper_strategy_rename(name: str, req: RenameBody):
    _call(strategies.STRATEGIES.rename, name, req.to)
    return {"name": req.to.strip(), "strategies": _strategies_view()}


@router.delete("/api/paper/strategies/{name}")
def paper_strategy_delete(name: str):
    strategies.STRATEGIES.delete(name)
    return {"strategies": _strategies_view()}


# ---------------------------------------------------------------- backtests (app/paper/backtest.py, jobs.py)
class BacktestBody(BaseModel):
    strategy: dict | None = None            # the strategy itself, or
    strategy_name: str | None = None        # a saved strategy by name
    symbol: str
    start: str
    end: str
    missing: str | None = None              # days without cached bars: "fetch", "skip" or "stop" (else Config's default)
    account: str | None = None              # whose starting cash and settings (else the defaults for new accounts)
    baseline_runs: int | None = Field(None, ge=0, le=20)   # random-entry runs (else Config's default)


class SaveBody(BaseModel):
    account: str = Field(max_length=200)


@router.post("/api/paper/backtests")
def paper_backtest_start(req: BacktestBody):
    """Start a backtest in the background; follow it with GET /api/paper/backtests/{id}."""
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


@router.get("/api/paper/backtest-defaults")
def paper_backtest_defaults():
    return backtest.defaults()


@router.put("/api/paper/backtest-defaults")
def paper_backtest_defaults_set(d: Annotated[dict, Body()]):
    """What the Backtests form starts with (the Config page): symbol, account, random runs, days without bars."""
    d = _call(backtest.check_defaults, d)
    with app_config.editing() as cfg:
        cfg.setdefault("paper", {})["backtest"] = d
    return backtest.defaults()


@router.delete("/api/paper/backtest-defaults")
def paper_backtest_defaults_reset():
    with app_config.editing() as cfg:
        cfg.setdefault("paper", {}).pop("backtest", None)
    return backtest.defaults()


@router.get("/api/paper/backtests")
def paper_backtests():
    return {"runs": jobs.listing()}


@router.get("/api/paper/backtests/{run_id}")
def paper_backtest(run_id: str):
    return _call(jobs.read, run_id)


@router.get("/api/paper/backtests/{run_id}/review")
def paper_backtest_review(run_id: str, day: str):
    """A finished backtest's day for a chart: its symbol, timeframe, the studies its rules read, and its trades as
    entry and exit markers (the chart page's review mode, /review)."""
    return _call(review.day_view, _call(jobs.read, run_id), valid_date(day))


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
