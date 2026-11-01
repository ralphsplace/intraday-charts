"""Paper trading (app/paper/): named accounts and their history. Simulated on the NAS; nothing here talks to TWS or
IBKR, and nothing here places, changes or cancels a real order."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import app_config
from ..paper import accounts

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
