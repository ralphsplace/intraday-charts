# Getting started

## Install

```bash
unzip intraday-charts.zip && cd intraday-charts
cp .env.example .env                     # IB_HOST: host.docker.internal by default
docker compose --profile collector up -d --build
```

Before the first start, set up TWS's API settings ([Connecting to TWS](tws.md#set-up-tws-once)). If TWS runs on
a different machine from Docker (e.g. Docker on the NAS), set `IB_HOST` in `.env` to that PC's LAN address. Then
open `http://<your-nas>:8050`.

Two containers run:

- `intraday-charts`: the web server (the pages).
- `intraday-charts-collector`: the TWS collector, which fetches bars and option quotes and fills the cache.

## Addresses

| Address | Page |
|---|---|
| `http://<your-nas>:8050/` | the default dashboard (QQQs to start with) |
| `http://<your-nas>:8050/QQQs` | a dashboard by name ([Dashboards](dashboards.md)) |
| `http://<your-nas>:8050/dashboards` | create, rename, duplicate, delete dashboards and pick the default |
| `http://<your-nas>:8050/earnings` | the [Earnings view](earnings.md) |
| `http://<your-nas>:8050/expected-move` | the [Expected move view](expected-move.md) |
| `http://<your-nas>:8050/options` | the [Option chain view](option-chain.md) |

Every page has the same drop-down at the top left to move between them.

The pages can only be opened from your home network: see [Purpose and security model](security.md).

## The first time

A new install starts with an **empty cache**. The first time you open the page, you get:

- **One QQQ chart:** 3-minute candles, today, with no studies.
- **The Load data dialog.** Its date defaults to the last completed trading day. The charts on screen
  are requested straight away; add symbols there if you want more.

A chart says what it is waiting for, e.g. "number 3 of 12 in the queue". When its bars arrive, it
draws them by itself. If the collector isn't running yet, requests are kept and run when it starts.

From there:

1. Type a symbol into the chart's symbol box and press Enter. Its bars are fetched if they aren't cached.
2. Add studies with **f(x)** ([Studies](studies.md)).
3. Change how the price is drawn (the price type) beside the days menu ([Charts](charts.md)).
4. Add charts with **Layout**, or a chart's **≡** menu ([Layouts and the watch list](layouts.md)).
5. Step through the day with the replay controls, or press **Live** ([Replay and Live](charts.md#replay-and-live)).
6. Save the window under **Layouts ▾** so other browsers and devices can load it.

## Upgrading from `intraday-chart`

`intraday-chart` is the project's earlier name. Keep your `data` folder and `.env`:

1. In the old folder, stop the old containers: `docker compose --profile collector down`
2. Rename the folder from `intraday-chart` to `intraday-charts` (your data and `.env` move with it).
3. Unzip `intraday-charts.zip` into the folder above it, so it lands on the renamed folder, then
   `docker compose --profile collector up -d --build` from `intraday-charts`.

The containers are now `intraday-charts` and `intraday-charts-collector`. Each browser moves its saved
windows, drawings and earnings-page choices to the new names the first time it opens a page.
