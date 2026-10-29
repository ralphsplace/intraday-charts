"""Named dashboards, each opened at its own address: http://<nas>:8050/<name>.

Kept in <data>/user/dashboards.json so every browser sees the same list:
    {"default": "<id>", "items": [{"id", "name", "type", "settings"}, ...]}

Each dashboard is the chart page (one chart by default; the Layout menu adds more). Its window state is kept
per browser, under the dashboard's id; "settings.start" (a saved window layout or a built-in template) is what a
browser sees the first time.

Built-in dashboards (templates.SEEDED, e.g. Internals) are added once, with the template's id as their id; the
file remembers which were added ("seeded"), so one you delete stays deleted.
"""
from __future__ import annotations

import re
import uuid

from . import saved, templates

TYPES = {"charts": "Charts"}
RESERVED = {"dashboards", "earnings", "expected-move", "options", "api", "static", "favicon.ico"}   # other pages' addresses
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
NAME_RULE = "1 to 40 letters, digits, - _ or . (it becomes the page address), starting with a letter or digit"
KIND = "dashboards"

SEED = {"default": "main",
        "items": [{"id": "main", "name": "QQQs", "type": "charts", "settings": {}}]}


class DashboardError(ValueError):
    pass


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or "")) and name.lower() not in RESERVED


def _clean(d) -> dict:
    """Seed the file the first time; repair anything malformed; add built-in dashboards not added before."""
    if not isinstance(d, dict) or not isinstance(d.get("items"), list) or not d["items"]:
        d = {"default": SEED["default"], "items": [dict(i, settings={}) for i in SEED["items"]],
             "seeded": d.get("seeded", []) if isinstance(d, dict) else []}
    items = [i for i in d["items"] if isinstance(i, dict) and i.get("id") and i.get("name") and i.get("type") in TYPES]
    for i in items:
        i.setdefault("settings", {})
    if not items:
        return _clean(None)
    if d.get("default") not in {i["id"] for i in items}:
        d["default"] = items[0]["id"]
    seeded = [s for s in d.get("seeded", []) if isinstance(s, str)]
    for key, name in templates.SEEDED.items():
        if key in seeded:
            continue
        seeded.append(key)
        if not any(i["name"].lower() == name.lower() or i["id"] == key for i in items):
            items.append({"id": key, "name": name, "type": "charts", "settings": {"start": templates.start(key)}})
    return {"default": d["default"], "items": items, "seeded": seeded}


def all_dashboards() -> dict:
    return _clean(saved._read(saved.path(KIND)))


def find(name_or_id: str) -> dict | None:
    """By name (any letter case) or id."""
    key = (name_or_id or "").lower()
    d = all_dashboards()
    return next((i for i in d["items"] if i["name"].lower() == key or i["id"] == name_or_id), None)


def default() -> dict:
    d = all_dashboards()
    return next(i for i in d["items"] if i["id"] == d["default"])


def _mutate(fn):
    with saved._locked(KIND) as p:
        d = _clean(saved._read(p))
        out = fn(d)
        saved._write(p, d)
        return out if out is not None else d


def _check_name(d, name, except_id=None):
    if not valid_name(name):
        raise DashboardError(f"Dashboard names are {NAME_RULE}; not one of: dashboards, api, static.")
    if any(i["name"].lower() == name.lower() and i["id"] != except_id for i in d["items"]):
        raise DashboardError(f'There is already a dashboard called "{name}".')


def create(name: str, type: str, settings: dict | None = None, copy_of: str | None = None) -> dict:
    if type not in TYPES:
        raise DashboardError("type must be one of: " + ", ".join(TYPES))

    def fn(d):
        _check_name(d, name)
        src = next((i for i in d["items"] if i["id"] == copy_of), None) if copy_of else None
        item = {"id": uuid.uuid4().hex[:8], "name": name, "type": src["type"] if src else type,
                "settings": dict(src["settings"]) if src else dict(settings or {})}
        if src:
            item["copied_from"] = src["id"]
        d["items"].append(item)
        return item
    return _mutate(fn)


def update(id: str, name: str | None = None, settings: dict | None = None) -> dict:
    def fn(d):
        item = next((i for i in d["items"] if i["id"] == id), None)
        if not item:
            raise KeyError(id)
        if name is not None and name != item["name"]:
            _check_name(d, name, except_id=id)
            item["name"] = name
        if settings is not None:
            item["settings"] = settings
        return item
    return _mutate(fn)


def delete(id: str) -> dict:
    def fn(d):
        if not any(i["id"] == id for i in d["items"]):
            raise KeyError(id)
        if len(d["items"]) == 1:
            raise DashboardError("This is the only dashboard; create another before deleting it.")
        d["items"] = [i for i in d["items"] if i["id"] != id]
        if d["default"] == id:
            d["default"] = d["items"][0]["id"]
    return _mutate(fn)


def set_default(id: str) -> dict:
    def fn(d):
        if not any(i["id"] == id for i in d["items"]):
            raise KeyError(id)
        d["default"] = id
    return _mutate(fn)
