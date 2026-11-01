"""Named watch lists: one set for the whole app, kept in the application config (app/app_config.py, section
"watchlists": name -> definition), so every dashboard, browser and device sees the same lists.

One job: what a list holds, by its source. The naming rules are shared with every app-wide named thing
(app/named.py): unique names, "Watch list N" for a new one, an id that never changes so a tab still finds its list
after a rename elsewhere, and a rename that's a move.

A definition is {"id", "source", ...} by source:
    symbols    {"symbols": [...]}                         typed or imported symbols
    finviz     {"feed": {"source", "address", "label"}}    a FinViz screen or portfolio (app/list_sources.py)
    holdings   {}                                         the account's positions (app/positions.py)
Lists saved by older versions are brought to this shape when the server starts (app/upgrade.py).
"""
from __future__ import annotations

from .named import Named

SOURCES = ("symbols", "finviz", "holdings")
DEFAULT = "Watch list"
MAX_SYMBOLS = 500
LISTS = Named("watchlists", DEFAULT, "watch list")     # unique names, ids, rename is a move (app/named.py)


def normal(value) -> dict:
    """A stored list with its source checked and its symbols capped (a hand edit may have left anything)."""
    v = dict(value) if isinstance(value, dict) else {}
    v.setdefault("id", None)
    v["source"] = v.get("source") if v.get("source") in SOURCES else "symbols"
    if v["source"] == "symbols":
        v["symbols"] = [str(s) for s in (v.get("symbols") or [])][:MAX_SYMBOLS]
    return v


def all_lists() -> dict:
    return {n: normal(v) for n, v in LISTS.items().items()}


def next_name(names) -> str:
    return LISTS.next_name(names)


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
    return LISTS.create(_clean(source, data or {}), name)


def update(name: str, source: str, data: dict) -> dict:
    """New contents for a list, keeping its name and id."""
    return LISTS.replace(name, _clean(source, data))


def rename(old: str, new: str) -> dict:
    """A list under a new name, the same id and contents: a move, never a copy."""
    return normal(LISTS.rename(old, new))


def delete(name: str) -> None:
    LISTS.delete(name)
