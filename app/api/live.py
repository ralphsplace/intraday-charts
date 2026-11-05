"""The trade panel's orders to the IBKR paper account (app/live_orders.py, tools/trader.py): its view of a symbol
(whether orders can be sent, the account, position, working orders, today's fills), and sending an action. 403
while orders are off (LIVE_ORDERS) or not possible (no trader, not connected, not a paper account)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import live_orders, sessions
from .common import call, one_symbol

router = APIRouter()


class ActionBody(BaseModel):
    action: str                             # order | bracket | cancel | flatten
    symbol: str
    order: dict | None = None               # order, bracket: {"side", "qty", "type", "price" | "trail"}
    stop: dict | None = None                # bracket: {"price"} or {"trail": {"amount" | "atr", ...}}
    target: dict | None = None              # bracket: {"price"}
    order_id: int | None = None             # cancel: TWS's id of the order


@router.get("/api/live")
def live_view(symbol: str):
    return live_orders.view(one_symbol(symbol))


@router.post("/api/live/orders")
def live_order(req: ActionBody):
    """Send an action to the trader and wait a few seconds for its answer: {"ok", "message"}, or {"ok": None} when
    it hasn't answered yet (the panel's view shows what happened)."""
    why = live_orders.why_not()
    if why:
        raise HTTPException(403, why)
    action = {k: v for k, v in req.model_dump().items() if v is not None}
    action["symbol"] = one_symbol(req.symbol)
    now = sessions.now_et()
    action = call(live_orders.resolve_atr, action, sessions.today(now), now.hour * 60 + now.minute)
    action = call(live_orders.check, action)
    r = live_orders.wait(live_orders.submit(action)["id"])
    if r is None:
        return {"ok": None, "message": "Sent; TWS hasn't answered yet.", "view": live_orders.view(action["symbol"])}
    if not r["ok"]:
        raise HTTPException(409, r["message"])
    return {**r, "view": live_orders.view(action["symbol"])}
