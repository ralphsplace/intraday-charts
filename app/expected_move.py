"""The expected move of a stock by an option expiry, from its option quotes (the expected-move page).

One job: option quotes in, expected move out. The collector (tools/option_quotes.py) fetches the quotes from TWS
and caches them here; the server builds the view from that cache. The same functions choose which strikes to
quote, so the page and the collector always agree.

For the chosen expiry (the first on or after the date asked for):
  - straddle    the at-the-money call + put (mid prices), interpolated to the stock's price: the market's
                average expected move by expiry
  - 0.85 x straddle, a common rule of thumb
  - 1 and 2 sigma from implied volatility: price x IV x sqrt(calendar years to expiry, 16:00 ET)
  - an event between the previous expiry and this one (e.g. earnings): when IV jumps between them, the jump's
    own move is sqrt((IV_this^2 - IV_prev^2) x T_this)
  - diagonal legs (Ralph's construction): short call and put at the listed strikes nearest the expected move in
    this expiry, long call and put one strike closer to the money in the next weekly expiry
Quality checks: quotes outside regular hours, wide bid/ask spreads, and a stock price the options disagree with
(put-call parity at the at-the-money strike) are flagged.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import pandas as pd

from . import sessions, store

ET = "America/New_York"
WIDE = 0.25                 # a spread wider than 25% of the mid price is "wide"
PARITY_GAP = 0.004          # options imply a price more than 0.4% from the stock's: flag it
EVENT_JUMP = 1.15           # IV 15% above the previous expiry's: an event sits between them
NEXT_WEEKLY_DAYS = 7        # the diagonal's long legs: the next weekly, at least 7 days after this one (Fri -> next Fri)
STALE_SECONDS = 15 * 60     # cached quotes older than this are offered a refresh


# ---------------------------------------------------------------- cache (written by the collector)
def path(symbol: str) -> Path:
    return store.DATA_DIR / "options" / f"{symbol.upper()}.json"


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


# ---------------------------------------------------------------- picking expiries and strikes
def pick_expiries(expiries: list[str], target: str, today: str) -> dict:
    """{"chosen", "prev", "next"} (YYYYMMDD): the first expiry on or after `target` (YYYY-MM-DD), the one before it
    (if not already expired), and the next weekly: the first at least NEXT_WEEKLY_DAYS after it."""
    ex = sorted(e for e in expiries if e >= today.replace("-", ""))
    t = target.replace("-", "")
    chosen = next((e for e in ex if e >= t), None)
    if chosen is None:
        return {"chosen": None, "prev": None, "next": None}
    prev = [e for e in ex if e < chosen]
    later = pd.Timestamp(chosen) + pd.Timedelta(days=NEXT_WEEKLY_DAYS)
    nxt = next((e for e in ex if pd.Timestamp(e) >= later), None)
    return {"chosen": chosen, "prev": prev[-1] if prev else None, "next": nxt}


def bracket(strikes: list[float], price: float) -> list[float]:
    """The listed strikes either side of the price (one if it sits on a strike)."""
    s = sorted(strikes)
    below = [k for k in s if k <= price]
    above = [k for k in s if k >= price]
    out = ([below[-1]] if below else []) + ([above[0]] if above else [])
    return sorted(set(out))


def nearest(strikes: list[float], x: float) -> float | None:
    return min(strikes, key=lambda k: (abs(k - x), k)) if strikes else None


def one_closer(strikes: list[float], k: float, price: float) -> float | None:
    """The next listed strike from k towards the price."""
    s = sorted(strikes)
    if k >= price:
        lower = [x for x in s if x < k]
        return lower[-1] if lower else None
    higher = [x for x in s if x > k]
    return higher[0] if higher else None


# ---------------------------------------------------------------- prices
def mid(q: dict | None) -> tuple[float | None, str | None]:
    """A quote's price and where it came from: the bid/ask mid, or the last trade when there's no two-sided quote."""
    if not q:
        return None, None
    bid, ask, last = q.get("bid"), q.get("ask"), q.get("last")
    if _num(bid) and _num(ask) and bid > 0 and ask >= bid:
        return (bid + ask) / 2, "mid"
    if _num(last) and last > 0:
        return float(last), "last"
    return None, None


def spread_pct(q: dict | None) -> float | None:
    m, how = mid(q)
    if how != "mid" or not m:
        return None
    return (q["ask"] - q["bid"]) / m


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def years_to(expiry: str, now: pd.Timestamp) -> float:
    """Calendar years from now to 16:00 ET on the expiry (at least one minute)."""
    end = pd.Timestamp(f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]} 16:00", tz=ET)
    return max((end - now).total_seconds(), 60.0) / (365 * 86400)


def quote(cache: dict, expiry: str | None, strike: float | None, right: str) -> dict | None:
    if not expiry or strike is None:
        return None
    return ((cache.get("expiries") or {}).get(expiry, {}).get("quotes") or {}).get(_key(strike), {}).get(right)


def _key(strike: float) -> str:
    return f"{float(strike):g}"


def listed(cache: dict, expiry: str | None) -> list[float]:
    """The strikes quoted for an expiry with both a call and a put."""
    qs = ((cache.get("expiries") or {}).get(expiry or "", {}).get("quotes") or {})
    return sorted(float(k) for k, v in qs.items() if v.get("C") and v.get("P"))


def listed_side(cache: dict, expiry: str | None, right: str) -> list[float]:
    """The strikes quoted for an expiry on one side ("C" or "P")."""
    qs = ((cache.get("expiries") or {}).get(expiry or "", {}).get("quotes") or {})
    return sorted(float(k) for k, v in qs.items() if v.get(right))


def short_strike(cache: dict, expiry: str | None, right: str, price: float, move: float) -> float | None:
    """The listed strike nearest the expected move, on its side of the price (calls above, puts below)."""
    side = [k for k in listed_side(cache, expiry, right) if (k >= price if right == "C" else k <= price)]
    return nearest(side, price + move if right == "C" else price - move)


def straddle_at(cache: dict, expiry: str | None, price: float) -> dict | None:
    """The at-the-money straddle for an expiry: per bracketing strike, and interpolated to the price."""
    ks = bracket(listed(cache, expiry), price)
    rows = []
    for k in ks:
        c, _ = mid(quote(cache, expiry, k, "C"))
        p, _ = mid(quote(cache, expiry, k, "P"))
        if c is not None and p is not None:
            rows.append({"strike": k, "call": round(c, 4), "put": round(p, 4), "straddle": round(c + p, 4)})
    if not rows:
        return None
    if len(rows) == 2 and rows[1]["strike"] > rows[0]["strike"]:
        w = (price - rows[0]["strike"]) / (rows[1]["strike"] - rows[0]["strike"])
        value = rows[0]["straddle"] + w * (rows[1]["straddle"] - rows[0]["straddle"])
    else:
        value = rows[0]["straddle"]
    atm = min(rows, key=lambda r: abs(r["strike"] - price))
    ivs = [q.get("iv") for r in rows for q in (quote(cache, expiry, r["strike"], "C"), quote(cache, expiry, r["strike"], "P"))
           if q and _num(q.get("iv")) and q["iv"] > 0]
    return {"rows": rows, "atm": atm, "value": round(value, 4), "iv": round(sum(ivs) / len(ivs), 4) if ivs else None}


# ---------------------------------------------------------------- the view
def view(symbol: str, target: str, now: pd.Timestamp | None = None) -> dict:
    """Everything the page shows for one symbol, or a status saying what's missing."""
    now = now or pd.Timestamp.now(tz=ET)
    symbol = symbol.upper()
    cache = read(symbol)
    out = {"symbol": symbol, "target": target}
    if not cache:
        return {**out, "status": "missing"}
    out["fetched"] = cache.get("fetched")
    out["quoted_at"] = cache.get("quoted_at")
    out["age"] = round(time.time() - cache["fetched"]) if _num(cache.get("fetched")) else None
    if cache.get("target") != target:
        return {**out, "status": "missing", "message": "quotes were fetched for another date"}
    if cache.get("error"):
        return {**out, "status": "error", "message": cache["error"]}
    price = cache.get("price")
    ex = {k: cache.get(k) for k in ("chosen", "prev", "next")}
    if not _num(price) or not ex["chosen"]:
        return {**out, "status": "error", "message": "no price or no expiry on or after that date"}
    s = straddle_at(cache, ex["chosen"], price)
    if not s:
        return {**out, "status": "error", "message": f"no quotes for the {fmt_expiry(ex['chosen'])} expiry"}
    if cache.get("quoted_at"):              # time left is counted from the quotes, not from when they're looked at
        now = pd.Timestamp(cache["quoted_at"]).tz_convert(ET)
    t = years_to(ex["chosen"], now)
    em = s["value"]
    moves = [_move("Straddle (expected move)", em, price), _move("0.85 x straddle", 0.85 * em, price)]
    if s["iv"]:
        one = price * s["iv"] * math.sqrt(t)
        moves += [_move("1 sigma from IV (about 68%)", one, price), _move("2 sigma (about 95%)", 2 * one, price)]
    warnings = list(cache.get("warnings") or [])
    if not cache.get("market_open"):
        warnings.append("Quotes taken outside regular hours: option prices are often wide or stale until 09:30 ET.")
    wide = [f"{r['strike']:g} {side}" for r in s["rows"] for side, right in (("call", "C"), ("put", "P"))
            if (spread_pct(quote(cache, ex["chosen"], r["strike"], right)) or 0) > WIDE]
    if wide:
        warnings.append("Wide bid/ask spreads (over 25% of the mid): " + ", ".join(wide) + ".")
    parity = None
    a = s["atm"]
    implied = a["strike"] + a["call"] - a["put"]
    if abs(implied - price) / price > PARITY_GAP:
        parity = round(implied, 2)
        warnings.append(f"The options imply a price near {implied:.2f}, but the stock's price is {price:.2f}: the "
                        "stock or the option quotes may be stale.")
    res = {**out, "status": "ok", "price": price, "price_source": cache.get("price_source"),
           "market_open": bool(cache.get("market_open")), "expiry": ex["chosen"], "prev_expiry": ex["prev"],
           "next_expiry": ex["next"], "days": round(t * 365, 2), "atm": a, "straddle": s, "iv": s["iv"],
           "moves": moves, "parity_price": parity, "event": event(cache, ex, price, s, now),
           "diagonal": diagonal(cache, ex, price, em), "warnings": warnings}
    return res


def _move(name: str, move: float, price: float) -> dict:
    return {"name": name, "move": round(move, 2), "pct": round(move / price * 100, 2),
            "low": round(price - move, 2), "high": round(price + move, 2)}


def event(cache: dict, ex: dict, price: float, s: dict, now: pd.Timestamp) -> dict | None:
    """An event priced between the previous expiry and this one, from the jump in implied volatility."""
    if not ex["prev"] or not s["iv"]:
        return None
    p = straddle_at(cache, ex["prev"], price)
    if not p or not p["iv"]:
        return None
    iv_c, iv_p, t = s["iv"], p["iv"], years_to(ex["chosen"], now)
    if iv_c < iv_p * EVENT_JUMP:
        return {"found": False, "prev_iv": iv_p, "iv": iv_c, "prev_expiry": ex["prev"]}
    move = price * math.sqrt(max(iv_c ** 2 - iv_p ** 2, 0.0) * t)
    return {"found": True, "prev_iv": iv_p, "iv": iv_c, "prev_expiry": ex["prev"],
            "move": round(move, 2), "pct": round(move / price * 100, 2)}


def diagonal(cache: dict, ex: dict, price: float, em: float) -> dict | None:
    """Short call and put at the strikes nearest the expected move (this expiry); long call and put one strike
    closer to the money in the next weekly expiry; each leg's mid and the net per side (long - short)."""
    if not ex["next"]:
        return None
    legs = {}
    for right in "CP":
        k = short_strike(cache, ex["chosen"], right, price, em)
        long_k = one_closer(listed_side(cache, ex["next"], right), k, price) if k is not None else None
        sm, _ = mid(quote(cache, ex["chosen"], k, right))
        lm, _ = mid(quote(cache, ex["next"], long_k, right))
        legs[right] = {"short_strike": k, "short": _r(sm), "long_strike": long_k, "long": _r(lm),
                       "net": _r(lm - sm) if sm is not None and lm is not None else None}
    n = straddle_at(cache, ex["next"], price)
    total = [legs[r]["net"] for r in "CP"]
    return {"short_expiry": ex["chosen"], "long_expiry": ex["next"], "call": legs["C"], "put": legs["P"],
            "net": _r(sum(total)) if all(x is not None for x in total) else None,
            "next_straddle": n["value"] if n else None, "next_iv": n["iv"] if n else None}


def _r(x):
    return None if x is None else round(x, 2)


def fmt_expiry(e: str | None) -> str:
    return pd.Timestamp(e).strftime("%a %b %-d") if e else ""


def market_open(now: pd.Timestamp) -> bool:
    day = now.strftime("%Y-%m-%d")
    m = now.hour * 60 + now.minute
    return sessions.is_trading_day(day) and 9 * 60 + 30 <= m < 16 * 60
