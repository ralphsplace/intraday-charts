# Intraday Charts

A self-hosted intraday charting dashboard for stocks and ETFs (QQQ first), modelled on thinkorswim
chart grids. It runs in Docker on your NAS and reads 1-minute bars from a local cache. The cache is
filled from Trader Workstation (TWS): type a symbol into a chart, or pick symbols and a day under
**Load data**, and the collector fetches them.

![A 2-over-4 dashboard in Live on Oct 30: QQQ 3-minute candles with VWAP, Bollinger bands, SMAs, the MA cloud, VZO dots, a trend line, a line and an alert that has fired (top left); QQQ's current price over ATR levels and the volume profile (top right); VOLD-NYSE, -VIX, TICK-NYSE and ADD-NYSE below. The drawing tools are in the top bar](img/scalpingView.png)

It is **read-only**: it never places or prepares orders. The connection to TWS is opened read-only, and you
can also tick TWS's own *Read-Only API* setting. It can only be reached from your home network
([Purpose and security model](security.md)).

## The views

| View | What it's for |
|---|---|
| [Charts](charts.md) | One or more charts per window: candle durations from 1 minute to 1 month, price types, drawings and alerts, replay of any cached day, and Live. |
| [Layouts and the watch list](layouts.md) | Grids of charts (2 over 4, 3×3, …), adding and removing charts, and a watch list that drives a linked chart. |
| [Dashboards](dashboards.md) | Named windows with their own addresses, including the built-in market Internals dashboard. |
| [Studies](studies.md) | Overlays, volume, profiles, oscillators, market internals and level studies (prior day, S/R ladder, session levels, ATR levels, events). |
| [Earnings view](earnings.md) | A stock's last 6 earnings reports drawn over each other, around the report day. |
| [Expected move view](expected-move.md) | The options' expected move by a date for several stocks, with diagonal legs. |
| [Config page](config.md) | The application config: named watch lists, each watch list type's columns, study defaults, paper accounts. |
| [Paper trading](paper.md) | Practise trades in Replay with a simulated paper account; how fills are modelled, and the limits. |
| [Option chain view](option-chain.md) | Build an option structure from the chain and evaluate it: risk graph, profit/loss grid, strike profile. |

## Setting up and running

- [Getting started](getting-started.md): install, addresses, the first time.
- [Connecting to TWS](tws.md): TWS settings, the collector, market internals, watchlists.
- [Configuration](configuration.md): `.env`, `config.json`, `data/events.json`.
- [Tools](tools.md): the signal backtester and the market-events tool.
- [Known limitations](limitations.md).
- [Development](development.md): how the code is organized, adding a study, project layout, tests.
