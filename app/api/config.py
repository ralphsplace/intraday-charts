"""The application config the Config page edits (app/app_config.py): study defaults and each watch list
kind's default columns."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException

from .. import app_config, studies, watch_fields, watchlists

router = APIRouter()

@router.get("/api/config")
def app_config_view():
    """Everything the Config page edits: study defaults (with the built-in ones), each watch list kind's default
    columns, and the named watch lists."""
    return {"studies": studies.catalog(), "watch_columns": watch_fields.catalog(), "watchlists": watchlists.all_lists(),
            "path": "data/user/config.json"}


@router.put("/api/config/studies/{type}")
def config_study_defaults(type: str, params: Annotated[dict, Body()]):
    """New defaults for a study: kept only where they differ from the built-in ones."""
    spec = studies.base.REGISTRY.get(type)
    if not spec:
        raise HTTPException(404, f"Unknown study '{type}'")
    full = studies.base.coerce(spec, params)
    mine = {p["key"]: full[p["key"]] for p in spec["params"] if p["key"] in params and full[p["key"]] != p["default"]}
    with app_config.editing() as d:
        st = d.setdefault("studies", {})
        if mine:
            st[type] = mine
        else:
            st.pop(type, None)
    return next(s for s in studies.catalog() if s["type"] == type)


@router.delete("/api/config/studies/{type}")
def config_study_reset(type: str):
    with app_config.editing() as d:
        d.setdefault("studies", {}).pop(type, None)
    return {"ok": True}


@router.put("/api/config/watch-columns/{kind}")
def config_watch_columns(kind: str, ids: Annotated[list[str], Body()]):
    try:
        cols = watch_fields.check_columns(kind, ids)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    with app_config.editing() as d:
        d.setdefault("watch_columns", {})[kind] = cols
    return watch_fields.catalog()


@router.delete("/api/config/watch-columns/{kind}")
def config_watch_columns_reset(kind: str):
    with app_config.editing() as d:
        d.setdefault("watch_columns", {}).pop(kind, None)
    return watch_fields.catalog()
