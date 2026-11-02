"""Upgrade what older versions saved on the server, once, when the server starts.

One job: bring the user's saved data up to the current shapes, so the rest of the code reads one shape only. It
is safe to run any number of times (an upgraded file is left alone) and from several server processes at once
(every change goes through the locked, atomic writes of app/jsonfile.py). Each change is logged.

What it upgrades:
  - data/user/watchlists.json, the watch lists from before the application config: moved into config.json
    (a list already in the config wins), and the old file renamed to watchlists.json.moved;
  - watch lists saved as plain symbol arrays or without an id: given the current shape and an id;
  - in saved views, saved layouts and the dashboards' starting layouts:
      a chart saved with a price style name ("style": "hollow") gets the price type it stands for;
      a watch list panel saved before tabs gets one tab; a tab saved before lists were named gets a named list
      of its own ("Watch list N", or its old name when free), or the id of the list it names;
      a watch list linked to one chart by the chart's id gets a colour group shared with that chart;
  - paper trading rules from before strategies (#67), each with its own long, short and exit conditions: each
    list of conditions becomes a rule ("<name> long", "<name> short", "<name> exit long", "<name> exit short") and
    the rest a strategy of the old rule's name that trades on them, the same way.
"""
from __future__ import annotations

import copy
import logging

from . import app_config, jsonfile, named, saved, store, watchlists

log = logging.getLogger("intraday-charts")

# price style names saved before price types: the type and settings each stands for (as app/static/js/pricetypes.js)
STYLES = {"candles": ("candles", {}), "hollow": ("candles", {"up_fill": False}), "heikin": ("heikin", {}),
          "bars": ("bars", {}), "line": ("line", {}), "area": ("area", {})}
GROUPS = ("red", "green", "blue", "yellow", "purple", "orange")      # link colour groups (app/static/js/links.js)
SPECIAL = {"": "symbols", "@feed": "finviz", "@holdings": "holdings"}  # list values of tabs before named lists
_checking = False      # while only checking whether a file needs upgrading: change nothing outside the copy


def run() -> list[str]:
    """Upgrade everything; what changed, one line each (also logged)."""
    done = []
    for part in (_watchlists_file, _list_shapes, _saved_layouts, _paper_rules):
        try:
            done += part()
        except jsonfile.BrokenFile as e:                    # a hand edit to fix first: start anyway, say so
            done.append(f"skipped: {e}")
    for line in done:
        log.warning("upgrade: %s", line)
    return done


# ---------------------------------------------------------------- watch lists
def _watchlists_file() -> list[str]:
    old = store.DATA_DIR / "user" / "watchlists.json"
    if not old.exists():
        return []
    lists = jsonfile.read(old)
    with app_config.editing() as d:
        wl = d.setdefault("watchlists", {})
        moved = [n for n in lists if n not in wl]
        for n in moved:
            wl[n] = lists[n]
    old.rename(old.with_suffix(".json.moved"))
    return [f"moved {len(moved)} watch list(s) from watchlists.json into config.json"]


def _list_shape(v) -> dict | None:
    """A list in the current shape, or None when it already is."""
    if isinstance(v, list):
        return {"id": named.new_id(), "source": "symbols", "symbols": [str(s) for s in v][:watchlists.MAX_SYMBOLS]}
    if isinstance(v, dict) and not v.get("id"):
        return {**v, "id": named.new_id()}
    return None


def _list_shapes() -> list[str]:
    if not any(_list_shape(v) for v in app_config.section("watchlists").values()):
        return []
    n = 0
    with app_config.editing() as d:
        wl = d.setdefault("watchlists", {})
        for name, v in list(wl.items()):
            new = _list_shape(v)
            if new:
                wl[name], n = new, n + 1
    return [f"gave {n} watch list(s) the current shape and an id"]


# ---------------------------------------------------------------- saved views, layouts and dashboards
def _chart(c: dict) -> bool:
    if "style" not in c:
        return False
    style = c.pop("style")
    if not (isinstance(c.get("price"), dict) and c["price"].get("type")):
        t, params = STYLES.get(style, STYLES["candles"])
        c["price"] = {"type": t, "params": dict(params)}
    return True


def _tab(t: dict, panel_name: str | None) -> bool:
    """A tab saved before lists were named: a named list of its own, or the id of the list it names."""
    if t.get("listId"):
        return False
    lst = t.get("list") or ""
    symbols = [str(s) for s in (t.get("symbols") or [])]
    lists = watchlists.all_lists()
    if lst not in SPECIAL and not symbols:                       # names a list: find its id
        if lst in lists:
            t["listId"] = lists[lst]["id"]
            return True
        return False
    if _checking:
        return True
    source = SPECIAL.get(lst, "symbols")
    feed = t.get("feed") or {}
    if source == "finviz" and not feed.get("address"):
        t.update(list="", listId=None)
    else:
        data = {"symbols": symbols} if source == "symbols" else {"feed": feed} if source == "finviz" else {}
        name = panel_name if panel_name and panel_name != watchlists.DEFAULT and panel_name not in lists else None
        name, item = watchlists.create(source, data, name)
        t.update(list=name, listId=item["id"])
    t.pop("symbols", None)
    t.pop("feed", None)
    t.pop("name", None)
    return True


def _watch_panel(c: dict) -> bool:
    changed = False
    if not (isinstance(c.get("tabs"), list) and c["tabs"]):
        c["tabs"] = [{"id": named.new_id(), "list": c.get("list") or "", "symbols": c.get("symbols") or [],
                      "feed": c.get("feed"), "columns": None}]
        changed = True
    for t in c["tabs"]:
        if isinstance(t, dict):
            changed |= _tab(t, t.get("name"))
    for k in ("symbols", "list", "feed"):
        changed |= c.pop(k, None) is not None
    return changed


def _links(configs: list) -> bool:
    """A watch list linked to one chart by the chart's id: both join the first colour group not in use."""
    used = {c.get("link") for c in configs if isinstance(c, dict) and c.get("link") in GROUPS}
    changed = False
    for c in configs:
        if not isinstance(c, dict) or not c.get("link") or c["link"] in GROUPS:
            continue
        chart = next((x for x in configs if c.get("kind") == "watchlist" and isinstance(x, dict) and x is not c
                      and x.get("id") == c["link"]), None)
        group = ""
        if chart is not None:
            group = chart["link"] if chart.get("link") in GROUPS else next((g for g in GROUPS if g not in used), "")
            if group:
                chart["link"] = group
                used.add(group)
        c["link"] = group
        changed = True
    return changed


def _configs(configs) -> bool:
    if not isinstance(configs, list):
        return False
    changed = False
    for c in configs:
        if isinstance(c, dict):
            changed |= _watch_panel(c) if c.get("kind") == "watchlist" else _chart(c)
    return _links(configs) | changed


def _layout(lay) -> bool:
    return isinstance(lay, dict) and _configs(lay.get("configs"))


def _needs(each, values) -> bool:
    global _checking
    _checking = True
    try:
        return any([each(copy.deepcopy(v)) for v in values])
    finally:
        _checking = False


def _upgrade_file(kind: str, each) -> int:
    p = saved.path(kind)
    if not p.exists() or not _needs(each, jsonfile.read(p).values()):
        return 0
    n = 0
    with jsonfile.editing(p) as d:
        for v in d.values():
            n += bool(each(v))
    return n


def _saved_layouts() -> list[str]:
    out = []
    for kind, each in (("views", lambda v: isinstance(v, dict) and _chart(v)), ("layouts", _layout)):
        n = _upgrade_file(kind, each)
        if n:
            out.append(f"upgraded {n} saved {kind[:-1]}(s)")
    n = _upgrade_file("dashboards", _dashboards)
    if n:
        out.append("upgraded the dashboards' starting layouts")
    return out


def _dashboards(v) -> bool:
    """dashboards.json is {"default": id, "items": [...]}: each item's settings.start is a layout."""
    if not isinstance(v, list):
        return False
    return any([_layout((i.get("settings") or {}).get("start")) for i in v if isinstance(i, dict)])


# ---------------------------------------------------------------- paper trading rules (#67)
def _old_rule(v) -> bool:
    return isinstance(v, dict) and isinstance(v.get("rule"), dict) and "when" not in v


def _paper_rules() -> list[str]:
    from .paper import expr
    if not any(_old_rule(v) for v in app_config.section("paper_rules").values()):
        return []
    done = []
    with app_config.editing() as d:
        rs, sts = d.setdefault("paper_rules", {}), d.setdefault("paper_strategies", {})
        for name in [n for n, v in rs.items() if _old_rule(v)]:
            old = rs.pop(name)["rule"]
            ex = old.get("exits") or {}
            within = old.get("within", 1) if isinstance(old.get("within"), int) else 1
            parts = (("buy", "long", old.get("long"), within), ("short", "short", old.get("short"), within),
                     ("exit_long", "exit long", ex.get("exit_long"), 1), ("exit_short", "exit short", ex.get("exit_short"), 1))
            st = {k: old[k] for k in ("tf", "order", "qty", "hours") if k in old}
            st["exits"] = {k: ex[k] for k in ("stop", "target", "trail", "reverse") if k in ex}
            made = []
            for key, label, conds, n in parts:
                st[key] = ""
                if not conds:
                    continue
                letters = [chr(65 + i) for i in range(len(conds[:26]))]
                when = " AND ".join(letters)
                if n > 1 and len(letters) > 1:                    # all within n bars, one of them on this bar
                    when = " AND ".join(f"WITHIN {n} {x}" for x in letters) + " AND (" + " OR ".join(letters) + ")"
                rname, k = f"{name} {label}", 2
                while rname in rs:
                    rname, k = f"{name} {label} {k}", k + 1
                rs[rname] = {"id": named.new_id(), "conditions": conds[:26], "when": when}
                st[key] = expr.text({"rule": rname})
                made.append(rname)
            sname, k = name, 2
            while sname in sts:
                sname, k = f"{name} {k}", k + 1
            sts[sname] = {"id": named.new_id(), **st}
            done.append(f'paper rule "{name}" became rules {", ".join(made)} and strategy "{sname}"')
    return done
