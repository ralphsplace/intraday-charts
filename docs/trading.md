# Trading on your IBKR paper account

The [trade panel](#the-trade-panel) places orders on your **IBKR paper account**, through Trader Workstation. It is
off until you turn it on, and it only ever sends orders to a paper account: everything else in the app (charts,
market data, backtests) stays read-only.

## Turning it on

1. **Log a second TWS into your paper account.** IBKR's paper account is a separate login (Paper Trading, in the
   TWS login screen). Market data still comes from your live TWS, as before.
2. In the paper TWS: **Configure > API > Settings**: tick **Enable ActiveX and Socket Clients**, untick
   **Read-Only API** (orders need it off), and note the **Socket port** (7497 by default for paper). Add the NAS's
   address to **Trusted IPs** if TWS runs on another PC.
3. In `.env` on the NAS:

    ```
    LIVE_ORDERS=paper
    TRADE_PORT=7497            # the paper TWS's API port
    TRADE_HOST=                # its address, if it's not the same PC as your live TWS (IB_HOST)
    LIVE_MAX_SHARES=1000       # the most shares in one order
    ```

4. Restart: `docker compose --profile collector up -d`. If the collector runs on the TWS PC instead
   (`tools/run_collector_windows.bat`), set `LIVE_ORDERS=paper` in that file too. The collector's log says
   *Orders to the IBKR paper account are on*, and the [environment check](dashboards.md) shows the account.

## The safeguards

- **Off by default.** Without `LIVE_ORDERS=paper`, no TWS connection can place an order, and the panel says so.
- **Paper accounts only.** The collector's trader (`tools/trader.py`) has its own connection, to the paper TWS. It
  sends an order only while every account that TWS reports is a paper one (IBKR paper account IDs start `DU`). It
  checks when it connects, and again before every order. If that TWS is logged into a live account, every order is
  refused, the panel says why, and the environment check shows a warning.
- **One place.** Order calls exist only in `tools/trader.py`. A test fails, and the server refuses to start, if
  one appears anywhere else; the market data connection is still opened read-only.
- **Limits.** Stocks and ETFs only; at most `LIVE_MAX_SHARES` shares an order; day orders, regular hours.
- **Home network only**, as the rest of the dashboard ([security](security.md)).

## The trade panel

On any cell's **≡** menu, **+ Trade panel left** or **+ Trade panel right**. It follows the symbol of its
[link group](layouts.md) (the coloured square), or of the active chart when it isn't linked.

- The header shows the account (**IBKR paper DU…1234**), or why orders can't go (off, the trader not running, not
  connected, a live account).
- It shows the position and its unrealized P/L at the chart's last price, the **working orders** (× cancels one) and
  **today's fills**, as TWS reports them, every few seconds. A new fill shows a message with a sound.
- The ticket: **Market**, **Limit**, **Stop**, **Trailing stop** (a dollar distance) or **Trail × ATR** (a multiple of
  the ATR on the followed chart's bars, worked out when the order goes in), the shares, and **Stop and target**
  (a bracket: the entry, with a stop and a target a distance from the last price, which cancel each other in TWS).
  Then **Buy**, **Sell** or **Flatten** (cancel the symbol's working orders and close the position at market).
- Orders go only in **Live** (the chart's price is today's); in Replay the panel shows the account but doesn't trade.

[Backtests](backtesting.md) and a chart's **Signals** never trade: they're simulated from the cached bars.
