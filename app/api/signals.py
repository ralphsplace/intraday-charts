"""Signal rules and strategies (app/signals/): the named rules and the expressions they're made of, the recommended
rules, the strategies on them, and a strategy's entries and exits on a chart."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..signals import chart, expr, presets, rules, strategies
from .common import call, one_symbol, valid_date

router = APIRouter()


class RenameBody(BaseModel):
    to: str = Field(max_length=200)


class RuleBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    rule: dict


class StrategyBody(BaseModel):
    name: str | None = Field(None, max_length=200)
    strategy: dict


class ExprBody(BaseModel):
    text: str | None = Field(None, max_length=expr.MAX_TEXT)      # typed, or
    tree: dict | None = None                                     # from the group editor


class PresetsBody(BaseModel):
    names: list[str] | None = None                         # the recommended rules to add, or all of them


def _rules_view() -> dict:
    """The saved rules, each with its expression as a tree too (for the group editor)."""
    return {n: {**v, "tree": expr.parse(v["when"])} for n, v in rules.all_rules().items()}


def _strategies_view() -> dict:
    return {n: {**v, "trees": {k: expr.parse(v[k]) if v.get(k) else None for k, _ in strategies.SIGNALS}}
            for n, v in strategies.all_strategies().items()}


# ---------------------------------------------------------------- rules (app/signals/rules.py, expr.py, presets.py)
@router.get("/api/signal-rules")
def signal_rules():
    return {"rules": _rules_view(), "ops": rules.OPS, "prices": rules.PRICES, "tfs": rules.TFS,
            "letters": rules.MAX_CONDITIONS}


@router.post("/api/signal-expr")
def signal_expr(req: ExprBody):
    """An expression checked and turned into its other form: text to a tree, a tree to text. 400 says what's wrong
    and where ("pos", 0-based)."""
    try:
        tree = expr.valid_tree(req.tree) if req.tree is not None else expr.parse(req.text or "")
    except expr.ExprError as e:
        raise HTTPException(400, {"message": str(e), "pos": e.pos}) from None
    letters, names = expr.refs(tree)
    return {"tree": tree, "text": expr.text(tree), "letters": letters, "rules": names}


@router.post("/api/signal-rules")
def signal_rule_save(req: RuleBody):
    """A new rule (under its name, or "Rule N"), or new contents for the rule of that name."""
    name, item = call(rules.save, req.name, req.rule)
    return {"name": name, "item": item, "rules": _rules_view()}


@router.get("/api/signal-rules/presets")
def signal_rule_presets():
    """The recommended rules (app/signals/presets.py), and which are saved already."""
    return {"presets": presets.listing()}


@router.post("/api/signal-rules/presets")
def signal_rule_presets_add(req: PresetsBody):
    """Save recommended rules (with the rules they're made of); a saved rule of the same name is kept."""
    r = call(presets.add, req.names)
    return {**r, "rules": _rules_view(), "presets": presets.listing()}


@router.post("/api/signal-rules/{name}/rename")
def signal_rule_rename(name: str, req: RenameBody):
    """A new name; the rules and strategies that use it say the new one."""
    call(rules.rename, name, req.to)
    return {"name": req.to.strip(), "rules": _rules_view(), "strategies": _strategies_view()}


@router.delete("/api/signal-rules/{name}")
def signal_rule_delete(name: str):
    """409 when a rule or strategy uses it."""
    call(rules.delete, name)
    return {"rules": _rules_view()}


# ---------------------------------------------------------------- strategies (app/signals/strategies.py)
@router.get("/api/signal-strategies")
def signal_strategies():
    return {"strategies": _strategies_view(), "rules": sorted(rules.all_rules()), "tfs": rules.TFS}


@router.post("/api/signal-strategies")
def signal_strategy_save(req: StrategyBody):
    """A new strategy (under its name, or "Strategy N"), or new contents for the strategy of that name."""
    name, item = call(strategies.save, req.name, req.strategy)
    return {"name": name, "item": item, "strategies": _strategies_view()}


@router.post("/api/signal-strategies/{name}/rename")
def signal_strategy_rename(name: str, req: RenameBody):
    call(strategies.STRATEGIES.rename, name, req.to)
    return {"name": req.to.strip(), "strategies": _strategies_view()}


@router.delete("/api/signal-strategies/{name}")
def signal_strategy_delete(name: str):
    strategies.STRATEGIES.delete(name)
    return {"strategies": _strategies_view()}


@router.get("/api/signal-strategies/{name}/chart")
def signal_strategy_chart(name: str, symbol: str, day: str, cursor: int | None = Query(None, ge=0, le=24 * 60),
                          tf: int | None = Query(None, ge=1, le=60)):
    """A strategy's entries and exits on a chart of `symbol` on `day`, as arrows on the chart's tf-minute bars they
    happened in, up to the replay cursor (minute of the day) when there is one. Signals only: nothing is traded."""
    return call(chart.day_markers, name, one_symbol(symbol, demo_ok=True), valid_date(day), cursor, tf)
