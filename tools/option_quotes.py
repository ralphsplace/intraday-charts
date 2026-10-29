"""Option quotes for the expected-move page: one symbol's chain and snapshot quotes from TWS, read-only.

One job: ask TWS for the quotes app/expected_move.py needs, and cache them there. Two rounds of snapshots:
  1. the stock, and the at-the-money calls and puts of the chosen expiry, the one before it and the next weekly
     (the strikes either side of the price), which give the expected move;
  2. the strikes nearest that move in the chosen expiry (the diagonal's short legs) and the strikes one closer to
     the money in the next weekly (its long legs).
Snapshots are one-off quotes (no streaming); IBKR needs US options market data (OPRA) for them.
"""
from __future__ import annotations

import logging
import math
import time

from app import expected_move as em
from app import sessions

log = logging.getLogger("fetch_ibkr")
CANDIDATES = 4          # strikes tried per side: a chain lists every strike of every expiry, not all exist in each


def _clean(x) -> float | None:
    """IBKR sends nan or -1 for "no value"."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def ticker_quote(t) -> dict:
    g = getattr(t, "modelGreeks", None)
    return {"bid": _clean(getattr(t, "bid", None)), "ask": _clean(getattr(t, "ask", None)),
            "last": _clean(getattr(t, "last", None)), "close": _clean(getattr(t, "close", None)),
            "iv": _clean(getattr(g, "impliedVol", None)) if g is not None else None}


def _option(symbol, expiry, strike, right, trading_class):
    from ib_async import Option
    return Option(symbol, expiry, strike, right, "SMART", currency="USD", tradingClass=trading_class)


class OptionQuotes:
    def __init__(self, ib, option=_option):
        self.ib, self.option = ib, option

    def chain(self, symbol: str, con_id: int):
        chains = self.ib.reqSecDefOptParams(symbol, "", "STK", con_id) or []
        smart = [c for c in chains if c.exchange == "SMART"]
        return next((c for c in smart if c.tradingClass == symbol), smart[0] if smart else (chains[0] if chains else None))

    def quote(self, symbol: str, trading_class: str, wanted: list[tuple[str, float, str]], cache: dict) -> None:
        """Qualify and quote options (expiry, strike, right), adding them to the cache; ones that don't exist
        are skipped."""
        todo = [w for w in dict.fromkeys(wanted) if em.quote(cache, w[0], w[1], w[2]) is None]
        if not todo:
            return
        contracts = [self.option(symbol, e, k, r, trading_class) for e, k, r in todo]
        qualified = [c for c in (self.ib.qualifyContracts(*contracts) or []) if c is not None and getattr(c, "conId", 0)]
        if not qualified:
            return
        for c, t in zip(qualified, self.ib.reqTickers(*qualified), strict=False):
            e, k, r = c.lastTradeDateOrContractMonth, float(c.strike), c.right[:1].upper()
            slot = cache["expiries"].setdefault(e, {"quotes": {}})["quotes"].setdefault(em._key(k), {})
            slot[r] = ticker_quote(t)

    def fetch(self, stock, symbol: str, target: str, now) -> dict:
        """The cache entry for one symbol and target date (YYYY-MM-DD)."""
        base = {"symbol": symbol, "target": target, "fetched": time.time(), "quoted_at": now.isoformat(),
                "market_open": em.market_open(now)}
        ch = self.chain(symbol, stock.conId)
        if ch is None or not ch.expirations:
            return {**base, "error": f"IBKR lists no options for {symbol}"}
        ex = em.pick_expiries(sorted(ch.expirations), target, sessions.today(now))
        if not ex["chosen"]:
            return {**base, "error": f"no {symbol} expiry on or after {target}"}
        [st] = self.ib.reqTickers(stock)
        q = ticker_quote(st)
        price, source = (q["last"], "last") if q["last"] else (q["close"], "close")
        if not price:
            m, how = em.mid(q)
            price, source = m, how
        if not price:
            return {**base, **ex, "error": f"no price for {symbol} from TWS"}
        cache = {**base, **ex, "price": price, "price_source": source, "trading_class": ch.tradingClass,
                 "expiries": {}, "warnings": []}
        strikes = sorted(float(k) for k in ch.strikes)
        near = sorted(strikes, key=lambda k: abs(k - price))[:CANDIDATES]
        # round 1: at the money, for the three expiries
        self.quote(symbol, ch.tradingClass, [(e, k, r) for e in (ex["prev"], ex["chosen"], ex["next"]) if e
                                             for k in near for r in "CP"], cache)
        s = em.straddle_at(cache, ex["chosen"], price)
        if not s:
            return {**cache, "error": f"no quotes for the {em.fmt_expiry(ex['chosen'])} expiry (US options market data?)"}
        move = s["value"]
        # round 2: the diagonal's legs: strikes near the move in this expiry, then one closer in the next weekly
        up = sorted([k for k in strikes if k >= price], key=lambda k: abs(k - (price + move)))[:CANDIDATES]
        dn = sorted([k for k in strikes if k <= price], key=lambda k: abs(k - (price - move)))[:CANDIDATES]
        self.quote(symbol, ch.tradingClass, [(ex["chosen"], k, "C") for k in up] + [(ex["chosen"], k, "P") for k in dn], cache)
        if ex["next"]:
            wanted = []
            for right in "CP":
                k = em.short_strike(cache, ex["chosen"], right, price, move)
                if k is None:
                    continue
                between = [x for x in strikes if (price <= x < k if right == "C" else k < x <= price)]
                wanted += [(ex["next"], x, right) for x in sorted(between, key=lambda x: abs(x - k))[:CANDIDATES]]
            self.quote(symbol, ch.tradingClass, wanted, cache)
        log.info("%s: option quotes for %s (expected move +/-%.2f)", symbol, em.fmt_expiry(ex["chosen"]), move)
        return cache
