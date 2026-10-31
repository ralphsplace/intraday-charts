"""The TWS collector's reader of the account's positions, for a watch list's Holdings list (app/positions.py).

Runs only when HOLDINGS=on in .env, and only in live mode. It asks TWS for positions (reqPositions) on the
collector's read-only connection about once a minute: no orders, no executions, no account values. Account
numbers are masked before they're written.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import positions  # noqa: E402

log = logging.getLogger("collector")
EVERY = 60.0                 # seconds between reads


def read_positions(ib) -> dict:
    out, accounts = [], []
    for p in ib.reqPositions():
        c = p.contract
        acct = positions.mask(p.account)
        if acct not in accounts:
            accounts.append(acct)
        out.append({"account": acct, "symbol": str(getattr(c, "symbol", "") or ""),
                    "sec_type": str(getattr(c, "secType", "") or ""), "currency": str(getattr(c, "currency", "") or ""),
                    "qty": float(p.position), "avg_cost": float(p.avgCost)})
    return {"positions": out, "accounts": accounts, "fetched": time.time()}


class PositionsReader:
    def __init__(self, ib, clock=time.monotonic, every: float = EVERY):
        self.ib, self.clock, self.every, self.last = ib, clock, every, None

    def sync(self) -> None:
        if self.last is not None and self.clock() - self.last < self.every:
            return
        self.last = self.clock()
        try:
            data = read_positions(self.ib)
        except Exception as e:                       # noqa: BLE001  (TWS or ib_async: tell the page, carry on)
            data = {"error": f"TWS: {e}", "fetched": time.time()}
            log.warning("Positions: %s", data["error"])
        positions.write(data)
