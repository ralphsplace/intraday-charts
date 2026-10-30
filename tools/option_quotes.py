"""Option quotes from TWS (snapshots, read-only), for the expected-move and option-chain pages.

One job: ask TWS for the option quotes a page needs. For the expected-move page (fetch), two rounds of snapshots:
  1. the stock, and the at-the-money calls and puts of the chosen expiry, the one before it and the next weekly
     (the strikes either side of the price), which give the expected move;
  2. the strikes nearest that move in the chosen expiry (the diagonal's short legs) and the strikes one closer to
     the money in the next weekly (its long legs).
For the option-chain page (fetch_chain): a window of strikes around the price for the expiries asked for, plus the
at-the-money strikes of the next few expiries (their expected moves, for the expiry strip), and the open interest of
the window's options (for the strike profile). TWS sends open interest only on a subscription (generic tick 101, not
with snapshots), so those are subscribed for a few seconds and cancelled; it changes once a day, so a later fetch the
same day reuses it.
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
BATCH = 60              # option snapshots asked for at once (IBKR allows about 100 open quote lines)
OI_WAIT = 3.0           # seconds TWS takes to send open interest after a subscription starts


def _clean(x) -> float | None:
    """IBKR sends nan or -1 for "no value"."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def _greek(g, name) -> float | None:
    """A model Greek (delta and theta may be negative); nan means none."""
    try:
        x = float(getattr(g, name, None))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def ticker_quote(t) -> dict:
    g = getattr(t, "modelGreeks", None)
    q = {"bid": _clean(getattr(t, "bid", None)), "ask": _clean(getattr(t, "ask", None)),
         "last": _clean(getattr(t, "last", None)), "close": _clean(getattr(t, "close", None)),
         "iv": _clean(getattr(g, "impliedVol", None)) if g is not None else None}
    if g is not None:
        for name in ("delta", "gamma", "theta", "vega"):
            v = _greek(g, name)
            if v is not None:
                q[name] = v
    return q


def _option(symbol, expiry, strike, right, trading_class):
    from ib_async import Option
    return Option(symbol, expiry, strike, right, "SMART", currency="USD", tradingClass=trading_class)


class OptionQuotes:
    def __init__(self, ib, option=_option):
        self.ib, self.option = ib, option
        self.contracts = {}                     # (expiry, strike, right) -> the qualified contract, this fetch

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
            self.contracts[(e, k, r)] = c

    def open_interest(self, wanted: list[tuple[str, float, str]], cache: dict, known: dict) -> None:
        """Each option's open interest ("oi" in its quote): from `known` ({(expiry, strike, right): oi}, fetched
        earlier today), else subscribed (generic tick 101) for OI_WAIT seconds, read and cancelled."""
        todo = []
        for e, k, r in wanted:
            q = em.quote(cache, e, k, r)
            if q is None:
                continue
            if (e, k, r) in known:
                q["oi"] = known[(e, k, r)]
            elif (e, k, r) in self.contracts:
                todo.append((e, k, r))
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            tickers = [self.ib.reqMktData(self.contracts[w], "101", False, False) for w in batch]
            self.ib.sleep(OI_WAIT)
            for (e, k, r), t in zip(batch, tickers, strict=True):
                oi = _clean(getattr(t, "callOpenInterest" if r == "C" else "putOpenInterest", None))
                if oi is not None:
                    em.quote(cache, e, k, r)["oi"] = oi
                self.ib.cancelMktData(self.contracts[(e, k, r)])

    def stock_price(self, stock) -> tuple[float | None, str | None]:
        """The stock's last trade, else its close, else its bid/ask mid."""
        [st] = self.ib.reqTickers(stock)
        q = ticker_quote(st)
        if q["last"]:
            return q["last"], "last"
        if q["close"]:
            return q["close"], "close"
        return em.mid(q)

    def fetch_chain(self, stock, symbol: str, wanted: list[str], window: int, now, previous: dict | None = None) -> dict:
        """The option-chain cache for one symbol, all quoted at one time: `window` strikes either side of the
        price in each wanted expiry (YYYYMMDD; none listed: the nearest), and the two strikes either side of the
        price in each of the first STRIP expiries (their expected moves, for the page's expiry strip)."""
        from app import option_chain as oc
        base = {"symbol": symbol, "fetched": time.time(), "quoted_at": now.isoformat(), "market_open": em.market_open(now)}
        ch = self.chain(symbol, stock.conId)
        if ch is None or not ch.expirations:
            return {**base, "error": f"IBKR lists no options for {symbol}"}
        today = sessions.today(now).replace("-", "")
        expirations = sorted(e for e in ch.expirations if e >= today)
        price, source = self.stock_price(stock)
        if not price:
            return {**base, "error": f"no price for {symbol} from TWS"}
        strikes = sorted(float(k) for k in ch.strikes)
        wanted = [e for e in dict.fromkeys(wanted) if e in expirations][:oc.MAX_EXPIRIES] or expirations[:1]
        cache = {**base, "price": price, "price_source": source, "trading_class": ch.tradingClass,
                 "expirations": expirations, "strikes": strikes, "wanted": wanted, "window": window, "expiries": {}}
        near = sorted(strikes, key=lambda k: (abs(k - price), k))
        todo = [(e, k, r) for e in wanted for k in near[:2 * window + 1] for r in "CP"]
        todo += [(e, k, r) for e in expirations[:oc.STRIP] if e not in wanted for k in near[:CANDIDATES] for r in "CP"]
        self.contracts = {}
        for i in range(0, len(todo), BATCH):               # a few dozen at a time: IBKR limits open quote lines
            self.quote(symbol, ch.tradingClass, todo[i:i + BATCH], cache)
        day = sessions.today(now)
        known = {}
        if previous and previous.get("oi_day") == day:     # open interest changes once a day: reuse today's
            for e, ex in (previous.get("expiries") or {}).items():
                for key, sides in (ex.get("quotes") or {}).items():
                    for r, q in sides.items():
                        if q.get("oi") is not None:
                            known[(e, float(key), r)] = q["oi"]
        try:
            self.open_interest([w for w in todo if w[0] in wanted], cache, known)
            cache["oi_day"] = day
        except Exception as e:                            # noqa: BLE001  (the quotes are still good without it)
            log.warning("%s: open interest: %s", symbol, e)
        if not any((cache["expiries"].get(e) or {}).get("quotes") for e in wanted):
            return {**cache, "error": f"no quotes for {symbol} options (US options market data?)"}
        log.info("%s: option chain for %s (%d strikes each)", symbol, ", ".join(em.fmt_expiry(e) for e in wanted),
                 2 * window + 1)
        return cache

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
        price, source = self.stock_price(stock)
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
