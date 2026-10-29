"""Option structures: building them from a chain (templates) and evaluating them. Read-only: nothing here places
or prepares orders.

One job: legs in, numbers out. A leg is {"qty": +n bought / -n sold, "expiry": "YYYYMMDD", "strike", "right": "C"|"P",
"price": its mid, "iv": its implied volatility}. Values before expiry come from Black-Scholes with each leg's own
implied volatility (European exercise, no dividends, a flat RATE), so they are estimates: real prices also move
with volatility, skew and early exercise. At its expiry's 16:00 close a leg is worth its intrinsic value.

evaluate() gives, for 1 structure (x 100 shares per contract):
  - the net debit (+) or credit (-), and the Greeks now
  - profit/loss across stock prices now and at a chosen time (the risk graph), its breakevens, best and worst
  - the chance of a profit at that time, from a lognormal move at the front expiry's implied volatility
  - a grid of profit/loss by stock price and time, and where a loss limit sits in stock prices (a stop on the
    structure, read as levels on the stock's chart)
"""
from __future__ import annotations

import math

import pandas as pd

from . import expected_move as em

ET = "America/New_York"
RATE = 0.04            # risk-free rate for Black-Scholes (an estimate; small effect over days)
MULT = 100             # shares per contract
POINTS = 241           # stock prices across the risk graph
MIN_IV = 0.01
YEAR = 365 * 86400

TEMPLATES = {
    "custom": "Custom (click bids and asks in the chain)",
    "double_diagonal": "Double diagonal at the expected move",
    "diagonal": "Call diagonal at the expected move",
    "calendar": "Call calendar at the money",
    "vertical": "Call vertical to the expected move",
    "straddle": "Straddle at the money",
    "strangle": "Strangle at the expected move",
    "iron_condor": "Iron condor at the expected move",
    "butterfly": "Call butterfly across the expected move",
}
NEEDS_BACK = {"double_diagonal", "diagonal", "calendar"}
WING = 2               # iron condor wings: this many listed strikes beyond the short strikes


# ---------------------------------------------------------------- Black-Scholes
def _n(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _pdf(x: float) -> float:
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def intrinsic(s: float, k: float, right: str) -> float:
    return max(s - k, 0.0) if right == "C" else max(k - s, 0.0)


def bs_price(s: float, k: float, t: float, iv: float, right: str) -> float:
    if t <= 0 or s <= 0:
        return intrinsic(s, k, right)
    iv = max(iv, MIN_IV)
    d1 = (math.log(s / k) + (RATE + iv * iv / 2) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    if right == "C":
        return s * _n(d1) - k * math.exp(-RATE * t) * _n(d2)
    return k * math.exp(-RATE * t) * _n(-d2) - s * _n(-d1)


def bs_greeks(s: float, k: float, t: float, iv: float, right: str) -> dict:
    """Per share: delta, gamma, theta (per calendar day), vega (per 1 point of IV)."""
    if t <= 0:
        itm = (s > k) if right == "C" else (s < k)
        return {"delta": (1.0 if right == "C" else -1.0) if itm else 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    iv = max(iv, MIN_IV)
    rt = math.sqrt(t)
    d1 = (math.log(s / k) + (RATE + iv * iv / 2) * t) / (iv * rt)
    d2 = d1 - iv * rt
    disc = k * math.exp(-RATE * t)
    if right == "C":
        delta, carry = _n(d1), -RATE * disc * _n(d2)
    else:
        delta, carry = _n(d1) - 1, RATE * disc * _n(-d2)
    theta = (-s * _pdf(d1) * iv / (2 * rt) + carry) / 365
    return {"delta": delta, "gamma": _pdf(d1) / (s * iv * rt), "theta": theta, "vega": s * _pdf(d1) * rt / 100}


def implied_vol(price: float, s: float, k: float, t: float, right: str) -> float | None:
    """The volatility that gives this price (bisection), or None when the price is below intrinsic or absurd."""
    if t <= 0 or price is None or price <= intrinsic(s, k, right) * math.exp(-RATE * t) - 1e-9:
        return None
    lo, hi = 0.005, 5.0
    if bs_price(s, k, t, hi, right) < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_price(s, k, t, mid, right) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- time
def close_of(expiry: str) -> pd.Timestamp:
    return pd.Timestamp(f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]} 16:00", tz=ET)


def years(at: pd.Timestamp, expiry: str) -> float:
    """Calendar years from `at` to the expiry's 16:00 close (0 or less: expired)."""
    return (close_of(expiry) - at).total_seconds() / YEAR


def eval_times(legs: list[dict], now: pd.Timestamp) -> list[dict]:
    """The times a structure can be evaluated at: now, today's close, midday and the close of the front expiry."""
    front = min(leg["expiry"] for leg in legs)
    fc = close_of(front)
    out = [{"id": "now", "label": "Now " + now.strftime("%H:%M"), "at": now}]
    today_close = now.normalize() + pd.Timedelta(hours=16)
    if now < today_close < fc:
        out.append({"id": "close", "label": "Today 16:00", "at": today_close})
    noon = fc - pd.Timedelta(hours=4)
    if noon > now and noon.normalize() > now.normalize():
        out.append({"id": "front_noon", "label": fc.strftime("%a") + " 12:00", "at": noon})
    if fc > now:
        out.append({"id": "front_close", "label": fc.strftime("%a %b %-d") + " 16:00 (front expiry)", "at": fc})
    return out


# ---------------------------------------------------------------- values
def value(legs: list[dict], s: float, at: pd.Timestamp, iv_shift: float = 0.0) -> float:
    """The structure's value per share at stock price s and time `at` (bought legs +, sold legs -)."""
    total = 0.0
    for leg in legs:
        t = years(at, leg["expiry"])
        total += leg["qty"] * bs_price(s, leg["strike"], t, (leg.get("iv") or 0.3) + iv_shift, leg["right"])
    return total


def net_price(legs: list[dict]) -> float:
    """Per share: + a debit (paid), - a credit (received), at the legs' mid prices."""
    return sum(leg["qty"] * leg["price"] for leg in legs)


def greeks(legs: list[dict], s: float, now: pd.Timestamp) -> dict:
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        g = bs_greeks(s, leg["strike"], years(now, leg["expiry"]), leg.get("iv") or 0.3, leg["right"])
        for k in out:
            out[k] += leg["qty"] * g[k] * MULT
    return {k: round(v, 2) for k, v in out.items()}


def _crossings(xs: list[float], ys: list[float], level: float = 0.0) -> list[float]:
    out = []
    for i in range(1, len(xs)):
        a, b = ys[i - 1] - level, ys[i] - level
        if a == 0:
            out.append(xs[i - 1])
        elif a * b < 0:
            out.append(xs[i - 1] + (xs[i] - xs[i - 1]) * a / (a - b))
    return [round(x, 2) for x in dict.fromkeys(out)]


def _nice(x: float) -> float:
    """A round step near x: 0.5, 1, 2, 2.5, 5 x a power of ten."""
    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    return min((m * p for m in (1, 2, 2.5, 5, 10)), key=lambda v: abs(v - x))


def evaluate(legs: list[dict], price: float, now: pd.Timestamp, at_id: str = "front_close", iv_shift: float = 0.0,
             sigma: float | None = None, move: float | None = None, stop: float | None = None) -> dict:
    """The numbers for 1 structure. sigma: the front expiry's at-the-money IV (for the chance of profit and the
    price range); move: its expected move in $ (the grid's spacing); stop: a loss limit in $ (negative)."""
    times = eval_times(legs, now)
    at = next((t for t in times if t["id"] == at_id), times[-1])
    sigma = sigma or sum(leg.get("iv") or 0.3 for leg in legs) / len(legs)
    front = min(leg["expiry"] for leg in legs)
    sd = price * sigma * math.sqrt(max(years(now, front), 1 / (365 * 24)))
    half = max(4 * sd, 0.03 * price)
    xs = [price - half + 2 * half * i / (POINTS - 1) for i in range(POINTS)]
    net = net_price(legs)

    def pnl(x, t):
        return (value(legs, x, t, iv_shift) - net) * MULT

    curve_now = [pnl(x, now) for x in xs]
    curve_at = [pnl(x, at["at"]) for x in xs]
    wide = [price * f / 100 for f in range(5, 301, 1)] + xs        # best and worst beyond the graph too
    wide_at = [pnl(x, at["at"]) for x in wide]
    best_i = max(range(len(wide)), key=lambda i: wide_at[i])
    worst = min(wide_at)
    calls = sum(leg["qty"] for leg in legs if leg["right"] == "C")
    out = {
        "net": round(net, 4), "cost": round(net * MULT, 2), "kind": "debit" if net >= 0 else "credit",
        "times": [{"id": t["id"], "label": t["label"]} for t in times], "at": at["id"], "at_label": at["label"],
        "iv_shift": iv_shift, "greeks": greeks(legs, price, now),
        "graph": {"prices": [round(x, 2) for x in xs], "now": [round(v, 2) for v in curve_now],
                  "at": [round(v, 2) for v in curve_at]},
        "breakevens": _crossings(xs, curve_at),
        "max_profit": {"value": round(wide_at[best_i], 2), "price": round(wide[best_i], 2), "unlimited": calls > 0},
        "max_loss": {"value": round(worst, 2), "unlimited": calls < 0},
        "chance": chance(legs, price, now, at["at"], sigma, iv_shift, net),
        "grid": grid(legs, price, now, times, iv_shift, net, move or sd),
    }
    if stop is not None and stop < 0:
        fine = [price - half + 2 * half * i / 2000 for i in range(2001)]
        ys = [pnl(x, at["at"]) for x in fine]
        cross = _crossings(fine, ys, stop)
        out["stop"] = {"loss": stop, "below": max((x for x in cross if x < price), default=None),
                       "above": min((x for x in cross if x > price), default=None)}
    return out


def chance(legs, price, now, at, sigma, iv_shift, net) -> float | None:
    """P(profit at `at`), the stock moving lognormally at the front expiry's implied volatility."""
    t = (at - now).total_seconds() / YEAR
    if t <= 0:
        return None
    sd = sigma * math.sqrt(t)
    zs = [-5 + 10 * i / 800 for i in range(801)]
    w = [_pdf(z) for z in zs]
    win = sum(wi for z, wi in zip(zs, w, strict=True)
              if value(legs, price * math.exp((RATE - sigma ** 2 / 2) * t + sd * z), at, iv_shift) > net)
    return round(100 * win / sum(w), 1)


def grid(legs, price, now, times, iv_shift, net, move) -> dict:
    """Profit/loss at 11 stock prices (the current one in the middle, spaced over about 1.5 expected moves either
    side) by each evaluation time."""
    step = _nice(1.5 * move / 5)
    prices = [round(price + i * step, 2) for i in range(5, -6, -1)]
    return {"prices": prices, "times": [t["label"] for t in times],
            "values": [[round((value(legs, x, t["at"], iv_shift) - net) * MULT, 2) for t in times] for x in prices]}


# ---------------------------------------------------------------- templates
def template(name: str, cache: dict, front: str, back: str | None) -> list[dict]:
    """Legs (qty, expiry, strike, right) for a template, from the strikes quoted in the cache. Raises ValueError
    with a reason the page can show."""
    if name not in TEMPLATES or name == "custom":
        raise ValueError("Pick a template")
    if name in NEEDS_BACK and not back:
        raise ValueError("This template needs a later expiry: pick one under Back expiry")
    price = cache["price"]
    s = em.straddle_at(cache, front, price)
    if not s:
        raise ValueError(f"No at-the-money quotes for {em.fmt_expiry(front)} yet")
    move = s["value"]
    side = {r: [k for k in em.listed_side(cache, front, r)] for r in "CP"}
    atm = em.nearest(sorted(set(side["C"]) & set(side["P"])), price)
    up = em.short_strike(cache, front, "C", price, move)
    dn = em.short_strike(cache, front, "P", price, move)

    def leg(qty, expiry, strike, right):
        if strike is None:
            raise ValueError(f"No quoted {right} strike for this template in {em.fmt_expiry(expiry)}: widen Strikes")
        return {"qty": qty, "expiry": expiry, "strike": float(strike), "right": right}

    def back_strike(k, right):
        return em.one_closer(em.listed_side(cache, back, right), k, price) if k is not None else None

    def beyond(k, right, n):
        ks = side[right]
        if k is None or k not in ks:
            return None
        i = ks.index(k) + (n if right == "C" else -n)
        return ks[i] if 0 <= i < len(ks) else None

    if name == "double_diagonal":
        return [leg(-1, front, up, "C"), leg(-1, front, dn, "P"),
                leg(1, back, back_strike(up, "C"), "C"), leg(1, back, back_strike(dn, "P"), "P")]
    if name == "diagonal":
        return [leg(-1, front, up, "C"), leg(1, back, back_strike(up, "C"), "C")]
    if name == "calendar":
        k = atm if atm in em.listed_side(cache, back, "C") else None
        return [leg(-1, front, atm, "C"), leg(1, back, k, "C")]
    if name == "vertical":
        return [leg(1, front, atm, "C"), leg(-1, front, up if up != atm else beyond(atm, "C", 1), "C")]
    if name == "straddle":
        return [leg(1, front, atm, "C"), leg(1, front, atm, "P")]
    if name == "strangle":
        return [leg(1, front, up, "C"), leg(1, front, dn, "P")]
    if name == "iron_condor":
        return [leg(-1, front, up, "C"), leg(1, front, beyond(up, "C", WING), "C"),
                leg(-1, front, dn, "P"), leg(1, front, beyond(dn, "P", WING), "P")]
    # butterfly: calls, body at the money, equal wings about the expected move wide
    lo = em.nearest([k for k in side["C"] if k < atm], atm - move) if atm is not None else None
    hi = atm + (atm - lo) if lo is not None else None
    return [leg(1, front, lo, "C"), leg(-2, front, atm, "C"), leg(1, front, hi if hi in side["C"] else None, "C")]
