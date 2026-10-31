# Intraday Charts: multi-chart layouts, studies and levels

A self-hosted intraday charting dashboard for stocks and ETFs (QQQ first), modelled on thinkorswim
chart grids. It runs in Docker on your NAS and reads 1-minute bars from a local cache. The cache is
filled from Trader Workstation (TWS): type a symbol into a chart, or pick symbols and a day under
**Load data**, and the collector fetches them.

![A 2-over-4 dashboard in Live on Oct 30: QQQ 3-minute candles with VWAP, Bollinger bands, SMAs, the MA cloud, VZO dots, a trend line, a line and an alert that has fired (top left); QQQ's current price over ATR levels and the volume profile (top right); VOLD-NYSE, -VIX, TICK-NYSE and ADD-NYSE below. The drawing tools are in the top bar](docs/img/scalpingView.png)

- **Read-only.** It never places or prepares orders. Every TWS connection is opened read-only, the code
  contains no order calls, and a test fails if one is ever added.
- **Home network only.** No logins: every request must come from your home network, pages can't be used by
  other websites, and an environment check at startup stops the server if something is unsafe.
  See [Purpose and security model](docs/security.md).

## User guide

**<https://ralphsplace.github.io/intraday-charts/>**, built from [`docs/`](docs/index.md) on every change to `main`.

| Page | What's in it |
|---|---|
| [Getting started](docs/getting-started.md) | Install, addresses, the first time, upgrading |
| [Charts](docs/charts.md) | Candle durations, price types, replay and Live, drawings and alerts, saved views |
| [Layouts and the watch list](docs/layouts.md) | Grids of charts, adding and removing charts, the watch list |
| [Dashboards](docs/dashboards.md) | Named dashboards, and the market Internals dashboard |
| [Studies](docs/studies.md) | Every study, the support / resistance ladder |
| [Earnings view](docs/earnings.md) | A stock's last 6 earnings reports, drawn over each other |
| [Expected move view](docs/expected-move.md) | The options' expected move by a date, with diagonal legs |
| [Config page](docs/config.md) | Named watch lists, default columns, study defaults (the application config) |
| [Option chain view](docs/option-chain.md) | Build and evaluate option structures; the strike profile |
| [Connecting to TWS](docs/tws.md) | TWS settings, the collector, market internals, watchlists |
| [Configuration](docs/configuration.md) | `.env`, `config.json`, `data/events.json` |
| [Tools](docs/tools.md) | The signal backtester and the market-events tool |
| [Known limitations](docs/limitations.md) | What isn't covered or tested yet |
| [Development](docs/development.md) | How the code is organized, adding a study, project layout, tests |

## Quick start

```bash
unzip intraday-charts.zip && cd intraday-charts
cp .env.example .env                     # IB_HOST: host.docker.internal by default
docker compose --profile collector up -d --build
```

Set up TWS's API settings first ([Connecting to TWS](docs/tws.md#set-up-tws-once)). Then open
`http://<your-nas>:8050`. More in [Getting started](docs/getting-started.md).

## Development

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium     # for the browser tests
ruff check app tools tests                # lint
pytest --cov                              # every test, with Python and JavaScript coverage
pip install -r requirements-docs.txt && mkdocs serve   # preview the user guide
```

Details in [Development](docs/development.md#tests).

## Licence

Apache License 2.0: see `LICENSE` and `NOTICE`. The bundled TradingView Lightweight Charts library is
also Apache 2.0 (`app/static/vendor/lightweight-charts.LICENSE`). This project stands on the work of
others: see [Licence and thanks](docs/about.md).
