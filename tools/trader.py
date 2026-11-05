"""The TWS collector's trader (#84): places the trade panel's orders on a TWS logged into an IBKR **paper** account.
The only code in the project that places, changes or cancels orders (app/envcheck.py checks that).

Runs inside the collector only when LIVE_ORDERS=paper in .env. It has a TWS connection of its own, to the paper
TWS (TRADE_HOST, TRADE_PORT: 7497 by default; client id TRADE_CLIENT_ID), apart from the collector's read-only
market data connection. It sends an order only while every account that TWS reports is a paper one (IDs start DU),
checked when it connects and again before each order; otherwise it refuses and says why. At most LIVE_MAX_SHARES
shares an order. Requests and status go through files (app/live_orders.py).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import live_orders  # noqa: E402

log = logging.getLogger("collector")
STATUS_EVERY = 3.0           # seconds between status writes
RETRY_EVERY = 30.0           # seconds between connection attempts


def _mask(account: str) -> str:
    a = str(account or "")
    return a[:2] + "…" + a[-4:] if len(a) > 6 else a


class Trader:
    def __init__(self, connect, clock=time.monotonic, host=None, port=None):
        """connect(): a connected ib_async IB (not read-only) to the paper TWS, or raises OSError."""
        self.connect_fn, self.clock = connect, clock
        self.host = host or os.environ.get("TRADE_HOST") or os.environ.get("IB_HOST", "host.docker.internal")
        self.port = int(port or os.environ.get("TRADE_PORT", "7497"))
        self.ib = None
        self.account = None
        self.refused = None
        self.message = None
        self.contracts: dict = {}
        self.last_try = self.last_status = None

    # ---------------------------------------------------------------- the connection and the paper check
    def _paper_account(self) -> str | None:
        """The paper account orders go to; None (with self.refused set) when TWS reports any account that isn't one."""
        accounts = [a for a in (self.ib.managedAccounts() or []) if a]
        if not accounts:
            self.refused = "TWS reports no account yet: no orders are sent."
            return None
        live = [a for a in accounts if not live_orders.is_paper(a)]
        if live:
            self.refused = (f"TWS on port {self.port} is logged into a live account ({', '.join(_mask(a) for a in live)}): "
                            "no orders are sent. Log that TWS into your paper account.")
            return None
        self.refused = None
        want = os.environ.get("TRADE_ACCOUNT", "").strip().upper()
        return want if want in accounts else accounts[0]

    def ensure(self) -> bool:
        if self.ib is not None and self.ib.isConnected():
            return True
        if self.last_try is not None and self.clock() - self.last_try < RETRY_EVERY:
            return False
        self.last_try = self.clock()
        try:
            self.ib = self.connect_fn()
        except (OSError, TimeoutError, ConnectionRefusedError) as e:
            self.ib, self.message = None, f"Can't reach the paper TWS at {self.host}:{self.port}: {e}"
            return False
        self.message = None
        self.contracts.clear()
        self.account = self._paper_account()
        log.info("Trader connected to the paper TWS at %s:%s, account %s%s", self.host, self.port,
                 _mask(self.account or ""), f" (refused: {self.refused})" if self.refused else "")
        return True

    # ---------------------------------------------------------------- one pass of the collector's loop
    def step(self) -> None:
        reqs = live_orders.take_requests()
        connected = self.ensure()
        for r in reqs:
            try:
                if not connected:
                    raise ValueError(self.message or "The trader isn't connected to the paper TWS")
                self.account = self._paper_account()           # every order: still a paper account
                if not self.account:
                    raise ValueError(self.refused)
                msg = self.carry_out(live_orders.check(r))
                live_orders.answer(r["id"], True, msg)
                log.info("Trader: %s", msg)
            except Exception as e:                            # noqa: BLE001  (say why to the page; carry on)
                live_orders.answer(r.get("id", "?"), False, str(e))
                log.warning("Trader refused %s: %s", r.get("action"), e)
        if reqs or self.last_status is None or self.clock() - self.last_status >= STATUS_EVERY:
            self.last_status = self.clock()
            self.write_status(connected)

    # ---------------------------------------------------------------- orders
    def contract(self, sym: str):
        if sym not in self.contracts:
            from ib_async import Stock
            c = Stock(sym, "SMART", "USD")
            if not self.ib.qualifyContracts(c):
                raise ValueError(f"TWS doesn't know {sym}")
            self.contracts[sym] = c
        return self.contracts[sym]

    def _ib_order(self, o: dict, action: str | None = None):
        from ib_async import Order
        side = action or ("BUY" if o["side"] == "buy" else "SELL")
        x = Order(action=side, totalQuantity=o["qty"], account=self.account, tif="DAY")
        if o["type"] == "market":
            x.orderType = "MKT"
        elif o["type"] == "limit":
            x.orderType, x.lmtPrice = "LMT", o["price"]
        elif o["type"] == "stop":
            x.orderType, x.auxPrice = "STP", o["price"]
        else:
            x.orderType = "TRAIL"
            if "amount" in o["trail"]:
                x.auxPrice = o["trail"]["amount"]
            else:
                x.trailingPercent = o["trail"]["pct"]
        return x

    def carry_out(self, a: dict) -> str:
        sym, k = a["symbol"], a["action"]
        c = self.contract(sym)
        if k == "order":
            o = self._ib_order(a["order"])
            self.ib.placeOrder(c, o)
            return f"{a['order']['side'].upper()} {a['order']['qty']} {sym} {a['order']['type']} sent"
        if k == "bracket":
            from ib_async import Order
            entry = self._ib_order(a["order"])
            entry.orderId, entry.transmit = self.ib.client.getReqId(), False
            back = "SELL" if a["order"]["side"] == "buy" else "BUY"
            target = Order(action=back, totalQuantity=a["order"]["qty"], orderType="LMT", lmtPrice=a["target"]["price"],
                           account=self.account, tif="DAY", parentId=entry.orderId, transmit=False)
            stop = Order(action=back, totalQuantity=a["order"]["qty"], account=self.account, tif="DAY",
                         parentId=entry.orderId, transmit=True)
            if "trail" in a["stop"]:
                stop.orderType, stop.auxPrice = "TRAIL", a["stop"]["trail"]["amount"]
            else:
                stop.orderType, stop.auxPrice = "STP", a["stop"]["price"]
            for o in (entry, target, stop):                  # the last one sends all three
                self.ib.placeOrder(c, o)
            return f"{a['order']['side'].upper()} {a['order']['qty']} {sym} with a stop and target sent"
        if k == "cancel":
            t = next((t for t in self.ib.openTrades() if t.order.orderId == a["order_id"] and t.contract.symbol == sym), None)
            if t is None:
                raise ValueError(f"No working order {a['order_id']} in {sym}")
            self.ib.cancelOrder(t.order)
            return f"cancel of order {a['order_id']} sent"
        # flatten: cancel the symbol's working orders, then close the position at market
        n = 0
        for t in self.ib.openTrades():
            if t.contract.symbol == sym and getattr(t.order, "account", self.account) in (self.account, "", None):
                self.ib.cancelOrder(t.order)
                n += 1
        qty = sum(p.position for p in self.ib.positions(self.account) if p.contract.symbol == sym)
        if qty:
            self.ib.placeOrder(c, self._ib_order({"side": "sell" if qty > 0 else "buy", "qty": int(abs(qty)), "type": "market"}))
        return f"flatten {sym}: {n} order(s) cancelled" + (f", {abs(qty):g} shares closed at market" if qty else ", no position")

    # ---------------------------------------------------------------- status for the page
    def write_status(self, connected: bool) -> None:
        s = {"connected": connected, "host": self.host, "port": self.port, "message": self.message,
             "account": _mask(self.account or "") or None, "paper": bool(self.account) and not self.refused,
             "refused": self.refused, "positions": [], "orders": [], "fills": []}
        if connected and self.account:
            try:
                s["positions"] = [{"symbol": p.contract.symbol, "qty": float(p.position), "avg": float(p.avgCost)}
                                  for p in self.ib.positions(self.account) if p.contract.secType == "STK"]
                s["orders"] = [_order_row(t) for t in self.ib.openTrades() if not t.isDone()]
                s["fills"] = [{"symbol": f.contract.symbol, "side": "buy" if f.execution.side == "BOT" else "sell",
                               "qty": float(f.execution.shares), "price": float(f.execution.price),
                               "time": f.execution.time.timestamp() if hasattr(f.execution.time, "timestamp") else None,
                               "order": f.execution.orderId}
                              for f in self.ib.fills() if f.execution.acctNumber == self.account]
            except Exception as e:                            # noqa: BLE001
                s["message"] = f"TWS: {e}"
        live_orders.write_status(s)

    def close(self) -> None:
        if self.ib is not None:
            self.ib.disconnect()


def _order_row(t) -> dict:
    o = t.order
    kind = {"MKT": "market", "LMT": "limit", "STP": "stop", "TRAIL": "trail"}.get(o.orderType, o.orderType.lower())
    price = o.lmtPrice if kind == "limit" else o.auxPrice if kind in ("stop", "trail") else None
    return {"id": o.orderId, "symbol": t.contract.symbol, "side": "buy" if o.action == "BUY" else "sell",
            "type": kind, "qty": float(o.totalQuantity), "price": price if price and price < 1e300 else None,
            "parent": o.parentId or None, "status": t.orderStatus.status}


def connect_paper(host: str, port: int, client_id: int):
    """A connection to the paper TWS that can place orders (the only one that isn't read-only)."""
    from ib_async import IB
    ib = IB()
    # the account's positions, working orders and today's executions come with the connection: the panel shows them
    ib.connect(host, port, clientId=client_id, readonly=False, timeout=20)
    return ib
