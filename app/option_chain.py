"""The option-chain page's data: the cached chain (written by the collector, tools/option_quotes.py) turned into
what the page shows, and a structure's legs priced from it. No network, no orders.

The cache (data/chains/<SYMBOL>.json) holds one moment's snapshot quotes: a window of strikes around the price for
the expiries the page asked for, and the at-the-money strikes of the next STRIP expiries (their expected moves).
It has the same "expiries -> quotes -> strike -> C/P" shape as the expected-move cache, so the same helpers read both.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from . import expected_move as em
from . import store
from . import structures as st

STRIP = 8                   # expiries in the page's expiry strip (each with its expected move)
MAX_EXPIRIES = 4            # expiries quoted in full per request (the one viewed plus a structure's)
WINDOWS = (5, 9, 15)        # strikes either side of the price
DEFAULT_WINDOW = 9
STALE_SECONDS = 5 * 60      # older quotes are offered a refresh


def path(symbol: str) -> Path:
    return store.DATA_DIR / "chains" / f"{symbol.upper()}.json"


def read(symbol: str) -> dict | None:
    try:
        d = json.loads(path(symbol).read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def write(symbol: str, data: dict) -> None:
    p = path(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(p)


def quoted_at(cache: dict) -> pd.Timestamp:
    return pd.Timestamp(cache["quoted_at"]).tz_convert(st.ET)


def _side(q: dict | None, s: float, k: float, t: float, right: str) -> dict | None:
    """One option's row cell: bid, ask, mid, IV (IBKR's, else from the mid), delta and gamma (IBKR's, else
    Black-Scholes) and open interest."""
    if not q:
        return None
    m, how = em.mid(q)
    iv = q.get("iv") or (st.implied_vol(m, s, k, t, right) if m else None)
    delta, gamma = q.get("delta"), q.get("gamma")
    if iv and (delta is None or gamma is None):
        g = st.bs_greeks(s, k, t, iv, right)
        delta = g["delta"] if delta is None else delta
        gamma = g["gamma"] if gamma is None else gamma
    return {"bid": q.get("bid"), "ask": q.get("ask"), "mid": round(m, 4) if m is not None else None, "how": how,
            "iv": round(iv, 4) if iv else None, "delta": round(delta, 3) if delta is not None else None,
            "gamma": gamma, "oi": q.get("oi")}


def gamma_exposure(gamma: float | None, oi: float | None, price: float) -> float | None:
    """Dollars of delta per 1% move in the stock held by an option's open interest: gamma x OI x 100 x S^2 x 1%."""
    if gamma is None or oi is None:
        return None
    return gamma * oi * st.MULT * price * price * 0.01


def strike_profile(rows: list[dict], price: float) -> dict:
    """Gamma exposure by strike: calls +, puts - (the usual convention: dealers long calls, short puts). Strikes
    without open interest are left out and counted."""
    out, missing = [], 0
    for r in rows:
        c, p = r.get("C") or {}, r.get("P") or {}
        cg, pg = gamma_exposure(c.get("gamma"), c.get("oi"), price), gamma_exposure(p.get("gamma"), p.get("oi"), price)
        if cg is None and pg is None:
            missing += 1
            continue
        out.append({"strike": r["strike"], "call": round(cg or 0.0, 2), "put": round(-(pg or 0.0), 2),
                    "call_oi": c.get("oi"), "put_oi": p.get("oi")})
    net = sum(x["call"] + x["put"] for x in out)
    return {"strikes": out, "missing": missing, "net": round(net, 2),
            "call_wall": max(out, key=lambda x: x["call"])["strike"] if out else None,
            "put_wall": min(out, key=lambda x: x["put"])["strike"] if out else None}


def view(symbol: str, expiry: str | None = None) -> dict:
    """The chain for one expiry (default: the first the collector quoted in full), the expiry strip, and status."""
    symbol = symbol.upper()
    cache = read(symbol)
    out = {"symbol": symbol, "stale_seconds": STALE_SECONDS, "templates": st.TEMPLATES, "windows": WINDOWS}
    if not cache:
        return {**out, "status": "missing"}
    out.update({"fetched": cache.get("fetched"), "quoted_at": cache.get("quoted_at"), "wanted": cache.get("wanted", []),
                "window": cache.get("window"), "synthetic": bool(cache.get("synthetic")),
                "age": round(time.time() - cache["fetched"]) if cache.get("fetched") else None})
    if cache.get("error"):
        return {**out, "status": "error", "message": cache["error"]}
    price, now = cache["price"], quoted_at(cache)
    strip = []
    for e in cache.get("expirations", [])[:STRIP]:
        s = em.straddle_at(cache, e, price)
        strip.append({"expiry": e, "label": em.fmt_expiry(e), "days": max(0, (pd.Timestamp(e) - now.tz_localize(None).normalize()).days),
                      "move": round(s["value"], 2) if s else None, "iv": s["iv"] if s else None,
                      "full": e in cache.get("wanted", [])})
    wanted = cache.get("wanted") or []
    expiry = expiry if expiry in wanted else (wanted[0] if wanted else None)
    rows = []
    if expiry:
        t = st.years(now, expiry)
        quotes = cache["expiries"].get(expiry, {}).get("quotes", {})
        for k in sorted(float(x) for x in quotes):
            qk = quotes[em._key(k)]
            rows.append({"strike": k, "C": _side(qk.get("C"), price, k, t, "C"), "P": _side(qk.get("P"), price, k, t, "P")})
    s = em.straddle_at(cache, expiry, price) if expiry else None
    profile = strike_profile(rows, price)
    warnings = []
    if not cache.get("market_open"):
        warnings.append("Quotes taken outside regular hours: option prices are often wide or stale until 09:30 ET.")
    return {**out, "status": "ok", "price": price, "price_source": cache.get("price_source"),
            "market_open": bool(cache.get("market_open")), "expirations": cache.get("expirations", []), "strip": strip,
            "expiry": expiry, "expiry_label": em.fmt_expiry(expiry), "rows": rows,
            "move": round(s["value"], 2) if s else None, "atm_iv": s["iv"] if s else None,
            "next_weekly": em.pick_expiries(cache.get("expirations", []), _iso(expiry), _iso(expiry))["next"] if expiry else None,
            "profile": profile, "oi_day": cache.get("oi_day"),
            "warnings": warnings}


def _iso(e: str) -> str:
    return f"{e[:4]}-{e[4:6]}-{e[6:]}"


def priced(cache: dict, legs: list[dict]) -> tuple[list[dict], list[str]]:
    """The legs with their mid price and IV from the cache, and the expiries (YYYYMMDD) still to be quoted."""
    price, now = cache["price"], quoted_at(cache)
    out, missing = [], []
    for leg in legs:
        q = em.quote(cache, leg["expiry"], leg["strike"], leg["right"])
        m, _ = em.mid(q)
        if m is None:
            missing.append(leg["expiry"])
            continue
        iv = (q or {}).get("iv") or st.implied_vol(m, price, leg["strike"], st.years(now, leg["expiry"]), leg["right"])
        greek = st.bs_greeks(price, leg["strike"], st.years(now, leg["expiry"]), iv or 0.3, leg["right"])
        out.append({**leg, "price": round(m, 4), "iv": iv, "delta": round(greek["delta"], 3),
                    "theta": round(greek["theta"], 4), "label": em.fmt_expiry(leg["expiry"])})
    return out, sorted(set(missing))


def evaluate(symbol: str, legs: list[dict], at: str, iv_shift: float, stop: float | None) -> dict:
    """A structure priced from the cached chain and evaluated (structures.evaluate), or what's missing."""
    cache = read(symbol)
    if not cache or cache.get("error"):
        return {"status": "missing", "missing": sorted({leg["expiry"] for leg in legs})}
    full, missing = priced(cache, legs)
    if missing:
        return {"status": "missing", "missing": missing}
    front = min(leg["expiry"] for leg in full)
    s = em.straddle_at(cache, front, cache["price"])
    res = st.evaluate(full, cache["price"], quoted_at(cache), at, iv_shift, sigma=s["iv"] if s else None,
                      move=s["value"] if s else None, stop=stop)
    return {"status": "ok", "legs": full, "price": cache["price"], "quoted_at": cache.get("quoted_at"), **res}
