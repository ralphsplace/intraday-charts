# Development

Each part does one job and talks to the others through one small interface:

- **Indicator maths** (`app/indicators.py`): plain functions on bars, no drawing.
- **Studies** (`app/studies/`): `base.py` is the interface (`@study`, settings, plots, outputs); every
  other module is one family (overlays, volume, profiles, oscillators, levels, internals).
  The server and the page only use the interface: the catalogue and `run_study`.
- **Price types** (`app/static/js/pricetypes.js`): each one draws the price on its own series. The chart
  only calls `create(chart, {type, params})`, then `setData(bars)` and `destroy()`. The chart's
  candle series stays as an invisible anchor that studies, levels and drawings attach to.
- **Study outputs** (`app/static/js/outputs/`): how each kind of study result is drawn (lines,
  histograms, reference lines, bands, levels, volume profile, cloud, opening-range box, event lines,
  label boxes). One module per kind, all with the same hooks; the chart only runs the hooks.
- **Drawing tools** (`app/static/js/tools/`): Alert, Line and Trend, one module each, all with the same
  hooks (clicks, label, settings, drawing, alert check). The header buttons, legend, settings dialog and
  alerts are built from the list.
- **Shared look** (`app/static/js/styles.js`): line types, dash patterns and colours, used everywhere.
  The Python copy of the line types (`app/studies/base.py`) is checked against it by the tests.
- **Signals** (`tools/signals.py`): buy/sell rules, used only by the backtester; nothing draws them.

## Adding a study

Put it in the module for its family. Each study is one decorated function:

```python
@study("my_avg", "My average", "Overlays", "price",
       [P("length", "Length", "int", 10, min=1, max=200)],
       lambda p: f"My avg ({p['length']})", "One-line description for the Studies dialog.",
       plots=[plot("avg", "Average", "#4d9de0")])
def _my_avg(ctx, p):
    w = ctx.warm(p["length"])                       # today's bars plus warm-up from prior days
    values = w["close"].rolling(p["length"]).mean()
    return {"lines": [ln("avg", "My avg", ctx.points(w, values))]}
```

- The settings dialog is generated from the parameter list; each `plot` adds color, line type and thickness settings.
- The legend, Hide and Remove come for free.
- Use `pane="own"` for an oscillator pane.
- Return `levels` for horizontal price levels, or `hlines` for reference lines in the study's own pane.
- Other outputs: `labels` (colored boxes at the top of the chart), `bands` (shaded zones in a study
  pane), `profile` (volume-at-price histogram), `cloud`, `box` and `verticals`. `app/studies/outputs.py`
  lists them all with their fields. Every result is checked against that list: a study that returns
  something malformed shows the problem on its legend entry and the rest of the chart carries on.
- Return `note` for a short text next to the study's name, and `needs` (a list of symbols) when the study
  reads other symbols' bars: the chart asks the collector for them.
- Add `intraday=True` to `@study` when the study needs 1-minute bars; on 1d / 1w / 1M charts it then
  says "intraday charts only" instead of running.

## Adding a price type

Add a `define({...})` to `app/static/js/pricetypes.js`:

```js
define({
  id: "dots", name: "Dots", description: "A dot at each close.",
  params: [P("color", "Color", "color", "#c9d1db", "Dots"), P("size", "Size", "int", 3, "Dots", { min: 1, max: 8 })],
  create(chart, p) {
    const s = chart.addSeries(LWC.LineSeries, { lineVisible: false, pointMarkersVisible: true,
                                                pointMarkersRadius: p.size, color: p.color });
    return { setData: (bars) => s.setData(bars.map((b) => ({ time: b.time, value: b.close }))),
             destroy: () => chart.removeSeries(s) };
  },
});
```

It appears in every chart's price-type menu, and its settings dialog is built from `params`.

## Adding a drawing tool or a kind of study output

Add a module to `app/static/js/tools/` (or `app/static/js/outputs/`) and list it in that folder's
`index.js`. The comment at the top of `index.js` describes the hooks; the existing modules are short
examples (`hline.js` for a tool, `labels.js` for an output). A tool can also act on its clicks without
storing a drawing (`place`): `avwap.js` adds a study.

## Project layout

```
app/engine.py           day context (bars, warm-up, VWAP, opening range, expected range); no look-ahead
app/holdings.py         fund holdings for the Heavyweights study (app/heavyweights.json, data/ override)
app/periods.py          daily, weekly and monthly candles (period context); the replay day from its minutes
app/timeframes.py       the candle durations a chart offers, and the range each shows
app/indicators.py       indicator maths (SMA/EMA/WMA, RSI, MACD, Bollinger, ATR, ADX, value area, ...)
app/studies/base.py     the study interface: @study, settings, plots, run_study, catalog
app/studies/outputs.py  what a study may return; every result is checked against it
app/studies/*.py        one module per family: overlays, volume, profiles, oscillators, levels, internals
app/server.py           web server: the pages (/, /<dashboard>, /dashboards) and the /api endpoints
app/store.py            Parquet cache (1-minute days and daily bars); derived symbols such as -VIX
app/control.py          requests and status shared by the server and the collector (data/control/)
app/sessions.py         US trading days and holidays
app/saved.py            saved chart views, layouts, watchlists and option structures (data/user/)
app/watchlist.py        symbols from pasted text or exported watchlist files
app/dashboards.py       named dashboards and their addresses (data/user/dashboards.json)
app/security.py         home-network-only access, host-name and cross-site checks
app/envcheck.py         the startup environment check (Dashboards page)
app/static/dashboards.html  the dashboards page (/dashboards)
app/static/dash.js      the dashboard drop-down on every page
app/templates.py        built-in starting layouts for dashboards (Market internals)
app/earnings.py         earnings view: reports, reaction days, the % windows (no network)
app/static/earnings.html    the earnings page (/earnings)
app/expected_move.py    expected-move view: expiries, straddle, 1σ/2σ, event move, diagonal legs (no network)
app/static/expected-move.html  the expected-move page (/expected-move); its scripts in js/expected-move/
app/option_chain.py     option-chain view: the cached chain, the expiry strip, legs priced from it (no network)
app/quotes.py           watch list rows: last, change, volume, high and low from cached bars (no network)
app/positions.py        the Holdings list: positions summed over accounts, value and P/L at the price on screen (no TWS)
app/list_sources.py     watch lists from outside sources (FinViz): addresses checked, fetched lists stored (no network)
app/structures.py       option structures: Black-Scholes, templates, evaluation (risk graph, grid, loss-limit prices)
app/static/options.html the option-chain page (/options); its scripts in js/options/
app/static/js/          the pages' code, as ES modules, one job each (no build step; the browser loads them directly):
  earnings/             the earnings page: chart, legend, start-up
  expected-move/        the expected-move page: table and cards, start-up and polling
  options/              the option-chain page: expiry strip and chain, legs, evaluation, chart levels, start-up
  main.js               start-up: restores the window and wires the modules together
  state.js              the window's state (charts, layout, day, cursor, preferences) and saving it
  util.js               DOM helpers, server calls, browser storage
  panel.js              one chart: settings, fetching its view, drawing it; the parts below are mixed into it
  panel-header.js       a chart's header (symbol, candle duration, range, price type, f(x), maximize)
  timeframes.js         the candle durations and ranges, as the server lists them
  study-layers.js       draws a chart's studies by running the output modules' hooks
  outputs/              one module per kind of study output (lines, levels, profile, box, event lines, ...)
  legends.js            the legend on each pane, with Settings / Hide / Remove
  drawings.js           drawings stored per symbol; runs the tool modules' hooks (place, draw, alert)
  drawtools.js          the top bar's drawing-tool buttons: arm a tool on every chart
  tools/                one module per drawing tool (alert, horizontal line, trend line)
  styles.js             line types, dash patterns, colours
  params.js             settings parameters (the shape the settings dialog takes)
  keys.js               this browser's storage keys (also used by the dashboards page)
  pricetypes.js         price types: candles, Heikin-Ashi, OHLC bars, line, area, current price line
  primitives.js         canvas drawings: volume profile, extended-hours shading, zones, trend lines
  grid.js               the grid of cells (charts and watch lists), active chart, splitters, maximize
  layout-edit.js        adding and removing cells: rows, settings and sizes in, new ones out (no page)
  layout-actions.js     the Layout section of a cell's menu, and Undo after a removal
  watchlist.js          the watch list cell: tabs, the table, the column chooser, picking a row
  watch-tab.js          one tab of a watch list: its source (own, saved, FinViz, holdings), columns and rows
  columns.js            the columns a watch list can show (one registry), and how each is written
  feed.js               a watch list's outside source (FinViz): fetched, refreshed, its status
  links.js              symbol links: colour groups of cells that show the same symbol
  layouts.js            the window layouts, as rows of charts (e.g. 2 over 4, or any top/bottom count)
  data.js               bars from TWS: the Day list, requests, waiting messages, polling
  replay.js             the toolbar: layout, day, display options, replay and Live
  saved.js              saved chart views and window layouts
  notify.js             alert messages, sound and desktop notification
  dialogs/              the Studies, settings and Load data dialogs, and opening/closing dialogs
app/static/vendor/      TradingView Lightweight Charts 5.2.1 (Apache 2.0), bundled for offline use. Its logo on the
                        charts is replaced by "RP" (to do: link it to the git repository once it exists); the library is
                        credited on the /dashboards page and in [Licence and thanks](about.md)
tools/fetch_ibkr.py     TWS collector: request queue, backfill, daily history and live streaming (read-only)
tools/run_collector_windows.bat  runs the collector on the TWS PC
tools/earnings_sources.py  where the collector gets earnings dates (SEC EDGAR); off without SEC_CONTACT
tools/positions.py      the collector's positions reader for the Holdings list (HOLDINGS=on only)
tools/list_sources.py   where the collector fetches watch lists from (FinViz Elite exports); off without FINVIZ_TOKEN
tools/option_quotes.py  option chains and snapshot quotes for the expected-move and option-chain pages
tools/recorder.py       records ADD-NYSE and VOLD-NYSE from live quotes (no history at IBKR)
tools/signals.py        buy/sell rules for the backtester only (never drawn on the charts)
tools/backtest_signals.py  VZO vs MACD (and random entries) with a fixed stop, on the cached bars
tools/market_events.py  significant QQQ moves matched to scheduled events and headlines (events.json + report)
app/data/market_calendar.json  Fed, CPI, jobs, GDP, PCE and big-holding earnings dates (Oct 2025 - Apr 2027)
tools/probe_ibkr.py     checks which data your TWS login delivers: live, delayed, history depth (QQQ, SPY, TICK/AD/TRIN), news feeds
tests/                  pytest suite: Python tests, plus browser tests in tests/ui ([Tests](#tests))
tests/synthetic.py      synthetic test bars (QQQ-DEMO, SPY-DEMO): invented prices for the tests
tests/fake_tws.py       a stand-in for TWS that invents bars, to try the page without IBKR:
                        python tests/fake_tws.py --data-dir /tmp/test-data --live
                        (with the chart server started on the same DATA_DIR; never your real data folder)
tests/ui/               browser tests (Playwright, Chromium) and the JavaScript coverage collector
tests/docker_smoke.sh   builds the image and checks the running container's protections
requirements.in/.txt    direct dependencies / every dependency pinned (Python 3.12)
requirements-dev.txt    tests, coverage, browser tests and the linter
pyproject.toml          project metadata, linter (ruff) and coverage settings
.github/workflows/ci.yml  lint and test on every push
.github/workflows/docs.yml  builds this guide on every push and publishes it from main
LICENSE, NOTICE         Apache License 2.0, and the third-party notice for Lightweight Charts
docs/                   this user guide (MkDocs; published to GitHub Pages), screenshots in docs/img/
mkdocs.yml              the user guide's site settings and page order
requirements-docs.txt   the pinned MkDocs packages that build it
```

## Tests

**Working from a git clone on Windows.** `.gitattributes` keeps Unix line endings in every checkout (only
`.bat` files get Windows ones), because the container runs these files on Linux; the image also strips any
stray Windows line endings from `start.sh` when it's built. A clone made before `.gitattributes` existed
keeps its old line endings until you refresh it once (discards uncommitted changes):
`git rm --cached -r -q . && git reset --hard`

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium     # for the browser tests
ruff check app tools tests                # lint
pytest --cov                              # every test, with Python and JavaScript coverage
pytest -m "not ui"                        # without the browser tests
pip-audit -r requirements.txt             # known vulnerabilities in the pinned dependencies
sh tests/docker_smoke.sh                  # the container's protections (needs Docker)
```

- **Python tests** (`tests/`): indicators, studies, the engine, the server API, the collector (against a
  stand-in for TWS), the market-events tool (with invented headlines), the earnings view (with hand-written
  samples in SEC EDGAR's format, so no network), option structures and the strike profile, and the
  daylight-saving changes.
- **Browser tests** (`tests/ui/`): start the real server on a temporary folder of synthetic bars and drive
  both pages in Chromium. They cover the chart, studies and their settings, replay, drawings,
  saved layouts, Load data, Live mode, price types (including the current price line), adding and removing charts,
  the watch list, the earnings, expected-move, option-chain and dashboards pages. Any JavaScript error
  fails the test. JavaScript coverage (from Chromium) is printed at the end of the run.
- **Security tests** (`tests/test_security.py`): home-network-only access, foreign host names, changes
  from other sites, the startup check, public TWS addresses, and no order calls anywhere.
- **Docker smoke test** (`sh tests/docker_smoke.sh`): builds the image and checks the running container.
  It serves pages, refuses foreign hosts and cross-site changes, runs as a normal user with no capabilities
  and read-only system files, hands old data to the app user, survives a restart, and refuses a public TWS
  address.
- **User guide** (`docs/`): `pip install -r requirements-docs.txt`, then `mkdocs serve` to preview it at
  `http://127.0.0.1:8000`, or `mkdocs build --strict` to check every link, as CI does.
- **CI** (`.github/workflows/ci.yml`) runs the linter, the dependency audit and every test on Python 3.12
  (the Docker image's version), plus the Docker smoke test.
- **Dependencies** are pinned in `requirements.txt` (generated from `requirements.in`, see its header).
- All test data is invented. Synthetic symbols end in `-DEMO`, and the browser tests' copies live only
  in a temporary folder.
