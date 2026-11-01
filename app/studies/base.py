"""The study interface, shared by every study module.

A study is registered with @study(...) and declares
  - category ("Overlays", "Oscillators", "Volume", "Profiles", "Levels", "Market internals"), one per module,
  - pane: "price" (drawn on the candles), "own" (its own pane below), or "volume" (bottom of the price pane),
  - params: the inputs shown in its settings dialog,
  - plots: the lines it draws; each gets Color, Line type, Thickness and Transparency settings automatically,
  - compute(ctx, params) -> outputs the chart knows how to draw.

Outputs (all optional): the kinds listed in outputs.py; every result is checked against it after the study runs.
Studies draw no buy/sell signals; those rules live only in the backtester (tools/signals.py).
"""
from __future__ import annotations

from .. import indicators as ind
from .outputs import problems

GRAY, PURPLE, TEAL, AMBER, ORANGE, BLUE, PINK, RED, GREEN, DIM = (
    "#8a8f98", "#9b8cff", "#2bb39a", "#e6b450", "#d9824a", "#4d9de0", "#d46aa8", "#ef5350", "#26a69a", "#4a525e")
STYLES = ["solid", "dotted", "dashed", "large_dashed", "sparse_dotted"]
STYLE_LABELS = {"solid": "Solid", "dotted": "Dotted", "dashed": "Dashed", "large_dashed": "Long dashes",
                "sparse_dotted": "Sparse dots"}


def P(key, label, type, default, **kw):
    return {"key": key, "label": label, "type": type, "default": default, "section": kw.pop("section", "Inputs"), **kw}


def src_param(default="close"):
    return P("source", "Source", "choice", default, options=ind.SOURCES)


def color(default, key="color", label="Color", section="Style"):
    return P(key, label, "color", default, section=section)


def plot(id, label, color, width=1, style="solid", transp=0):
    """A drawn line whose color, line type, thickness and transparency the user can change."""
    return {"id": id, "label": label, "color": color, "width": width, "style": style, "transp": transp}


def with_alpha(color: str, transparency_pct: float) -> str:
    """A #rrggbb color made partly transparent: 0% = solid (returned unchanged), 100% = invisible."""
    if not transparency_pct:
        return color
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{round(1 - transparency_pct / 100, 3)})"


def fill_params(default_color: str, label: str, transparency: int = 85) -> list[dict]:
    """A study's "fill between two lines" settings: on or off, a colour and its transparency (section Fill)."""
    return [P("fill", label, "bool", True, section="Fill"),
            color(default_color, "fill_color", "Fill colour", section="Fill"),
            P("fill_transp", "Fill: transparency %", "int", transparency, min=0, max=100, section="Fill")]


def fill_between(w, a, b, up: str, down: str | None = None) -> dict:
    """The "cloud" output: the space between lines a and b over the bars shown (w["current"]), in `up` where a is
    above b and `down` where it's below (one colour for both when down is None, as for channels)."""
    keep = w["current"].to_numpy(dtype=bool) & a.notna().to_numpy() & b.notna().to_numpy()
    return {"points": [{"time": int(t), "a": round(float(x), 4), "b": round(float(y), 4)}
                       for t, x, y in zip(w["ct"].to_numpy()[keep], a.to_numpy()[keep], b.to_numpy()[keep], strict=True)],
            "up": up, "down": down or up}


def channel_fill(w, upper, lower, p: dict) -> dict:
    """The cloud output for a channel study with fill_params, or nothing when its fill is off."""
    return {"cloud": fill_between(w, upper, lower, with_alpha(p["fill_color"], p["fill_transp"]))} if p["fill"] else {}


def style_params(plots: list[dict]) -> list[dict]:
    out = []
    for pl in plots:
        row = pl["label"]
        out += [P(f"{pl['id']}_color", "Color", "color", pl["color"], section="Style", row=row),
                P(f"{pl['id']}_style", "Line type", "choice", pl["style"], options=STYLES, labels=STYLE_LABELS,
                  section="Style", row=row),
                P(f"{pl['id']}_width", "Thickness", "int", pl["width"], min=1, max=4, section="Style", row=row),
                P(f"{pl['id']}_transp", "Transparency %", "int", pl.get("transp", 0), min=0, max=100,
                  section="Style", row=row)]
    return out


REGISTRY: dict[str, dict] = {}
INTRADAY_NOTE = "intraday charts only (1m to 15m)"


def study(type, name, category, pane, params, label, description="", plots=(), warmup=lambda p: 0, intraday=False):
    """intraday=True: the study needs 1-minute bars (sessions, VWAP, opening range...), so on daily, weekly and
    monthly charts it draws nothing and says so."""
    plots = list(plots)
    keys = [p["key"] for p in list(params) + style_params(plots)]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"study {type}: duplicate setting keys {dupes}"

    def deco(fn):
        REGISTRY[type] = {"type": type, "name": name, "category": category, "pane": pane,
                          "params": list(params) + style_params(plots), "plots": plots,
                          "label": label, "description": description, "warmup": warmup, "intraday": intraday,
                          "compute": fn}
        return fn
    return deco


def coerce(spec: dict, raw: dict) -> dict:
    """Fill defaults and clamp values to each parameter's declared range."""
    out = {}
    for p in spec["params"]:
        v = raw.get(p["key"], p["default"])
        t = p["type"]
        try:
            if t == "int":
                v = int(round(float(v)))
            elif t == "float":
                v = float(v)
            elif t == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif t == "choice":
                v = v if v in p["options"] else p["default"]
            else:
                v = str(v)
        except (TypeError, ValueError):
            v = p["default"]
        if t in ("int", "float"):
            if "min" in p:
                v = max(v, p["min"])
            if "max" in p:
                v = min(v, p["max"])
        out[p["key"]] = v
    return out


def apply_styles(spec: dict, params: dict, out: dict) -> None:
    """Give every drawn line its plot's color, line type and thickness. An item names its plot with a
    "plot" key; lines without one match a plot by id (e.g. "band1_up" uses plot "band1")."""
    plots = {pl["id"]: pl for pl in spec["plots"]}

    def style(item, pid):
        if pid in plots:
            item.update(color=with_alpha(params[f"{pid}_color"], params[f"{pid}_transp"]),
                        style=params[f"{pid}_style"], width=params[f"{pid}_width"])

    for line in out.get("lines", []):
        pid = line.get("plot") or next((k for k in plots if line["id"] == k or line["id"].startswith(k + "_")), None)
        style(line, pid)
    for key in ("hlines", "verticals", "levels"):
        for item in out.get(key, []):
            if item.get("plot"):
                style(item, item["plot"])
    if out.get("box") and out["box"].get("plot"):
        style(out["box"], out["box"]["plot"])


def user_defaults(type: str) -> dict:
    """The defaults set for a study on the Config page (the application config), checked against its settings:
    only known keys, each coerced and clamped like any setting."""
    from .. import app_config                          # local: the config module doesn't depend on the studies
    spec = REGISTRY.get(type)
    mine = app_config.section("studies").get(type) if spec else None
    if not isinstance(mine, dict) or not mine:
        return {}
    keys = {p["key"] for p in spec["params"]} & set(mine)
    full = coerce(spec, mine)
    return {k: full[k] for k in keys}


def effective_params(type: str, raw: dict) -> dict:
    """A study's settings: what the chart sent, then the Config page's defaults, then the built-in ones."""
    spec = REGISTRY[type]
    return coerce(spec, {**user_defaults(type), **(raw or {})})


def run_study(ctx, type: str, raw: dict) -> dict:
    """Run one study on a DayContext (intraday) or a PeriodContext (daily, weekly, monthly)."""
    spec = REGISTRY.get(type)
    if not spec:
        return {"type": type, "ok": False, "error": f"Unknown study '{type}'"}
    params = effective_params(type, raw)
    if spec["intraday"] and getattr(ctx, "period", False):
        return {"type": type, "ok": True, "params": params, "label": spec["label"](params), "pane": spec["pane"],
                "note": INTRADAY_NOTE}
    try:
        out = spec["compute"](ctx, params) or {}
        apply_styles(spec, params, out)
        bad = problems(out)
        if bad:
            raise ValueError("bad output: " + "; ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""))
    except Exception as e:  # one broken study must not take the chart down
        return {"type": type, "ok": False, "error": f"{type}: {e}", "params": params,
                "label": spec["label"](params), "pane": spec["pane"]}
    return {"type": type, "ok": True, "params": params, "label": spec["label"](params), "pane": spec["pane"], **out}


def catalog(user: bool = True) -> list[dict]:
    """Every study with its settings; each setting's default is the Config page's, when one is set (user=False:
    the built-in defaults, with "factory" on each setting either way)."""
    out = []
    for s in REGISTRY.values():
        mine = user_defaults(s["type"]) if user else {}
        params = [{**p, "factory": p["default"], "default": mine.get(p["key"], p["default"])} for p in s["params"]]
        out.append({**{k: v for k, v in s.items() if k in ("type", "name", "category", "pane", "description")},
                    "params": params, "customized": sorted(mine),
                    "lines": [{"id": pl["id"], "label": pl["label"]} for pl in s.get("plots", [])]})
    return out


def ln(id, title, data, **kw):
    """A line output; color, style and width are filled in from the study's plot settings."""
    return {"id": id, "title": title, "color": GRAY, "width": 1, "style": "solid", "data": data, **kw}


def hl(price, plot_id):
    """A horizontal reference line in a study's own pane, styled by its plot."""
    return {"price": price, "title": "", "plot": plot_id, "color": GRAY, "style": "dashed", "width": 1}


def bars_for(ctx, n):
    return ctx.warm(n + 5)


def level(p, plot_id, price, label, ctx=None, flip_closes=0, moving=False):
    """A price-pane level drawn with the color, line type and thickness chosen for its plot.
    If flip_closes is set, the label notes when price has closed beyond the level against the side it opened on."""
    flipped = False
    five = ctx.five_closed if ctx is not None and flip_closes else None
    if five is not None and len(five) >= flip_closes and not moving:
        recent = five["close"].iloc[-flip_closes:]
        flipped = bool((recent < price).all() if ctx.open_price >= price else (recent > price).all())
    suffix = " (flipped)" if flipped else (" (moving)" if moving else "")
    return {"price": round(float(price), 2), "label": label + suffix, "plot": plot_id, "flipped": flipped,
            "role": None if ctx is None else ("support" if ctx.price >= price else "resistance"),
            "color": p[f"{plot_id}_color"], "style": p[f"{plot_id}_style"], "width": p[f"{plot_id}_width"]}
