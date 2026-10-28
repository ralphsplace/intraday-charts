"""Check what market data your TWS login can deliver to this dashboard. Read-only; places no orders.

For each contract it reports:
  - whether IBKR knows it (and its contract id)
  - live data: real-time, delayed, or not subscribed
  - how far back historical data goes, and whether 1-minute bars come back (recent and older)
Then it checks news: which news feeds your account can use through the API, and whether QQQ headlines
come back for the last week and for a week about a year ago.

    python tools/probe_ibkr.py                      # QQQ, SPY, and the NYSE / Nasdaq breadth indexes
    python tools/probe_ibkr.py --host 192.168.1.50  # TWS on another PC
    docker compose run --rm collector python tools/probe_ibkr.py --client-id 19
"""
from __future__ import annotations

import argparse
import re
import os
import sys
import time

CONTRACTS = [
    # (label, symbol, secType, exchange)
    ("QQQ (Nasdaq ETF)", "QQQ", "STK", "SMART"),
    ("SPY", "SPY", "STK", "SMART"),
    ("NYSE TICK", "TICK-NYSE", "IND", "NYSE"),
    ("NYSE advance/decline", "AD-NYSE", "IND", "NYSE"),
    ("NYSE up/down volume", "VOL-NYSE", "IND", "NYSE"),
    ("CBOE VIX", "VIX", "IND", "CBOE"),
    ("NYSE TRIN", "TRIN-NYSE", "IND", "NYSE"),
    ("Nasdaq TICK", "TICK-NASD", "IND", "NASDAQ"),
    ("Nasdaq-100 TICK", "TICK-NDX", "IND", "NASDAQ"),
    ("Nasdaq advance/decline", "AD-NASD", "IND", "NASDAQ"),
    ("Nasdaq TRIN", "TRIN-NASD", "IND", "NASDAQ"),
]
MD_TYPES = {1: "REAL-TIME", 2: "FROZEN", 3: "DELAYED", 4: "DELAYED-FROZEN"}
INFO = {2104, 2106, 2107, 2108, 2119, 2158, 2174}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default=os.environ.get("IB_HOST", "host.docker.internal"))
    p.add_argument("--port", type=int, default=int(os.environ.get("IB_PORT", "7496")))
    p.add_argument("--client-id", type=int, default=19)
    args = p.parse_args(argv)

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from app import envcheck
    envcheck.require_local_tws(args.host)        # TWS must be on this machine or the home network

    from ib_async import IB, Contract
    ib = IB()
    errors: list = []
    ib.errorEvent += lambda reqId, code, msg, contract=None, *a: code in INFO or errors.append((code, str(msg)))
    print(f"Connecting to TWS at {args.host}:{args.port} (read-only, client id {args.client_id})...")
    ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=30)
    ib.reqMarketDataType(3)    # real-time if subscribed, otherwise fall back to delayed, so we can tell which

    qqq_id = None
    for label, sym, sec, exch in CONTRACTS:
        print(f"\n=== {label}: {sym} ({sec}, {exch})")
        errors.clear()
        c = Contract(symbol=sym, secType=sec, exchange=exch, currency="USD")
        if not ib.qualifyContracts(c):
            print("  contract: NOT FOUND at IBKR", *(f"\n  TWS {k}: {m}" for k, m in errors))
            continue
        print(f"  contract: found, conId {c.conId}, primary exchange {c.primaryExchange or c.exchange}")
        if sym == "QQQ":
            qqq_id = c.conId

        # live / delayed
        errors.clear()
        t = ib.reqMktData(c, "", False, False)
        ib.sleep(4)
        kind = MD_TYPES.get(getattr(t, "marketDataType", 0), "none")
        val = next((v for v in (t.last, t.close, t.marketPrice()) if v == v and v is not None), None)
        print(f"  live data: {kind}" + (f", value {val}" if val is not None else ", no value received"))
        if sym in ("AD-NYSE", "VOL-NYSE"):        # these send their values as bid/ask (recorded as ADD / VOLD)
            print(f"  bid {t.bid}, ask {t.ask} -> bid - ask = {t.bid - t.ask if t.bid == t.bid and t.ask == t.ask else 'n/a'}")
        for k, m in errors:
            print(f"  TWS {k}: {m}")
        ib.cancelMktData(c)

        # how far back
        for what in ("TRADES", "MIDPOINT"):
            errors.clear()
            try:
                head = ib.reqHeadTimeStamp(c, whatToShow=what, useRTH=True, formatDate=1)
            except Exception as e:  # noqa: BLE001
                head = None
                errors.append(("-", str(e)))
            if head:
                print(f"  history ({what}): available from {head}")
                break
            print(f"  history ({what}): none reported" + "".join(f" | TWS {k}: {m}" for k, m in errors))
        else:
            what = "TRADES"

        # 1-minute bars: yesterday and about a year ago
        for end, name in (("", "most recent day"), (time.strftime("%Y%m%d 16:00:00 US/Eastern",
                                                                    time.localtime(time.time() - 365 * 86400)),
                                                      "one year ago")):
            errors.clear()
            bars = ib.reqHistoricalData(c, endDateTime=end, durationStr="1 D", barSizeSetting="1 min",
                                        whatToShow=what, useRTH=True, formatDate=2, timeout=60)
            if bars:
                b = bars[len(bars) // 2]
                print(f"  1-min bars, {name}: {len(bars)} bars, e.g. {b.date:%Y-%m-%d %H:%M} "
                      f"O {b.open} H {b.high} L {b.low} C {b.close}")
            else:
                print(f"  1-min bars, {name}: none" + "".join(f" | TWS {k}: {m}" for k, m in errors))
            ib.sleep(2)

    news(ib, qqq_id, errors)
    ib.disconnect()
    print("\nDone. Paste this output back into the chat.")


def news(ib, con_id, errors):
    """Which news feeds the API can use, and how far back QQQ headlines go."""
    import datetime as dt
    print("\n=== News")
    errors.clear()
    try:
        providers = ib.reqNewsProviders() or []
    except Exception as e:  # noqa: BLE001
        providers = []
        errors.append(("-", str(e)))
    if not providers:
        print("  news feeds: none available to the API" + "".join(f" | TWS {k}: {m}" for k, m in errors))
        return
    print("  news feeds: " + ", ".join(f"{p.code} ({p.name})" for p in providers))
    if not con_id:
        print("  (QQQ contract not found, so no headline check)")
        return
    codes = "+".join(p.code for p in providers)
    now = dt.datetime.now()
    for name, start, end in (("last 7 days", now - dt.timedelta(days=7), now),
                             ("6 months ago (7 days)", now - dt.timedelta(days=189), now - dt.timedelta(days=182)),
                             ("one year ago (7 days)", now - dt.timedelta(days=372), now - dt.timedelta(days=365))):
        errors.clear()
        try:
            items = ib.reqHistoricalNews(con_id, codes, start.strftime("%Y-%m-%d %H:%M:%S.0"),
                                         end.strftime("%Y-%m-%d %H:%M:%S.0"), 300)   # IBKR's date format
        except Exception as e:  # noqa: BLE001
            items = []
            errors.append(("-", str(e)))
        items = items if isinstance(items, list) else ([items] if items else [])
        if not items:
            print(f"  QQQ headlines, {name}: none" + "".join(f" | TWS {k}: {m}" for k, m in errors))
            ib.sleep(1)
            continue
        by_feed: dict = {}
        for it in items:
            by_feed[it.providerCode] = by_feed.get(it.providerCode, 0) + 1
        times = sorted(str(it.time) for it in items)
        print(f"  QQQ headlines, {name}: {len(items)} ({', '.join(f'{k} {v}' for k, v in by_feed.items())}), "
              f"{times[0]} to {times[-1]}")
        for it in items[:3]:
            print(f"    {it.time}  [{it.providerCode}] {re.sub(r'^[{][^}]*[}]', '', str(it.headline))[:110]}")
        ib.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
