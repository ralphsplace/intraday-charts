"""Named things the user saves from the chart page: chart views, window layouts and watchlists.

Kept on the server (in <data>/user/<kind>.json) so every browser and device that opens the dashboard
sees the same list.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from . import store

KINDS = ("views", "layouts", "watchlists", "structures")
NAME_MAX = 60
_NAME_RE = re.compile(rf"^[^\x00-\x1f/\\]{{1,{NAME_MAX}}}$")


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or "")) and name.strip() == name


def path(kind: str) -> Path:
    return store.DATA_DIR / "user" / f"{kind}.json"


@contextmanager
def _locked(kind: str):
    p = path(kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lock:     # the server runs several worker processes
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield p
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(p: Path, d: dict) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    os.replace(tmp, p)


def all_items(kind: str) -> dict:
    return _read(path(kind))


def put(kind: str, name: str, data) -> dict:
    with _locked(kind) as p:
        d = _read(p)
        d[name] = data
        _write(p, d)
        return d


def delete(kind: str, name: str) -> dict:
    with _locked(kind) as p:
        d = _read(p)
        d.pop(name, None)
        _write(p, d)
        return d
