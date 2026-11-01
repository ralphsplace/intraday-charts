"""Named paper accounts: app-wide, kept in the application config (section "paper_accounts"), with the naming
rules every named thing shares (app/named.py): unique names, "Paper N" for a new one, an id that never changes,
a rename that's a move.

An account: {"id", "start_cash", "settings": {commission, slippage, shorting} as in app/paper/engine.py, "created"}.
Its history (practice sessions, backtest trades, resets, notes) is a file of its own, data/user/paper/<id>.json,
written through app/jsonfile.py, so a broken file is never written over:
    {"sessions": [{"id", "symbol", "day", "state": engine state, "started", "updated"}],
     "resets": [{"at", "balance"}], "notes": {"<session id>:<fill index>": text}}
The balance is the starting cash plus the result of every session since the last reset.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

from .. import app_config, jsonfile, store
from ..named import Named
from . import engine

ACCOUNTS = Named("paper_accounts", "Paper", "paper account")
BUILT_IN = {"start_cash": 25_000.0, "settings": engine.DEFAULT_SETTINGS}
MAX_CASH = 100_000_000


def defaults() -> dict:
    """A new account's starting cash and settings: the built-in ones with the Config page's on top."""
    mine = app_config.section("paper").get("defaults") or {}
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
    """{name: account, with its balance}."""
    return {n: {**v, "balance": balance(v)} for n, v in ACCOUNTS.items().items()}


def create(name: str | None = None, start_cash: float | None = None, settings: dict | None = None) -> tuple[str, dict]:
    d = defaults()
    item = check({"start_cash": d["start_cash"] if start_cash is None else start_cash,
                  "settings": {**d["settings"], **(settings or {})}}, partial=False)
    return ACCOUNTS.create({**item, "created": int(time.time())}, name)


def update(name: str, changes: dict) -> dict:
    """New starting cash or settings (kept: the history)."""
    _, old = ACCOUNTS.find(name)
    if old is None:
        raise KeyError(f'No paper account called "{name}"')
    merged = {**old, **check({**changes, "settings": {**old["settings"], **(changes.get("settings") or {})}}
                             if "settings" in changes else changes)}
    return ACCOUNTS.replace(name, merged)


def rename(old: str, new: str) -> dict:
    return ACCOUNTS.rename(old, new)


def delete(name: str) -> None:
    item = ACCOUNTS.delete(name)
    if item:
        p = history_path(item["id"])
        if p.exists():
            p.rename(p.with_suffix(".json.deleted"))          # kept on the NAS, out of the way


def find(id_or_name: str) -> tuple[str, dict]:
    name, item = ACCOUNTS.find(id_or_name)
    if item is None:
        raise KeyError(f'No paper account called "{id_or_name}"')
    return name, item


# ---------------------------------------------------------------- history
def history_path(account_id: str) -> Path:
    return store.DATA_DIR / "user" / "paper" / f"{account_id}.json"


def history(item: dict) -> dict:
    h = jsonfile.read(history_path(item["id"]))
    return {"sessions": h.get("sessions") or [], "resets": h.get("resets") or [], "notes": h.get("notes") or {}}


def editing_history(item: dict):
    """The history to change in place (locked, written back atomically)."""
    return jsonfile.editing(history_path(item["id"]))


def _since_reset(h: dict) -> list[dict]:
    last = max((r["at"] for r in h["resets"]), default=0)
    return [s for s in h["sessions"] if s.get("started", 0) >= last]


def balance(item: dict) -> float:
    """Starting cash plus every session's result since the last reset (open sessions at their cash)."""
    h = history(item)
    return round(item["start_cash"] + sum(s["state"]["cash"] - s["state"]["start_cash"] for s in _since_reset(h)
                                          if s.get("state")), 2)


def reset(name: str) -> dict:
    """Back to the starting cash; the sessions before stay in the history, marked by the reset."""
    _, item = find(name)
    with editing_history(item) as h:
        h.setdefault("resets", []).append({"at": time.time(), "balance": balance(item)})
        for s in h.setdefault("sessions", []):
            s["archived"] = True                               # a session after the reset starts afresh
    return item
