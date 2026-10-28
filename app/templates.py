"""Built-in starting layouts for dashboards: what a browser sees the first time it opens a dashboard made from one
(the same shape as a saved window layout: layout, configs, prefs). Offered under "Start from" on the Dashboards
page; dashboards.py also creates one dashboard from each template in SEEDED.

Studies are listed by type with the settings that differ from their defaults; the chart page fills in the rest.
"""
from __future__ import annotations

import copy


def _chart(symbol, tf, days, price="candles", price_params=None, studies=()):
    return {"symbol": symbol, "tf": tf, "days": days, "price": {"type": price, "params": price_params or {}},
            "studies": [{"type": t, "params": p} for t, p in studies]}


TREND = [("ma_cloud", {}), ("bollinger", {})]          # EMA 9/21 cloud and Bollinger (20, 2)

TEMPLATES = {
    "internals": {
        "label": "Market internals: QQQ and SPY over $VOLD, −VIX, $TICK, $ADD",
        "start": {
            "layout": "2/4",
            "configs": [
                _chart("QQQ", 3, 2),
                _chart("SPY", 3, 2),
                _chart("VOLD-NYSE", 5, 2, "line", studies=[("ema", {"length": 8})]),     # up - down volume
                _chart("-VIX", 3, 3, studies=TREND),                                      # VIX upside down
                _chart("TICK-NYSE", 3, 3, "line", studies=[("session_levels", {           # regular-hours high / low
                    "premarket": False, "opening_range": False, "or_box": False, "projection": False})]),
                _chart("ADD-NYSE", 5, 2, studies=TREND),                                  # advancing - declining
            ],
            "prefs": {"fitLevels": False, "extShade": True, "sync": True},
        },
    },
}

SEEDED = {"internals": "Internals"}     # template -> name of the dashboard created from it once


MAX_PER_ROW = 6            # charts in one row; app/static/js/layouts.js has the same limit


def rows(top: int, bottom: int) -> dict:
    """A start of `top` charts over `bottom` charts, each a fresh chart (the chart page fills them in)."""
    for n in (top, bottom):
        if not isinstance(n, int) or not 1 <= n <= MAX_PER_ROW:
            raise ValueError(f"Top and bottom must each be 1 to {MAX_PER_ROW} charts")
    return {"layout": f"{top}/{bottom}", "configs": [], "prefs": {}}


def labels() -> dict:
    return {k: t["label"] for k, t in TEMPLATES.items()}


def start(key: str) -> dict | None:
    t = TEMPLATES.get(key)
    return copy.deepcopy(t["start"]) if t else None
