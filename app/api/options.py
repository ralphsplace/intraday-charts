"""The option chain and structures (read-only): the cached chain, requests for fresh snapshots, templates and
the evaluation of a structure (app/option_chain.py, app/structures.py). Nothing here places an order."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import control, option_chain, structures
from .common import DEMO_RE, one_symbol, valid_expiry

router = APIRouter()


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
            out.append({"qty": leg.qty, "expiry": valid_expiry(leg.expiry), "strike": leg.strike, "right": leg.right})
    if not out:
        raise HTTPException(400, "Add at least one leg")
    return out


@router.get("/api/options/chain")
def options_chain(symbol: str, expiry: str | None = None):
    """The cached option chain for one expiry, with the expiry strip (app/option_chain.py)."""
    return option_chain.view(one_symbol(symbol, demo_ok=True), valid_expiry(expiry) if expiry else None)


@router.post("/api/options/request")
def options_request(req: ChainRequest):
    """Ask the TWS collector for fresh option-chain snapshots (read-only)."""
    sym = one_symbol(req.symbol, demo_ok=True)
    if DEMO_RE.match(sym):
        raise HTTPException(400, "Synthetic -DEMO symbols are never fetched")
    if req.window not in option_chain.WINDOWS:
        raise HTTPException(400, f"window must be one of {option_chain.WINDOWS}")
    r = control.submit([sym], chain={"expiries": [valid_expiry(e) for e in req.expiries], "window": req.window})
    return {"id": r["id"], "symbol": sym}


@router.post("/api/options/template")
def options_template(req: TemplateRequest):
    """A template's legs, from the strikes in the cached chain (app/structures.py)."""
    cache = option_chain.read(one_symbol(req.symbol, demo_ok=True))
    if not cache or cache.get("error"):
        raise HTTPException(409, "No option quotes yet: wait for the chain to load")
    try:
        legs = structures.template(req.template, cache, valid_expiry(req.front), valid_expiry(req.back) if req.back else None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"legs": legs}


@router.post("/api/options/evaluate")
def options_evaluate(req: StructureRequest):
    """A structure's numbers: risk graph, breakevens, chance of profit, Greeks, grid (estimates; no orders)."""
    return option_chain.evaluate(one_symbol(req.symbol, demo_ok=True), _legs(req.legs), req.at, req.iv_shift, req.stop)
