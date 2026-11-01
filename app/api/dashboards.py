"""Dashboards: create (empty, copied, or from a saved layout or template), rename, change settings, delete,
and choose the default (app/dashboards.py)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import dashboards, saved, templates

router = APIRouter()

class DashboardCreate(BaseModel):
    name: str
    type: str = "charts"
    copy_of: str | None = None          # id of a dashboard to copy
    start_layout: str | None = None     # charts: a saved window layout to start from
    start_template: str | None = None   # charts: or a built-in template (app/templates.py)
    start_rows: list[int] | None = None  # charts: or [top, bottom] charts, e.g. [3, 5]


class DashboardUpdate(BaseModel):
    name: str | None = None
    settings: dict | None = None


def _dash_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except dashboards.DashboardError as e:
        raise HTTPException(400, str(e)) from None
    except KeyError:
        raise HTTPException(404, "No such dashboard") from None


@router.get("/api/dashboards")
def dashboards_list():
    return {**dashboards.all_dashboards(), "types": dashboards.TYPES, "name_rule": dashboards.NAME_RULE,
            "templates": templates.labels(), "max_per_row": templates.MAX_PER_ROW}


@router.post("/api/dashboards")
def dashboards_create(req: DashboardCreate):
    settings = {}
    if req.start_layout:
        lay = saved.all_items("layouts").get(req.start_layout)
        if lay is None:
            raise HTTPException(404, f'No saved layout called "{req.start_layout}"')
        settings["start"] = lay
    elif req.start_template:
        settings["start"] = templates.start(req.start_template)
        if settings["start"] is None:
            raise HTTPException(404, f'No template called "{req.start_template}"')
    elif req.start_rows is not None:
        try:
            settings["start"] = templates.rows(*req.start_rows)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e) if isinstance(e, ValueError) else "start_rows is [top, bottom]") from None
    return _dash_call(dashboards.create, req.name.strip(), req.type, settings, req.copy_of)


@router.patch("/api/dashboards/{id}")
def dashboards_update(id: str, req: DashboardUpdate):
    if req.settings is not None and len(json.dumps(req.settings)) > 500_000:
        raise HTTPException(400, "too large")
    return _dash_call(dashboards.update, id, req.name.strip() if req.name is not None else None, req.settings)


@router.delete("/api/dashboards/{id}")
def dashboards_delete(id: str):
    return _dash_call(dashboards.delete, id)


@router.post("/api/dashboards/{id}/default")
def dashboards_default(id: str):
    return _dash_call(dashboards.set_default, id)
