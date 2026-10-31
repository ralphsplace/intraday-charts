"""The application config: the user's own settings for the whole app, in one file on the NAS
(data/user/config.json), edited on the Config page and read by every page, browser and device.

Sections (each optional; missing ones fall back to the built-in defaults):
    watchlists      {name: definition}       the named watch lists (app/watchlists.py)
    studies         {study type: {key: value}}  default settings for new studies (app/studies/base.py)
    watch_columns   {list kind: [column ids]}    each watch list type's default columns (app/watch_fields.py)

One job: read and change sections, safely across the server's worker processes (a lock file), with the file
read again only when it has changed. config.json next to the app (default symbol, default layout) stays as it
is: it ships with the app and is mounted read-only.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from . import store

SECTIONS = ("watchlists", "studies", "watch_columns")
_cache: dict = {}


def path() -> Path:
    return store.DATA_DIR / "user" / "config.json"


def _read_file(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _legacy_watchlists() -> dict:
    """Watch lists kept in their own file before the application config existed (Load data's saves)."""
    return _read_file(store.DATA_DIR / "user" / "watchlists.json")


def read() -> dict:
    """The whole config (a copy), with watch lists from the older file if the config has none yet."""
    p = path()
    try:
        key = (str(p), p.stat().st_mtime_ns)
    except OSError:
        key = (str(p), None)
    if _cache.get("key") != key:
        _cache.update(key=key, data=_read_file(p))
    d = copy.deepcopy(_cache["data"])
    if "watchlists" not in d:
        d["watchlists"] = _legacy_watchlists()
    return d


def section(name: str) -> dict:
    if name not in SECTIONS:
        raise KeyError(name)
    v = read().get(name)
    return v if isinstance(v, dict) else {}


@contextmanager
def editing():
    """The config to change in place, written back atomically when the block ends without an error."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            d = _read_file(p)
            if "watchlists" not in d:
                d["watchlists"] = _legacy_watchlists()        # moved in on the first change
            yield d
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
            os.replace(tmp, p)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def put_section(name: str, value: dict) -> dict:
    if name not in SECTIONS:
        raise KeyError(name)
    with editing() as d:
        d[name] = value
    return value
