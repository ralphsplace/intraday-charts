"""Named things saved from the chart page (views, layouts, structures; app/saved.py). Watch lists saved here
(Load data's "Save as watchlist") go to the named watch lists instead."""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException

from .. import saved, watchlists

router = APIRouter()

@router.get("/api/saved/{kind}")
def saved_list(kind: str):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if kind == "watchlists":                       # kept in the application config (app/watchlists.py)
        return watchlists.all_lists()
    return saved.all_items(kind)


@router.put("/api/saved/{kind}/{name}")
def saved_put(kind: str, name: str, data: Annotated[Any, Body()]):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if not saved.valid_name(name):
        raise HTTPException(400, f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
    if len(json.dumps(data)) > 500_000:
        raise HTTPException(400, "too large")
    if kind == "watchlists":                       # Load data's "Save as watchlist": keep the list's id
        if not isinstance(data, list):
            raise HTTPException(400, "A watchlist saved here is a list of symbols")
        watchlists.set_symbols(name, data)
        return watchlists.all_lists()
    return saved.put(kind, name, data)


@router.delete("/api/saved/{kind}/{name}")
def saved_delete(kind: str, name: str):
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    if kind == "watchlists":
        watchlists.delete(name)
        return watchlists.all_lists()
    return saved.delete(kind, name)
