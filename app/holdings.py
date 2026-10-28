"""Fund holdings for the Heavyweights study: the weights shipped in app/heavyweights.json, replaced fund by fund by
data/heavyweights.json when you keep your own (it survives updates). The app makes no internet requests, so these
are a dated snapshot: the study shows the date."""
from __future__ import annotations

import json
from pathlib import Path

from . import control, store

SHIPPED = Path(__file__).with_name("heavyweights.json")


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def fund(symbol: str) -> dict | None:
    """{"as_of", "source", "weights": {symbol: % of the fund}} heaviest first, or None when the fund isn't listed."""
    symbol = symbol.upper()
    f = _read(store.DATA_DIR / "heavyweights.json").get(symbol) or _read(SHIPPED).get(symbol)
    if not isinstance(f, dict) or not isinstance(f.get("weights"), dict):
        return None
    w = {}
    for s, v in f["weights"].items():
        sym = control.clean_symbol(str(s))
        if sym and isinstance(v, (int, float)) and v > 0:
            w[sym] = float(v)
    w = dict(sorted(w.items(), key=lambda kv: -kv[1]))
    return {"as_of": str(f.get("as_of", "")), "source": str(f.get("source", "")), "weights": w} if w else None
