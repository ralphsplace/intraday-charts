"""Named backtesting accounts: the starting cash and costs a backtest runs with. App-wide, kept in the application
config (section "backtest_accounts"), with the naming rules every named thing shares (app/named.py): unique
names, "Account N" for a new one, an id that never changes, a rename that's a move.

An account: {"id", "start_cash", "settings": {commission, slippage, shorting} as in engine.py, "created"}.
"""
from __future__ import annotations

import copy
import time

from .. import app_config
from ..named import Named
from . import engine

ACCOUNTS = Named("backtest_accounts", "Account", "backtesting account")
BUILT_IN = {"start_cash": 25_000.0, "settings": engine.DEFAULT_SETTINGS}
MAX_CASH = 100_000_000


def defaults() -> dict:
    """A new account's starting cash and settings: the built-in ones with the Config page's on top."""
    mine = app_config.section("backtesting").get("defaults") or {}
    return check({**copy.deepcopy(BUILT_IN), **mine}, partial=False)


def check(a: dict, partial: bool = True) -> dict:
    """Starting cash and settings checked and filled in; ValueError says what's wrong."""
    out = {}
    if "start_cash" in a or not partial:
        cash = a.get("start_cash")
        if not isinstance(cash, (int, float)) or not 100 <= cash <= MAX_CASH:
            raise ValueError(f"Starting cash is $100 to ${MAX_CASH:,}")
        out["start_cash"] = float(cash)
    if "settings" in a or not partial:
        s = {**copy.deepcopy(engine.DEFAULT_SETTINGS), **(a.get("settings") or {})}
        c = {**engine.DEFAULT_SETTINGS["commission"], **(s.get("commission") or {})}
        for k, hi in (("per_share", 1), ("minimum", 100), ("max_pct", 100)):
            if not isinstance(c.get(k), (int, float)) or not 0 <= c[k] <= hi:
                raise ValueError(f"commission {k.replace('_', ' ')} is 0 to {hi}")
        if not isinstance(s.get("slippage"), (int, float)) or not 0 <= s["slippage"] <= 10:
            raise ValueError("slippage is $0 to $10 a share")
        out["settings"] = {"commission": {k: float(c[k]) for k in ("per_share", "minimum", "max_pct")},
                           "slippage": float(s["slippage"]), "shorting": bool(s.get("shorting", True))}
    return out


def all_accounts() -> dict:
    """{name: account}."""
    return ACCOUNTS.items()


def create(name: str | None = None, start_cash: float | None = None, settings: dict | None = None) -> tuple[str, dict]:
    d = defaults()
    item = check({"start_cash": d["start_cash"] if start_cash is None else start_cash,
                  "settings": {**d["settings"], **(settings or {})}}, partial=False)
    return ACCOUNTS.create({**item, "created": int(time.time())}, name)


def update(name: str, changes: dict) -> dict:
    """New starting cash or settings."""
    _, old = ACCOUNTS.find(name)
    if old is None:
        raise KeyError(f'No backtesting account called "{name}"')
    merged = {**old, **check({**changes, "settings": {**old["settings"], **(changes.get("settings") or {})}}
                             if "settings" in changes else changes)}
    return ACCOUNTS.replace(name, merged)


def rename(old: str, new: str) -> dict:
    return ACCOUNTS.rename(old, new)


def delete(name: str) -> None:
    ACCOUNTS.delete(name)


def find(id_or_name: str) -> tuple[str, dict]:
    name, item = ACCOUNTS.find(id_or_name)
    if item is None:
        raise KeyError(f'No backtesting account called "{id_or_name}"')
    return name, item
