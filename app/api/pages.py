"""The HTML pages, and the page files under a versioned address so every browser loads new files after an
update. The router goes last: /{name} (a dashboard by name) would otherwise catch other pages' addresses."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import dashboards
from .common import ROOT

router = APIRouter()


def _static_version() -> str:
    """A fingerprint of the page files: it changes with every update that changes any of them."""
    h = hashlib.sha256()
    for f in sorted((ROOT / "static").rglob("*")):
        if f.is_file():
            h.update(f.relative_to(ROOT).as_posix().encode() + b"\0" + f.read_bytes())
    return "_v" + h.hexdigest()[:10]


STATIC_VERSION = _static_version()
_VERSION_DIR = re.compile(r"^_v[0-9a-f]{10}$")


class Revalidated(StaticFiles):
    """The page files. Pages ask for them under a versioned address, /static/_v<fingerprint>/js/main.js, so after an
    update every browser fetches the new files instead of reusing old ones it kept (the scripts' own imports are
    relative, so they follow the version). Any version is served the current files. And the browser must still
    check with the server before reusing a file (a cheap "not modified" when unchanged)."""

    def get_path(self, scope) -> str:
        head, sep, rest = super().get_path(scope).partition(os.sep)
        return rest if sep and _VERSION_DIR.match(head) else super().get_path(scope)

    def file_response(self, *a, **kw):
        r = super().file_response(*a, **kw)
        r.headers["Cache-Control"] = "no-cache"
        return r


PAGES = {"charts": "index.html"}


def _page(file: str, dash: dict | None = None) -> HTMLResponse:
    page = (ROOT / "static" / file).read_text().replace('"/static/', f'"/static/{STATIC_VERSION}/')
    if dash is not None:
        info = {"id": dash["id"], "name": dash["name"], "type": dash["type"], "settings": dash.get("settings", {}),
                "legacy": dash["id"] == "main", "copied_from": dash.get("copied_from")}
        page = page.replace("<!--DASHBOARD-->", "<script>window.DASHBOARD = " +
                            json.dumps(info).replace("<", "\\u003c") + ";</script>")
        page = page.replace("<title>", f"<title>{dash['name']} · ", 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/earnings")
def earnings_page():
    return _page("earnings.html")


@router.get("/expected-move")
def expected_move_page():
    return _page("expected-move.html")


@router.get("/options")
def options_page():
    return _page("options.html")


@router.get("/paper")
def paper_page():
    return _page("paper.html")


@router.get("/config")
def config_page():
    return _page("config.html")


@router.get("/")
def index():
    d = dashboards.default()
    return _page(PAGES[d["type"]], d)


@router.get("/dashboards")
def dashboards_page():
    """The dashboards are managed on the Config page now; old links and bookmarks land there."""
    return RedirectResponse("/config?tab=dashboards", status_code=307)


@router.get("/{name}")
def dashboard_page(name: str):
    d = dashboards.find(name)
    if not d:
        return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>No such dashboard</title>
<body style="font:15px system-ui;background:#0b0d10;color:#e3e6ea;padding:40px">
<p>There is no dashboard called <b>{html.escape(name)}</b>.</p>
<p><a style="color:#7fb8ff" href="/config?tab=dashboards">Manage dashboards</a> · <a style="color:#7fb8ff" href="/">Default dashboard</a></p>""",
                            status_code=404)
    return _page(PAGES[d["type"]], d)
