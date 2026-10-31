"""Named watch lists: one set for the whole app, kept in the application config (app/app_config.py, section
"watchlists": name -> definition), so every dashboard, browser and device sees the same lists.

One job: create, change, rename and delete them. A name is unique (it's the key); a new list is called
"Watch list N", N one more than the highest in use. Each list also has an id that never changes, so a watch list
tab that shows it still finds it after it's renamed elsewhere.

A definition is {"id", "source", ...} by source:
    symbols    {"symbols": [...]}                         typed or imported symbols
    finviz     {"feed": {"source", "address", "label"}}    a FinViz screen or portfolio (app/list_sources.py)
    holdings   {}                                         the account's positions (app/positions.py)
Lists saved before ids existed are plain symbol lists ([...]); they're given an id the first time the lists are
read, so a rename can never leave a tab behind on the old name.
"""
from __future__ import annotations

import re
import uuid

from . import app_config, saved

SOURCES = ("symbols", "finviz", "holdings")
DEFAULT = "Watch list"
MAX_SYMBOLS = 500
_N = re.compile(rf"^{DEFAULT} (\d+)$")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def normal(value) -> dict:
    """A stored list as an object (lists saved before ids existed are plain symbol lists)."""
    if isinstance(value, list):
        return {"id": None, "source": "symbols", "symbols": [str(s) for s in value][:MAX_SYMBOLS]}
    v = dict(value) if isinstance(value, dict) else {}
    v.setdefault("id", None)
    v["source"] = v.get("source") if v.get("source") in SOURCES else "symbols"
    if v["source"] == "symbols":
        v["symbols"] = [str(s) for s in (v.get("symbols") or [])][:MAX_SYMBOLS]
    return v


def all_lists() -> dict:
    lists = {n: normal(v) for n, v in app_config.section("watchlists").items()}
    if any(not v["id"] for v in lists.values()):              # older lists: give them ids, once
        with app_config.editing() as d:
            wl = d.setdefault("watchlists", {})
            for n, v in list(wl.items()):
                item = normal(v)
                if not item["id"]:
                    item["id"] = _new_id()
                wl[n] = item
        lists = {n: normal(v) for n, v in app_config.section("watchlists").items()}
    return lists


def next_name(names) -> str:
    used = [int(m.group(1)) for m in (_N.match(n) for n in names) if m]
    return f"{DEFAULT} {max(used, default=0) + 1}"


def _clean(source: str, data: dict) -> dict:
    if source not in SOURCES:
        raise ValueError(f"Unknown list source: {source}")
    out = {"source": source}
    if source == "symbols":
        syms = data.get("symbols") or []
        if not isinstance(syms, list):
            raise ValueError("symbols must be a list")
        out["symbols"] = [str(s)[:12] for s in syms][:MAX_SYMBOLS]
    elif source == "finviz":
        feed = data.get("feed") or {}
        if not isinstance(feed, dict) or not feed.get("address"):
            raise ValueError("A FinViz list needs its address")
        out["feed"] = {"source": "finviz", "address": str(feed["address"])[:4000], "label": str(feed.get("label", ""))[:200]}
    return out


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not saved.valid_name(name):
        raise ValueError(f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
    return name


def create(source: str, data: dict | None = None, name: str | None = None) -> tuple[str, dict]:
    """A new list, under `name` or the next default name; ValueError if the name is taken or invalid."""
    item = {"id": _new_id(), **_clean(source, data or {})}
    with app_config.editing() as d:
        wl = d.setdefault("watchlists", {})
        name = _check_name(name) if name else next_name(wl)
        if name in wl:
            raise ValueError(f'There is already a watch list called "{name}"')
        wl[name] = item
    return name, item


def update(name: str, source: str, data: dict) -> dict:
    """New contents for a list, keeping its name and id (one is given if it had none)."""
    with app_config.editing() as d:
        wl = d.setdefault("watchlists", {})
        old = normal(wl.get(name, []))
        item = {"id": old["id"] or _new_id(), **_clean(source, data)}
        wl[name] = item
    return item


def rename(old: str, new: str) -> dict:
    """A list under a new name, the same id and contents: a move, never a copy."""
    new = _check_name(new)
    with app_config.editing() as d:
        wl = d.setdefault("watchlists", {})
        if old not in wl:
            raise KeyError(f'No watch list called "{old}"')
        if new != old and new in wl:
            raise ValueError(f'There is already a watch list called "{new}"')
        item = normal(wl.pop(old))
        item["id"] = item["id"] or _new_id()
        wl[new] = item
    return item


def delete(name: str) -> None:
    with app_config.editing() as d:
        d.setdefault("watchlists", {}).pop(name, None)


def set_symbols(name: str, symbols: list) -> dict:
    """Load data's "Save as watchlist": a symbol list under `name`, keeping the id of a list it replaces."""
    _check_name(name)
    return update(name, "symbols", {"symbols": symbols})
