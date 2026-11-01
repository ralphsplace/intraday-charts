"""Named things saved from the chart page: views, layouts and option structures (app/saved.py). Watch lists
have their own endpoints (watch.py)."""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException

from .. import saved

router = APIRouter()


def _kind(kind: str) -> str:
    if kind not in saved.KINDS:
        raise HTTPException(404, "unknown kind")
    return kind


@router.get("/api/saved/{kind}")
def saved_list(kind: str):
    return saved.all_items(_kind(kind))


@router.put("/api/saved/{kind}/{name}")
def saved_put(kind: str, name: str, data: Annotated[Any, Body()]):
    _kind(kind)
    if not saved.valid_name(name):
        raise HTTPException(400, f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
    if len(json.dumps(data)) > 500_000:
        raise HTTPException(400, "too large")
    return saved.put(kind, name, data)


@router.delete("/api/saved/{kind}/{name}")
def saved_delete(kind: str, name: str):
    return saved.delete(_kind(kind), name)
