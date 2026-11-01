"""Named things the user saves from the chart page: chart views, window layouts and option structures.

Kept on the server (in <data>/user/<kind>.json) so every browser and device that opens the dashboard
sees the same list.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import jsonfile, store

KINDS = ("views", "layouts", "structures")
NAME_MAX = 60
_NAME_RE = re.compile(rf"^[^\x00-\x1f/\\]{{1,{NAME_MAX}}}$")


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or "")) and name.strip() == name


def path(kind: str) -> Path:
    return store.DATA_DIR / "user" / f"{kind}.json"


def all_items(kind: str) -> dict:
    return jsonfile.read(path(kind))


def put(kind: str, name: str, data) -> dict:
    with jsonfile.editing(path(kind)) as d:
        d[name] = data
    return d


def delete(kind: str, name: str) -> dict:
    with jsonfile.editing(path(kind)) as d:
        d.pop(name, None)
    return d
