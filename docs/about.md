# Licence and thanks

## Licence

Apache License 2.0: see `LICENSE` and `NOTICE`. The bundled TradingView Lightweight Charts library is
also Apache 2.0 (`app/static/vendor/lightweight-charts.LICENSE`).

## Thanks

This project stands on the work of others:

- **[TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/)** (Apache 2.0): the chart
  library that draws every chart. Bundled in `app/static/vendor/` with its licence.
- **[Anthropic's Claude](https://www.anthropic.com/claude)**: wrote the code, tests and documentation with
  the author, and researched the indicators, data sources and event calendar.
- **[Interactive Brokers](https://www.interactivebrokers.com/)**: Trader Workstation and its API supply
  the bars, market internals and news headlines.
- **[ib_async](https://github.com/ib-api-reloaded/ib_async)**: the Python client for the TWS API.
  It carries on Ewald de Wit's ib_insync and is maintained by the ib-api-reloaded community.
- **Python libraries:**
  - [FastAPI](https://fastapi.tiangolo.com/) and [Uvicorn](https://www.uvicorn.org/), the web server.
  - [pandas](https://pandas.pydata.org/), [NumPy](https://numpy.org/) and
    [Apache Arrow (pyarrow)](https://arrow.apache.org/), the bar cache and the calculations.

  - [pytest](https://pytest.org/) and [Playwright](https://playwright.dev/), the tests and the browser checks.
- **Indicator authors:**
  - Saty Mahajan: ATR Levels.
  - Used by the backtester: Walid Khalil and David Steckler (Volume Zone Oscillator), thinkorswim's
    STO_VZO study, technicalwhale and Sam4Cok's port ("Trading BUY/SELL Signal"), and tosindicators
    (Supply Demand Edge).
- **Event data:**
  - The Federal Reserve: FOMC dates.
  - The U.S. Bureau of Labor Statistics: CPI and jobs report dates.
  - The U.S. Bureau of Economic Analysis: GDP and PCE dates.
  - Financial Modeling Prep: earnings dates.
  - [SEC EDGAR](https://www.sec.gov/edgar/search/): earnings report dates and times, for the earnings view.
  - [The GDELT Project](https://www.gdeltproject.org/): world news, for moves without IBKR headlines.
- **[Docker](https://www.docker.com/)**: runs the dashboard and collector on the NAS.
