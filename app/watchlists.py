"""Named watch lists: one list of named watch lists for the whole app, kept on the NAS (data/user/watchlists.json,
the same file Load data saves to), so every dashboard, browser and device sees the same lists.

One job: create, change, rename and delete them. A name is unique (it's the key); a new list is called
"Watch list N", N one more than the highest in use. Each list also has an id that never changes, so a watch list
tab that shows it still finds it after it's renamed elsewhere.

A list is {"id", "source", ...} by source:
    symbols    {"symbols": [...]}                         typed or imported symbols
    finviz     {"feed": {"source", "address", "label"}}    a FinViz screen or portfolio (app/list_sources.py)
    holdings   {}                                         the account's positions (app/positions.py)
Lists saved before ids existed are plain symbol lists ([...]); they're read as source "symbols" and given an id
the first time they're changed.
"""
from __future__ import annotations

import re
import uuid

from . import saved

KIND = "watchlists"
SOURCES = ("symbols", "finviz", "holdings")
DEFAULT = "Watch list"
MAX_SYMBOLS = 500
_N = re.compile(rf"^{DEFAULT} (\d+)$")


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
    return {n: normal(v) for n, v in saved.all_items(KIND).items()}


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


def create(source: str, data: dict | None = None, name: str | None = None) -> tuple[str, dict]:
    """A new list, under `name` or the next default name; ValueError if the name is taken or invalid."""
    item = {"id": uuid.uuid4().hex[:12], **_clean(source, data or {})}
    with saved._locked(KIND) as p:
        d = saved._read(p)
        name = name or next_name(d)
        if not saved.valid_name(name):
            raise ValueError(f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
        if name in d:
            raise ValueError(f'There is already a watch list called "{name}"')
        d[name] = item
        saved._write(p, d)
    return name, item


def update(name: str, source: str, data: dict) -> dict:
    """New contents for a list, keeping its name and id (one is given if it had none)."""
    with saved._locked(KIND) as p:
        d = saved._read(p)
        old = normal(d.get(name, []))
        item = {"id": old["id"] or uuid.uuid4().hex[:12], **_clean(source, data)}
        d[name] = item
        saved._write(p, d)
    return item


def rename(old: str, new: str) -> dict:
    new = (new or "").strip()
    if not saved.valid_name(new):
        raise ValueError(f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
    with saved._locked(KIND) as p:
        d = saved._read(p)
        if old not in d:
            raise KeyError(f'No watch list called "{old}"')
        if new != old and new in d:
            raise ValueError(f'There is already a watch list called "{new}"')
        item = normal(d.pop(old))
        item["id"] = item["id"] or uuid.uuid4().hex[:12]
        d[new] = {k: v for k, v in item.items()}
        saved._write(p, d)
    return item


def delete(name: str) -> None:
    saved.delete(KIND, name)


def set_symbols(name: str, symbols: list) -> dict:
    """Load data's "Save as watchlist": a symbol list under `name`, keeping the id of a list it replaces."""
    return update(name, "symbols", {"symbols": symbols})
