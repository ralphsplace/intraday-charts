"""What a study may return. Every result is checked after the study runs (in run_study), so a malformed one fails
that study with a clear message on its legend entry instead of breaking the chart page.

Each kind of output is drawn by a module in app/static/js/outputs/ with the same name; tests/test_outputs.py
checks the two lists match. To add a kind: describe it here and add its drawing module there.
"""
from __future__ import annotations

from numbers import Real

NUM, TEXT, LIST, DICT = "number", "text", "list", "dict"

# kind: (one item or a list of items, the fields every item must have and their types)
OUTPUTS: dict[str, tuple[str, dict[str, str]]] = {
    "lines":      (LIST, {"id": TEXT, "data": LIST}),                 # series in the study's pane
    "histograms": (LIST, {"id": TEXT, "data": LIST}),
    "hlines":     (LIST, {"price": NUM}),                             # reference lines in the study's own pane
    "bands":      (LIST, {"from": NUM, "to": NUM, "color": TEXT}),    # shaded zones in the study's own pane
    "levels":     (LIST, {"price": NUM, "label": TEXT}),              # price-pane levels with axis labels
    "profile":    (DICT, {"bins": LIST, "side": TEXT}),               # volume-at-price histogram
    "cloud":      (DICT, {"points": LIST, "up": TEXT, "down": TEXT}),  # fill between two lines
    "box":        (DICT, {"start": NUM, "end": NUM, "high": NUM, "low": NUM}),  # opening-range box
    "verticals":  (LIST, {"time": NUM, "label": TEXT}),               # event lines
    "labels":     (LIST, {"text": TEXT, "bg": TEXT}),                 # coloured boxes at the top of the chart
}
OTHER = {"note": TEXT,       # text shown next to the study's name
         "needs": LIST}      # other symbols the study reads (e.g. SPY): the page asks the collector for them


def _is(value, kind: str) -> bool:
    if kind == NUM:
        return isinstance(value, Real) and not isinstance(value, bool)
    return isinstance(value, {TEXT: str, LIST: list, DICT: dict}[kind])


def problems(out: dict) -> list[str]:
    """What is wrong with a study's result, if anything (empty list: fine)."""
    found = []
    for key, value in out.items():
        if key in OTHER:
            if not _is(value, OTHER[key]):
                found.append(f"{key} should be {OTHER[key]}")
            elif key == "needs" and not all(isinstance(s, str) for s in value):
                found.append("needs should be a list of symbols")
            continue
        if key not in OUTPUTS:
            found.append(f"unknown output '{key}'")
            continue
        shape, fields = OUTPUTS[key]
        if not _is(value, shape):
            found.append(f"{key} should be a {shape}")
            continue
        for n, item in enumerate(value if shape == LIST else [value]):
            where = f"{key}[{n}]" if shape == LIST else key
            if not isinstance(item, dict):
                found.append(f"{where} should be a dict")
                continue
            found += [f"{where}.{f} should be {t}" for f, t in fields.items() if not _is(item.get(f), t)]
    return found
