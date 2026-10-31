"""Watch lists filled from an outside source, e.g. a FinViz screen or portfolio.

One job: turn what the page sends (an address copied from the source's site) into a checked, normalized
reference, and read and write the symbols fetched for it. No network here: the TWS collector does the fetching
(tools/list_sources.py), and only for a source turned on in .env.

A reference is {"source", "kind", "query"}. Only the parts a source needs are kept, each checked against a
narrow pattern, and the address the collector fetches is rebuilt from them; nothing typed on the page is
fetched as it stands, and an address's sign-in token (FinViz's auth=) is dropped: the token lives only in .env.

Each source has the same shape, so another one is one more class in SOURCES:
    name                     shown on the page
    switch                   the environment variable that says it's turned on
    normalize(text) -> ref   or ValueError with a message for the page
    label(ref) -> str        a short description of the list
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from . import store

STALE_SECONDS = 15 * 60          # an older list is fetched again when a page shows it
MAX_SYMBOLS = 500                # kept per list (a watch list shows the first 100)
_VALUE = re.compile(r"^[A-Za-z0-9_.,\-]{1,2000}$")


class FinViz:
    name = "FinViz"
    switch = "FINVIZ"                       # set by docker-compose when FINVIZ_TOKEN is set (the token stays in the collector)
    hosts = {"finviz.com", "www.finviz.com", "elite.finviz.com"}
    pages = {"screener.ashx": "screener", "export.ashx": "screener",
             "portfolio.ashx": "portfolio", "portfolio_export.ashx": "portfolio"}
    keep = {"screener": ("v", "f", "o", "s", "t"), "portfolio": ("pid",)}

    @classmethod
    def normalize(cls, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("Paste the address of a FinViz screen or portfolio")
        if "://" not in text and not text.startswith(("finviz.com", "www.finviz.com", "elite.finviz.com")):
            if "=" not in text:
                raise ValueError("That isn't a FinViz screen or portfolio address")
            text = "https://finviz.com/screener.ashx?" + text.lstrip("?")      # just the screen's settings
        u = urlsplit(text if "://" in text else "https://" + text)
        if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in cls.hosts:
            raise ValueError("Only finviz.com addresses are accepted")
        kind = cls.pages.get(u.path.rsplit("/", 1)[-1].lower())
        if not kind:
            raise ValueError("Use the address of a FinViz screener or portfolio page")
        params = dict(parse_qsl(u.query, keep_blank_values=False))
        kept = []
        for k in cls.keep[kind]:
            v = params.get(k)
            if v is None:
                continue
            if not _VALUE.match(v):
                raise ValueError(f"FinViz setting {k}= has characters it never uses")
            kept.append((k, v))
        if kind == "portfolio" and not any(k == "pid" for k, _ in kept):
            raise ValueError("A FinViz portfolio address needs its pid=")
        if kind == "portfolio" and not params["pid"].isdigit():
            raise ValueError("A FinViz portfolio's pid= is a number")
        if kind == "screener" and not any(k in ("f", "s", "t") for k, _ in kept):
            raise ValueError("That screen has no filters: it would list every stock FinViz knows")
        return {"source": "finviz", "kind": kind, "query": urlencode(kept, safe=",")}

    @staticmethod
    def label(ref: dict) -> str:
        q = dict(parse_qsl(ref["query"]))
        if ref["kind"] == "portfolio":
            return f"FinViz portfolio {q.get('pid')}"
        parts = [p for p in (q.get("s"), q.get("f")) if p]
        return "FinViz screen: " + (" ".join(parts) if parts else q.get("t", ""))[:120]


SOURCES = {"finviz": FinViz}


def source(name: str):
    if name not in SOURCES:
        raise ValueError(f"Unknown list source: {name}")
    return SOURCES[name]


def turned_on(name: str) -> bool:
    return bool(os.environ.get(source(name).switch, "").strip())


def normalize(name: str, text: str) -> dict:
    return source(name).normalize(text)


def valid(ref) -> bool:
    """A reference as sent back by the collector or the page: re-checked, never trusted."""
    try:
        return isinstance(ref, dict) and normalize(ref.get("source", ""), address(ref)) == ref
    except (ValueError, KeyError, TypeError):
        return False


def address(ref: dict) -> str:
    """The list's page on the source's site, rebuilt from the reference (without any sign-in token)."""
    page = "portfolio.ashx" if ref.get("kind") == "portfolio" else "screener.ashx"
    return f"https://finviz.com/{page}?{ref.get('query', '')}"


def key(ref: dict) -> str:
    return hashlib.sha256(json.dumps(ref, sort_keys=True).encode()).hexdigest()[:20]


def path(ref: dict) -> Path:
    return store.DATA_DIR / "lists" / f"{key(ref)}.json"


def read(ref: dict) -> dict | None:
    try:
        d = json.loads(path(ref).read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def write(ref: dict, data: dict) -> None:
    p = path(ref)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "ref": ref}, indent=1))
    tmp.replace(p)


def view(ref: dict) -> dict:
    """What the page shows for a list: its symbols when fetched, and whether to ask for them (again)."""
    src = source(ref["source"])
    out = {"ref": ref, "address": address(ref), "label": src.label(ref), "source_name": src.name, "on": turned_on(ref["source"]),
           "stale_seconds": STALE_SECONDS}
    d = read(ref)
    if not d:
        return {**out, "status": "missing", "symbols": []}
    age = time.time() - d["fetched"] if d.get("fetched") else None
    return {**out, "status": d.get("status", "error"), "symbols": d.get("symbols", [])[:MAX_SYMBOLS],
            "fields": d.get("fields") or {},
            "total": d.get("total"), "message": d.get("message"), "fetched": d.get("fetched"),
            "age": round(age) if age is not None else None, "stale": age is None or age > STALE_SECONDS}
