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
app/server.py           web server: builds the app from app/api/, the startup check, home-network-only access
app/api/                the endpoints, one module per area of the app, each with its own APIRouter:
  common.py             shared checks of symbols, dates and expiries; the deployment config file
  charts.py             meta, fetch and live requests, collector status, study catalog, the chart view
  watch.py              watch list rows and columns, study values, Holdings, FinViz sources, named lists
  saved.py              saved views, layouts and structures
  config.py             the Config page: study defaults, each list kind's default columns
  dashboards.py         create, rename, change, delete, default dashboard
  earnings.py, expected_move.py, options.py   the earnings, expected-move and option chain pages' data
  paper.py              paper accounts, their history, and Replay practice sessions
  pages.py              the HTML pages and versioned page files; last, as it ends with /{name}
app/store.py            Parquet cache (1-minute days and daily bars); derived symbols such as -VIX
app/control.py          requests and status shared by the server and the collector (data/control/)
app/sessions.py         US trading days and holidays
app/saved.py            saved chart views, layouts and option structures (data/user/)
app/upgrade.py          at server start, once: what older versions saved, brought to today's shapes
app/paper/engine.py     paper trading's market model: orders and 1-minute bars to fills (never the broker)
app/paper/accounts.py   named paper accounts, their settings, history file, balance and resets
app/paper/practice.py   Replay practice: a session's actions replayed over the day's bars, at the cursor
app/paper/rules.py      rules as data: checked, evaluated bar by bar at the close; refuses studies that repaint
app/paper/backtest.py   a rule over many days with the paper engine; trades, stats, the random baseline
app/paper/jobs.py       backtests as background runs, followed by id (progress and results in files)
app/named.py            app-wide named things (watch lists, paper accounts): unique names, ids, rename is a move
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
app/app_config.py       the application config (data/user/config.json): sections read fresh, changed under a lock
app/watchlists.py       named watch lists, app-wide on the NAS: default names, unique names, renames keeping the id
app/watch_fields.py     the watch list's columns (one registry) and their values per symbol, only the groups asked for
app/study_values.py     a ticker's study value (a line or level at the cursor) by name, e.g. VWAP or SMA 50
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
                        (panel.js and watchlist.js are built from parts like this one with mixParts in util.js)
  paper-practice.js     Replay practice on a chart: the paper strip, the order ticket, order lines (part of Panel)
  drawings.js           drawings stored per symbol; runs the tool modules' hooks (place, draw, alert)
  drawtools.js          the top bar's drawing-tool buttons: arm a tool on every chart
  tools/                one module per drawing tool (alert, horizontal line, trend line)
  styles.js             line types, dash patterns, colours
  params.js             settings parameters (the shape the settings dialog takes)
  keys.js               this browser's storage keys (also used by the dashboards page)
  pricetypes.js         price types: candles, Heikin-Ashi, OHLC bars, line, area, current price line
  primitives.js         canvas drawings: volume profile, extended-hours shading, zones, fills between lines, trend lines
  grid.js               the grid of cells (charts and watch lists), active chart, splitters, maximize
  layout-edit.js        adding and removing cells: rows, settings and sizes in, new ones out (no page)
  layout-actions.js     the Layout section of a cell's menu, and Undo after a removal
  watchlist.js          the watch list cell: its tabs and link group, picking a row; built from the parts below
  watchlist-tabs.js     its tabs and list menu: show, add, close, rename; pick, make or delete a list
  watchlist-columns.js  its column chooser, with heat shading
  watchlist-table.js    its table and footer: rows, sorting, dragging a column, the selected row
  watchlist-editor.js   its editor: a list's symbols, or a FinViz address
  watch-tab.js          one tab of a watch list panel: the named list it shows, its columns and rows
  settings-form.js      a settings form from a parameter list (the settings dialog and the Config page)
  config/               the Config page: watch lists, watch list columns, study defaults
  lists.js              the named watch lists in the page: find (by id, then name), create, change, rename
  columns.js            how each kind of watch list column is written or drawn (the columns come from the server)
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

## Study values

`app/study_values.py` answers "where is this ticker's VWAP, 50-period SMA or +1 ATR level now?" for code
outside the charts. It runs the same study code as the charts, on the same cached bars, up to the same cursor,
so a value always matches the line on a chart with the same settings. The watch list's study columns use it, and
so can later features that need a study's price.

```python
from app import study_values
study_values.value("QQQ", "2026-10-30", {"type": "sma", "params": {"length": 50}, "output": "sma", "tf": 5})
# {"value": 691.45, "note": ""}
```

Over HTTP: `GET /api/study-value?symbol=QQQ&day=2026-10-30&type=vwap` or
`...&type=sma&params={"length":50}&tf=5&output=sma`. `output` is a line's id or a level's plot id or label
(e.g. `atr_up` for +1 ATR in `saty_atr`). Values are cached until the day's bars change.

To add a watch list column, add an entry to `COLUMNS` in `app/watch_fields.py` (and, for a new kind of value, a
group function there and a renderer in `app/static/js/columns.js`); a study column is one line in `STUDIES`.

## Working with Claude Code

`CLAUDE.md` at the repo root holds the project's commands and standing rules. `.claude/settings.json` enables
plugins from the official marketplace for this repo (code review, simplification, security review, feature
workflows, Matt Pocock's engineering skills), and `.claude/skills/` holds TradingView's Lightweight Charts skills.
`docs/agents/` tells the engineering skills where issues live (GitHub Issues), which triage labels to use and
where domain docs go; it isn't part of the published guide.

## Lightweight Charts plugins, and the agent skills

TradingView's two official agent skills for Lightweight Charts™ are in `.claude/skills/` (Apache 2.0, see
`.claude/skills/NOTICE.md`): `lightweight-charts` (the v5 API, scales, panes, markers, foot-guns) and
`lightweight-charts-plugin-authoring` (custom series, series and pane primitives, the toolkit, the official plugins).
Claude Code loads them when it works in this repository.

The app already draws several things as plugins (series primitives in `app/static/js/primitives.js`): the volume
profile, extended-hours shading, zones, trend lines, and the fill between two lines (the `cloud` output, used by the
moving average cloud and the Bollinger, Keltner and Donchian channels through `fill_between` and `channel_fill` in
`app/studies/base.py`). Lightweight Charts 5.2 is bundled as a single file with no
build step, so new plugins are written the same way: small ES modules against the bundled library, following the
skill's rules (bitmap coordinates for lines, draw the visible range only, `requestUpdate()` after changes, undo
everything in `detached()`).

