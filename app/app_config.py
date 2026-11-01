"""The application config: the user's own settings for the whole app, in one file on the NAS
(data/user/config.json), edited on the Config page and read by every page, browser and device.

Sections (each optional; missing ones fall back to the built-in defaults):
    watchlists      {name: definition}       the named watch lists (app/watchlists.py)
    studies         {study type: {key: value}}  default settings for new studies (app/studies/base.py)
    watch_columns   {list kind: [column ids]}    each watch list type's default columns (app/watch_fields.py)
    paper_accounts  {name: account}          the named paper accounts (app/paper/accounts.py)
    paper           {"defaults": {...},      a new paper account's starting cash and settings,
                     "backtest": {...}}      and what a new backtest starts with
    paper_rules     {name: {"id", "rule"}}   the named paper trading rules (app/paper/rules.py)

One job: read and change sections, safely across the server's worker processes (a lock file), with the file
read again only when it has changed. config.json next to the app (default symbol, default layout) stays as it
is: it ships with the app and is mounted read-only.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path

from . import jsonfile, store

SECTIONS = ("watchlists", "studies", "watch_columns", "paper_accounts", "paper", "paper_rules")
_cache: dict = {}


def path() -> Path:
    return store.DATA_DIR / "user" / "config.json"


def read() -> dict:
    """The whole config (a copy)."""
    p = path()
    try:
        key = (str(p), p.stat().st_mtime_ns)
    except OSError:
        key = (str(p), None)
    if _cache.get("key") != key:
        _cache.update(key=key, data=jsonfile.read(p))
    return copy.deepcopy(_cache["data"])


def section(name: str) -> dict:
    if name not in SECTIONS:
        raise KeyError(name)
    v = read().get(name)
    return v if isinstance(v, dict) else {}


@contextmanager
def editing():
    """The config to change in place, written back atomically when the block ends without an error."""
    with jsonfile.editing(path()) as d:
        yield d


def put_section(name: str, value: dict) -> dict:
    if name not in SECTIONS:
        raise KeyError(name)
    with editing() as d:
        d[name] = value
    return value
