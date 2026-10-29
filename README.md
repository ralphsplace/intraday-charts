# Intraday Charts: multi-chart layouts, studies and levels

A self-hosted intraday charting dashboard for stocks and ETFs (QQQ first), modelled on thinkorswim
chart grids. It runs in Docker on your NAS and reads 1-minute bars from a local cache. The cache is
filled from Trader Workstation (TWS): type a symbol into a chart, or pick symbols and a day under
**Load data**, and the collector fetches them.

Studies are added, configured and removed the way TWS Advanced Charts does it:
- **f(x) Studies** opens the list.
- **Settings** on a study's legend entry opens its configuration.
- **Hide** and **×** hide or remove it.

Besides the standard studies (VWAP, SMA, EMA, Bollinger, RSI, MACD and more), the list includes
level studies TWS doesn't have: prior day, support/resistance, session levels, ATR levels and the volume profile.

Live data comes from Trader Workstation (TWS) running on your PC. It does **not** place orders:
the connection to TWS is opened read-only, and you can also tick TWS's own *Read-Only API* setting.

### Purpose and security model

**Purpose:** custom charting and visual presentation of trading data, from read-only sources (mainly the
IBKR API), in a secure local environment. It never trades.

**Security:** there are no logins. Instead, the dashboard can only be reached from your home network, and it
checks that it runs in a secure environment:
- **Home network only.** Every request, pages included, must come from an address in `ALLOWED_NETWORKS`.
  The default is this machine plus the private home-network ranges (10.x, 172.16-31.x, 192.168.x).
  Everything else gets "403 Forbidden".
- **No use from other websites.** A web page you visit can't use your browser to reach the dashboard:
  - The address in the browser must be an IP, a machine name (`nas`), one of Docker's names
    (`*.docker.internal`, e.g. `host.docker.internal`), a `.local`/`.lan`/`.home` name, or a name in
    `ALLOWED_HOSTS`. This blocks "DNS rebinding".
  - Changes (saving, fetching, editing dashboards) are only accepted from the dashboard's own pages.
- **Read-only trading data:**
  - Every TWS connection is opened read-only, and doesn't download the account's positions, orders or executions.
  - The code contains no order calls. A test fails if one is ever added, and the server refuses to start.
  - The tools refuse to connect to a TWS address on the internet. Accepted TWS addresses are this machine,
    Docker's `*.docker.internal` names, and home-network addresses.
- **Environment check at startup.** It covers:
  - who can connect
  - accepted addresses
  - running as a normal user
  - the data folder not writable by everyone
  - read-only trading data
  - the TWS connection
  - internet access

  A failed check stops the server; for example, `ALLOWED_NETWORKS` containing internet ranges. The results
  are on the Dashboards page, and a ⚠ link appears in every page's toolbar when one needs attention.
- **Hardened container:**
  - The server and collector run as a normal user (`APP_UID`, default 1000), with no Linux capabilities.
  - The system files are read-only and no-new-privileges is set.
  - Only the data folder and `/tmp` can be written.
  - On start, `start.sh` gives the data folder to that user, removes write access for others, then drops root.
- **Outbound connections only where you turn them on.** The dashboard itself makes no internet requests.
  Two things can go online, both reading public data only:
  - the collector, for the earnings page, looks up earnings dates on SEC EDGAR, and only when `SEC_CONTACT` is set
  - `tools/market_events.py --gdelt`, when you run it
  The environment check on the Dashboards page says which are on.
- **Supply chain.** Dependencies are pinned and checked for known vulnerabilities (`pip-audit`) on every
  push.

---

## 1. Quick start

```bash
unzip intraday-charts.zip && cd intraday-charts
cp .env.example .env                     # IB_HOST: host.docker.internal by default (see section 4)
docker compose --profile collector up -d --build
```

Set up TWS's API settings first (section 4). Then open `http://<your-nas>:8050`.

**Addresses** (more in section 2, *Dashboards*):
- `http://<your-nas>:8050/`: the default dashboard (QQQs to start with)
- `http://<your-nas>:8050/QQQs`: the chart
- `http://<your-nas>:8050/dashboards`: create, rename, duplicate, delete dashboards and pick the default

A new install starts with an **empty cache**. The first time you open the page, you get:
- **One QQQ chart:** 3-minute candles, today, with no studies. Add studies with **f(x)**, change how
  the price is drawn (the price type) beside the days menu, or add charts with **Layout**.
- **The Load data dialog.** Its date defaults to the last completed trading day. The charts on screen
  are requested straight away; add symbols there if you want more.

A chart says what it is waiting for, e.g. "number 3 of 12 in the queue". When its bars arrive, it
draws them by itself. If the collector isn't running yet, requests are kept and run when it starts.

**Upgrading from `intraday-chart`** (the project's earlier name). Keep your `data` folder and `.env`:
1. In the old folder, stop the old containers: `docker compose --profile collector down`
2. Rename the folder from `intraday-chart` to `intraday-charts` (your data and `.env` move with it).
3. Unzip `intraday-charts.zip` into the folder above it, so it lands on the renamed folder, then
   `docker compose --profile collector up -d --build` from `intraday-charts`.

The containers are now `intraday-charts` and `intraday-charts-collector`. Each browser moves its saved
windows, drawings and earnings-page choices to the new names the first time it opens a page.

---

## 2. Charts, layouts and drawings

### Earnings view

`http://<your-nas>:8050/earnings` (also **Earnings** in the drop-down at the top left of every page). Type a
stock and press Enter: its last 6 earnings reports are drawn over each other, one coloured line each, with a legend.

- **What a line is.** The daily close from some trading days before to some after the report's **day 0**:
  10 before and 5 after unless you change **Days before / after** at the top (1 to 60 each, press Enter or
  leave the box; remembered in this browser). Two views,
  switched with **Relative %** / **Price $** at the top (remembered in this browser):
  - **Relative %** (default): % change from the close the day before day 0. Every line starts from 0% at
    day −1, so the share price at the time doesn't matter. A stock that has tripled, re-rated or split still
    gives comparable lines.
  - **Price $**: the close itself, adjusted for stock splits, so each quarter sits at its real price level.
    Hovering shows the price and the % change beside it.
- **Day 0** is the first session that trades on the report:
  - the report day itself, when the report came before the open or during the session
  - the next session, when it came after the close
  The legend shows which, with each quarter's day-0 move and its move by the last day shown (e.g. +5).
- **Reading it.**
  - Hover the chart to see every quarter's value at that day.
  - Hover a legend row to pick out its line.
  - Each line is labelled at its end (e.g. `Jul '26`), so you don't have to tell six colours apart.
- **Splits, in both views.** IBKR's daily prices are already adjusted for splits (checked against NVIDIA's 10:1
  split of June 2024). If a window still shows a jump the exact size of a split, the earlier closes are adjusted
  and the legend says so.
- **Where the data comes from.**
  - Daily prices come from TWS, through the collector. The page asks for them, and shows progress while it waits.
  - Earnings dates come from **SEC EDGAR**. US companies publish quarterly results with a form 8-K,
    Item 2.02, filed when the press release goes out. EDGAR keeps the time of each filing, which says
    whether the report came before the open or after the close.
  - The collector looks the dates up when you open a stock, and again after 3 days. It caches them in
    `data/earnings/<SYMBOL>.json`.
- **Turning it on.** Set `SEC_CONTACT` in `.env` to your name and email, then restart:
  `docker compose --profile collector up -d`. The SEC asks every program to name a contact; it's sent
  only to sec.gov. Without it, the page says lookups are off.
- **Not covered.**
  - Funds and ETFs (they don't report earnings).
  - Foreign companies that report with form 6-K instead of 8-K (e.g. ASML).
  - For those, write `data/earnings/<SYMBOL>.json` by hand. A file without `"fetched"` is never replaced:
    ```json
    {"symbol": "ASML", "source": "by hand", "status": "ok",
     "earnings": [{"date": "2026-07-15", "time": "07:00"}, {"date": "2026-04-15", "time": "07:00"}]}
    ```
- **Check it once.** The collector's log lists the dates and times it found, e.g.
  `NVDA: 8 earnings reports found ... 2026-08-26 16:20`. EDGAR's times are read as US/Eastern. If a known
  after-close report shows an evening time around 20:00 instead of around 16:20, EDGAR's times are UTC
  after all. Day 0 would then be off for late-evening filings, and `tools/earnings_sources.py` needs to convert them.

### Expected move view

`http://<your-nas>:8050/expected-move` (also **Expected move** in the drop-down at the top left of every page). Type
one or more stocks (e.g. `AMZN LLY MA INTC MRK CAT`, up to 20) and a date, then press **Show**. The first option
expiry on or after that date is used: for a report on Thursday the 29th, pick the 29th or 30th to get Friday's expiry.
The page asks the collector for option quotes and fills in as they arrive (a few seconds per stock).

- **The comparison table** has one row per stock: price, expiry, the expected move in $ and %, the range it gives,
  the event priced in, and the at-the-money implied volatility. Hover ⚠ for warnings.
- **One card per stock** shows how the numbers were found:
  - **Straddle (expected move)**: the at-the-money call plus put (mid prices), interpolated between the strikes
    either side of the stock's price. This is the market's average expected move by the expiry's 16:00 close.
  - **0.85 × straddle**: a common rule of thumb for a closer estimate of the typical move.
  - **1σ and 2σ**: price × implied volatility × √(calendar time left, in years). About a two-in-three and a
    19-in-20 chance of closing inside, if moves were normally distributed.
  - **Event before this expiry**: when implied volatility jumps (by 15% or more) from the previous expiry to this
    one, the options price an event between them, usually earnings. Its own move is
    price × √((IV² this expiry − IV² previous) × time left).
- **Diagonal legs.** Short call and put at the listed strikes nearest the expected move in this expiry; long call
  and put one strike closer to the money in the next weekly (the first expiry at least 7 days later). Each leg's
  mid price and the net per side (long − short). Prices only: no signal or advice, and the app never places orders.
- **Fresh quotes.** Quotes older than 15 minutes are asked for again when you open the page; **Refresh quotes**
  asks right away. They're cached in `data/options/<SYMBOL>.json`.
- **Check the warnings.** The page says when quotes were taken outside regular hours, when a bid/ask spread is
  over 25% of the mid, or when the options imply a stock price more than 0.4% away from the stock's own (stale
  quotes somewhere). Before 09:30 ET, IBKR's option quotes are often too wide to use.
- **Needs** a US options market-data subscription in IBKR (OPRA). Without it, the page says no quotes came back.

### Dashboards

Each dashboard has its own address: `http://<your-nas>:8050/<name>` (any letter case). The drop-down at
the top left of every page switches between them, and its last entry, **Manage dashboards…**, opens
`/dashboards`. There you can:
- **Create** a dashboard: give it a name (it becomes the address). It starts as one QQQ chart with no
  studies, or from one of your saved window layouts.
- **Rename** a dashboard, **duplicate** it, or **delete** it (you're asked to confirm).
- **Make default:** choose which dashboard opens at the plain address `/`.

The list is kept on the NAS (`data/user/dashboards.json`), so every browser sees the same dashboards.
A dashboard keeps its window (charts, studies, price types, sizes) in each browser. Duplicate copies a
dashboard's window in the browser you duplicate it from.
Saved views, saved layouts, watchlists and drawings are shared by all dashboards.

### Layouts

**Layout** in the toolbar switches between 1 chart (the default), 2 or 3 side by side, 2×2, 3×2, 3×3,
4×3, and **2 over 4** (two wide charts above four). Layouts with the same number of charts in every row have
column and row splitters, each column splitter running top to bottom. In the others (e.g. 2 over 4) each row
has its own column splitters, so the top and bottom rows are sized separately. Double-click a splitter to make
its row's charts (or all rows) equal again.

**Any number of top and bottom charts:** on the Dashboards page, create a dashboard with "Start from: Top and
bottom rows of charts…" and pick how many charts go on top and how many below (1 to 6 each), e.g. 3 over 5.
The Layout menu shows that dashboard's own layout alongside the named ones.

Pages ask for their scripts at an address that changes with every update, so no browser (Chrome, Firefox or
any other) can run an old copy with a new page. A browser that opened a dashboard while it still had old
scripts may have saved that dashboard as one chart; clearing the site's data in that browser (Firefox: the
padlock in the address bar, "Clear cookies and site data") brings every dashboard back to how it starts.

### Internals dashboard

`http://<your-nas>:8050/Internals` (also in the drop-down), built in like thinkorswim's internals grid:
QQQ and SPY (3-minute, 2 days) over four market internals.

| Chart | What it is | Drawn as |
|---|---|---|
| `VOLD-NYSE` | NYSE up volume − down volume ($VOLD), in shares; shown as e.g. `25.04M` | line, EMA 8 |
| `-VIX` | the VIX upside down, as thinkorswim's −VIX (rising = volatility falling) | candles, EMA 9/21 cloud, Bollinger (20, 2) |
| `TICK-NYSE` | NYSE TICK ($TICK) | line, regular-hours high and low |
| `ADD-NYSE` | NYSE advancing − declining issues ($ADD) | candles, EMA 9/21 cloud, Bollinger (20, 2) |

- **History.** VIX and TICK come with history from TWS.
  - IBKR sends the NYSE advance–decline and up/down volume only as live quotes, with no history. So the
    collector records them in Live mode, 09:30–16:00, building 1-minute bars as `ADD-NYSE` and `VOLD-NYSE`.
  - Their history starts the day you start recording, so the 2-day view fills in over two sessions.
  - `RECORD` in `.env` turns recording off.
  - If IBKR won't give the collector one of them (for example, no market data for it), the collector logs
    "Not recording …" with the reason, keeps running, and the chart shows the reason too.
- **Market data.** VIX needs CBOE index data on your IBKR account; `tools/probe_ibkr.py` shows what your
  account delivers for each of these.
- **Timeframes.** Minute candles are 1, 3, 5 or 15 minutes, so −VIX is 3-minute here (thinkorswim's is 2).
- **Not included.** The thinkorswim panels' arrows and BUY/SHORT-style labels are signals, and the dashboard
  draws none. The charts and their studies are ordinary charts: change them like any other.
- **More like it.** "Start from: Market internals" on the Dashboards page makes another copy. Deleting
  Internals is permanent; it isn't added back.
- **These symbols in any chart:** `-VIX`, `VIX`, `ADD-NYSE`, `VOLD-NYSE`, `TICK-NYSE`.

Each chart has its own:
- symbol: type any stock or ETF symbol in the box at the top left and press Enter (Esc undoes).
  The list under it suggests cached symbols and your watchlists. If bars for that symbol and day
  aren't cached, they are fetched from TWS (section 4) and the chart fills in when they arrive.
- **candle duration**, in the menu after the symbol: 1, 3, 5 or 15 minutes, or **1d**, **1w** and **1M**
  (daily, weekly and monthly candles)
- **range shown**, in the menu after it:
  - minutes: Today, 2, 3 or 5 days, with dotted day separators
  - 1d / 1w / 1M: 3 or 6 months, 1, 2, 5 or 10 years. They start at 6 months (1d), 2 years (1w) and
    10 years (1M), and each keeps its own choice.

  Daily, weekly and monthly candles come from the daily prices the collector keeps (10 years; section 4).
  The replay day's candle is built from its 1-minute bars up to the replay time (regular hours), so a
  replay never shows the rest of the day, and in Live it forms as the day goes on. A week starts on
  Monday and a month on the 1st, and the week or month holding the replay day is still forming. Symbols
  without daily prices from IBKR (TICK, TRIN, ADD, VOLD) show one candle per cached 1-minute day.
  Studies that need minutes (VWAP, session levels, prior day, S/R ladder, Saty ATR, events, volume
  profile, $TICK) stay on the chart but draw nothing on 1d / 1w / 1M, and their legend says
  "intraday charts only".
- **price type**, in the menu after the days, with its settings behind the gear button next to it
  (colors, fill, thickness, and settings of its own; **Defaults** in the dialog puts them back):
  - **Candles** (default). Rising and falling colors, colored by open-to-close or by the previous
    close, fill on or off for rising and for falling bodies, outlines and their thickness, body width,
    wicks on or off and their thickness, dimmed extended hours. Hollow candles are a setting here, not
    a type of their own: turn off "Fill rising bodies" (and, as on TradingView, color by the previous
    close). Charts saved with the old "Hollow" style open as Candles with those bodies unfilled.
  - **Heikin-Ashi:** candles from averaged prices, which smooth out the noise; the same settings as
    Candles. The chart's levels, studies and price label still use the real prices.
  - **OHLC bars:** colors, bar thickness, the open tick on or off, dimmed extended hours.
  - **Line:** the close; color, thickness, line type, a separate color for extended hours.
  - **Area:** the close, filled below; line color, thickness and type, fill color and opacity.
  - **Current price line:** only the latest price, as a horizontal line across the chart, green while
    the price is moving up and red while it is moving down. It leaves no history, so the levels, volume
    profile and studies are what you see (for example, a levels chart with Prior day, Session levels and
    Volume profile). Optional direction arrows sit at 1/3 and 2/3 of the way across: on top of the line
    pointing up while rising, under it pointing down while falling. They show the last move only; they
    are not buy or sell signals. Settings: both colors, thickness, line type, arrows on or off, arrow size.
  Saved chart views keep the price type and its settings.
- studies (none by default)

Click a chart to make it the active one; its border turns green, and **f(x)** studies apply to it.
Switching to a smaller layout keeps the hidden charts' setups for when you switch back.

What all charts share:
- **Day and replay.** All charts show the same day and replay together. A step moves by the
  shortest minute candles on screen (5 minutes when every chart shows 1d, 1w or 1M).
- **Linked crosshairs** (on by default). Moving over one chart shows the same time on the others.
- **Shade extended hours.** Premarket and after-hours bars get a grey background.
- **Fit levels.** Stretches each price scale so every level line is on screen.

**Resizing**
- Drag the thin bar between two charts to make a column wider or a row taller. Double-click it to
  make them equal again. Sizes are remembered for each layout.
- **⤢** in a chart's header (or double-clicking an empty part of the header) maximizes that chart.
  **⤡** or Esc brings the grid back.
- Each chart keeps the same stretch of time on screen when it is resized.

In small charts (as in 3×3), the study list folds behind a **Studies (n)** button, and level lines
keep their price-axis labels but drop their names.

### Saved chart views and layouts

- **≡** next to a chart's symbol saves that chart's view under a name: symbol, timeframe, days shown
  and studies with all their settings. The same menu lists saved views. Click one to load it into
  that chart, or × to delete it. Tick **Keep this chart's symbol when loading** to apply a view's
  studies and timeframe to a different symbol.
- **Layouts ▾** in the toolbar does the same for the whole window: the grid, every chart's view,
  the column and row sizes, and the Fit levels, Shade extended hours and Link crosshairs settings.
- Saving under an existing name replaces it (the button says **Replace**).
- Saved views, layouts and watchlists are kept on the NAS (`data/user/`), so every browser and
  device sees the same lists. The window you're working in is also remembered by each browser
  between visits.

### Drawings

Each chart header has **Alert**, **Line**, **Trend** and **VWAP** tools. Drawings belong to the symbol, so
they appear on every chart of that symbol, on any timeframe.

| Tool | How | Notes |
|---|---|---|
| Alert | Click a price on the chart | Draws `MARK >= price` above the current price, or `MARK <= price` below it. When price gets there, you get a sound, an on-screen message and, if you allowed it, a desktop notification. This happens in Live mode, or while replaying forward. A triggered alert turns grey and shows the time; **Re-arm** resets it. |
| Line | Click a price | A plain horizontal line, with an optional label. |
| Trend | Click two points | Optional **Extend to the right**. |
| VWAP | Click a bar | Adds an **Anchored VWAP** study to that chart, starting at the bar you clicked. Not a drawing: change or remove it like any study (its settings hold the anchor time). |

Esc cancels a tool. Every drawing is listed in the chart's legend, with **Settings** (price,
color, line type, thickness) and **×** to delete it. Drawings are stored in this browser.

---

## 3. Studies

### Adding, configuring, removing

| Action | How |
|---|---|
| Add | **f(x) Studies** → search or browse by category → **Add**. The same study can be added more than once (e.g. EMA 9 and EMA 21). |
| Configure | Hover the study's name at the top-left of its pane → **Settings**, or use **Settings** in the Studies dialog. Inputs are on top; under **Style**, every line the study draws has its own **color, line type, thickness and transparency** (0% = solid): indicator lines and bands, oscillator reference lines (e.g. RSI 70 / 50 / 30 each separately), level lines, event lines and the opening-range box. Parabolic SAR can be drawn as dots or as a line. **Defaults** restores factory settings. |
| Hide / show | **Hide** keeps the study and its settings but stops drawing it. |
| Remove | **×** on the legend entry, or **Remove** in the Studies dialog. |
| Copy | **Copy to all charts** gives every chart in the layout the active chart's studies. |
| Start over | **Reset to defaults** in the Studies dialog. |

The layout, each chart's studies and the drawings are remembered in this browser. Oscillators get their own pane below the price
chart; drag the pane separators to resize.

### Available studies

**Overlays** (drawn on price)
- SMA, EMA and WMA (length, source, color)
- VWAP (regular or extended session, two standard-deviation bands)
- **Anchored VWAP.** A VWAP that starts at a bar you choose instead of the open, with its own σ bands
  measured from the anchor (so they start at zero width and widen):
  - **Chosen time** (`YYYY-MM-DD HH:MM`, ET): set by clicking a bar with the **VWAP** header button,
    or typed in the settings; blank means 09:30 today
  - **High of day** / **Low of day**, **Prior day high** / **Prior day low**: anchored at the minute
    that high or low printed
  - **Latest event today**: from `data/events.json` (e.g. the 08:30 CPI print)

  Regular hours only unless **Include extended hours** is on. It carries on across days (up to 15 days
  back) and draws a dotted line at the anchor.
- Bollinger Bands
- Keltner Channels
- Donchian Channels
- Parabolic SAR

- **Moving average cloud.** Two moving averages, each SMA or EMA with its own length, with the space
  between them filled.
  - One cloud colour while MA 1 is above MA 2, another while MA 2 is above MA 1, each with its own
    transparency. Where the lines cross, the fill switches colour exactly at the crossing.
  - Each line has its own colour, line type, thickness and transparency.
  - **Timeframe: Chart timeframe** (default) calculates on the chart's bars.
  - **Timeframe: Daily** calculates from daily closes (e.g. 50- and 200-day) and draws them as
    today's levels. This replaces the old "Daily moving averages" study; saved charts that used it
    switch over automatically. Long daily lengths need daily history (see `--daily-years` below).
**Volume**
- Volume, with an optional moving average; bars outside regular hours are dimmed
- **Relative volume (time of day).** Each bar's volume divided by the average volume of the same time
  slot over the last N sessions (10 by default), in its own pane, with a line at 1.0. The busy open
  and the quiet lunch are each compared with their own normal. Bars at or above 2× are highlighted
  and those under 0.5× dimmed (both adjustable). The bar still forming reads low until it ends.

- **Cumulative volume delta (estimate).** A running total of volume signed by where each 1-minute bar
  closed, reset each day at 09:30 (or 04:00), in its own pane. **It is an estimate, and labelled so:** true
  delta needs every trade matched against the bid and ask, which this app doesn't record. It is rebuilt
  from bars:
  - *Close location* (default): volume × ((close − low) − (high − close)) / (high − low), from −volume
    when a bar closed on its low to +volume when it closed on its high
  - *Close vs open*: + the volume on an up bar, − on a down bar

  On QQQ it tends to track OBV and VZO, so read it as one more view of the same pressure.

**Profiles** (horizontal histograms on the price; both share the row settings below)
- **Volume profile.** A horizontal histogram along the left (or right) edge, like thinkorswim's.
  - Range: today all sessions, today regular hours, or all shown days.
  - **Row height**, like thinkorswim's row-height modes:
    - *Number of rows* (default 60) across the range
    - *Tick size*: one row per price tick (QQQ: $0.01), or N ticks per row; POC, VAH and VAL then
      sit on exact tick prices
    - *Custom price per row*, e.g. $0.25
    Very fine rows on a wide range are widened automatically to stay under 1,500 rows (the legend
    says so).
  - Value-area %, side and width are configurable, plus colors and opacity.
  - Optional POC and VAH/VAL lines.
- **TPO / Market Profile.** Time at price: how many periods (30 minutes by default; 5, 15 or 60) price
  spent at each price, rather than how much traded there. Drawn on the right by default, so it sits
  beside the volume profile.
  - Its own POC, VAH and VAL (labelled TPO POC etc.), regular hours by default.
  - The prior day's regular-hours POC, VAH and VAL carried forward (pPOC, pVAH, pVAL).
  - **Naked POCs** (nPOC with the date) from the last N days (5 by default): earlier days' POCs that
    price hasn't traded through since.

**Oscillators** (own pane)
- RSI
- MACD
- Stochastic
- ATR
- ADX / DMI
- CCI
- Williams %R
- OBV
- **Volume Zone Oscillator (VZO).** Direction-signed volume as a % of total volume, as dots (default) or
  a line, colored like thinkorswim's STO_VZO_Lower (green above +15, yellow, red below −5), by zone
  (±40) or by slope. Lines at ±60, ±40 and 0, shaded zones from ±40 to ±60, and an optional signal
  line. It is an indicator only: it draws nothing on the price chart.
- **Polarized Fractal Efficiency (PFE).** How efficiently price moved over the last N bars (Hans Hannula,
  1994): the straight-line distance between the close N bars ago and now, as a % of the bar-by-bar path,
  each bar one unit wide. +100 is a straight rise, −100 a straight fall, near 0 a choppy path. EMA-smoothed
  (length 10, smoothing 5 by default), with dashed lines at ±50 (the trend level, adjustable) and 0.
  - Price is in its own units against a one-bar step, as in thinkorswim and TradingView, so readings depend
    on the stock's price and the bar size. On QQQ's 1-minute bars (Oct 28) it spent about 70% of the day
    beyond ±50; on 5-minute bars about 55%.

**Market internals** (NYSE TICK; the collector fetches it with every stock request, see section 4)
- **NYSE TICK (with extreme counter).** Each bar's TICK high (up bars) and low (down bars), with lines at
  ±1000 and ±600.
  - Bars beyond ±1000 are highlighted.
  - The legend counts today's extreme 1-minute readings, in total and over the last 120 minutes.
  - tosindicators suggests 3+ extremes in one direction within 2 hours means strong sentiment, and
    5+ can mean exhaustion. That's their guidance, not a tested rule.
- **Cumulative TICK.** Running total of TICK's (high + low + close) / 3 for every minute from 09:30,
  reset each day: cyan while rising, grey while falling. Summed per minute, so it reads the same on
  every timeframe.
- Each study can use the Nasdaq-100 TICK (`TICK-NDX`) or Nasdaq TICK (`TICK-NASD`) instead, if your
  account has real-time Nasdaq index data and you add them to `COMPANIONS`.
- You can also type `TICK-NYSE` or `TRIN-NYSE` into a chart's symbol box to chart the index itself.
- **Relative strength (vs SPY).** How much better or worse the chart's symbol has done than another
  symbol (SPY by default; any symbol in the settings) since today's open, or since the first bar shown,
  in %. Its own pane, with a zero line; above zero is stronger. The legend shows the current reading,
  e.g. "QQQ vs SPY: +0.42% since 09:30".
- **Heavyweights (QQQ top holdings).** A strip of boxes in the chart's legend: each of the fund's
  largest holdings (10 by default) with its move and its contribution to the fund (move × weight, in
  percentage points), green when adding and red when taking away. The first box adds them up next to the
  fund's own move, e.g. "Top 10: +0.62 of QQQ +0.80%". Moves are from the prior close (or today's open).
  - Weights are a dated snapshot, because the app makes no internet requests:
    `app/heavyweights.json` ships QQQ's top 10 (Zacks Investment Research, holdings as of 2026-10-02).
    To use your own, or other funds, put a file of the same shape at `data/heavyweights.json`; a fund
    listed there replaces the shipped one and survives updates. The legend shows the weights' date.

**Symbols a study reads.** Relative strength and Heavyweights need bars for symbols that aren't on any
chart (SPY, NVDA, AAPL, ...). The chart asks the collector for them automatically, like a typed symbol:
in Replay it fetches that day (plus the usual 5 days before it and the daily history), and in Live it
streams them. The first time, ten holdings with 10 years of daily history make a long queue (IBKR allows
about 50 history requests per 10 minutes); boxes show "…" until a holding's bars arrive.

**Levels**
- **Prior day levels (PH, PL, PC, PO).** Prior-day high, low, close and open, each switchable, with
  optional prior-week high/low and prior-day Fibonacci.
- **Support / resistance (Pivot, R1-R2, S1-S2).** The ordered ladder described below.
- **Session levels.** Levels built during today's session:
  - premarket high/low
  - the opening range (5/15/30 minutes) and its box
  - high and low of day
  - volume profile (POC, VAH, VAL; off by default)
  - day Fibonacci (off by default)
  - the remaining expected range from ATR

  Every line in these three studies has its own color, line type and thickness. Each study also has a
  "near price only" filter and a flip setting. A level's label gains "(flipped)" once price has closed
  beyond it on that many completed 5-minute bars, against the side it opened on.
- **Initial Balance.** The high and low of the first hour of regular trading (09:30-10:30; 30 or 90
  minutes also possible), its midpoint, and range extensions at multiples of the IB range (1× and 2×
  by default) above the high and below the low, with the IB period shaded. Until 10:30 the levels say
  "(building)". The legend describes the day so far: inside the IB, extended up or down by how many IB
  ranges, or traded out both sides. Holding inside the IB is typical of a rotational day; leaving it
  early, of a directional one. That's the usual reading, not a signal.
- **Daily range meter.** Today's regular-hours range (high − low so far) as a percentage of the average
  daily range of the last 14 days, as a label at the top of the chart, e.g. "Day range 3.46 = 76% of
  the 14-day average (4.57)". Its colour is teal under 50%, amber from 50 to 100%, and red past 100%
  (the day has already moved more than an average day). A gauge, not a signal. It optionally marks
  where an average-sized day would put the high (LOD + average) and the low (HOD − average).
- **ATR levels (Saty-style).** Levels at fractions of the daily ATR (Wilder, 14 days) above and below
  the prior close:
  - the 23.6% call/put triggers
  - 38.2, 50, 61.8 and 78.6%
  - ±1 ATR
  - optional extensions to 2 ATR

  It also shows thinkorswim-style labels:
  - "Day Range ($x) is n% of ATR ($y)"
  - "Calls > trigger | +1 ATR"
  - "Puts < trigger | −1 ATR"

  The level math is tested against the levels on your Oct 19 thinkorswim screenshot (prior close
  709.80, ATR 10.55).
- **Events.** Vertical lines from `data/events.json`, drawn into the future so you see them coming.
  Three kinds, each switchable with its own colour: scheduled events (dashed), headlines (dotted) and
  significant moves (solid orange, labelled with the move and its likely cause). A label at the top
  counts down to the next scheduled event of the day, e.g. "Next: FOMC 14:00, in 1h 25m". The scheduled events
  and moves come from `tools/market_events.py` (section 4, *Market events*).

**Calculation notes**
- Moving averages and oscillators are calculated on the chart's timeframe. They use earlier cached
  days to warm up, so they are defined from the first bar of the day.
- RSI, ATR and ADX use Wilder's smoothing, the convention most platforms use. Values can still
  differ slightly from TWS, depending on how much history each platform loads.

### The support / resistance ladder

Classic floor-pivot formulas don't keep the ladder in order: R1 often sits *below* the prior-day high,
and S1 *above* the prior-day low. So the ladder offers three methods:

| Method | R1 / R2 | S1 / S2 | Order guaranteed |
|---|---|---|---|
| Fibonacci extension (default) | PH + 0.272 × range / PH + 0.618 × range | PL − 0.272 × range / PL − 0.618 × range | R2 > R1 > PH, S2 < S1 < PL |
| ATR extension | PH + 0.5 ATR / PH + 1 ATR | PL − 0.5 ATR / PL − 1 ATR | R2 > R1 > PH, S2 < S1 < PL |
| Classic pivots | 2P − PL / P + range | 2P − PH / P − range | No |

Here range = PH − PL and Pivot P = (PH + PL + PC) / 3.

**Dynamic** (on by default, extension methods only): once price trades above PH, R1 and R2 are measured
from today's high instead, so they stay above price. Likewise S1 and S2 move below a new low. Levels
that have moved are labelled "(moving)".

Tick **Fit levels** in the toolbar to stretch the price scale so every drawn level is on screen.

### Replay and Live

- **Replay** steps through any cached day without looking ahead. Every study only sees bars that
  had started before the cursor time. Use ◀ ▶ to step one bar, or Play.
  - **Day** lists the days cached for the symbols on screen.
  - To replay another day, open **Load data…**, pick the symbols and the day on the calendar,
    and click **Fetch from TWS**. The charts switch to that day and fill in as the bars arrive.
- **Live** shows today and refreshes every 5 seconds. The replay controls at the bottom are removed while in Live, and the charts use the room.
  - Switching to Live asks the collector to stream every symbol on screen. Typing a new symbol into
    a chart while in Live adds it to the stream.
  - Streamed symbols stay streamed, also after a restart. **Load data…** lists them under
    *Live symbols*; × stops one.
  - On weekends and holidays Live shows the last trading day. Live moves to the new day by itself
    in the morning.
  - **Live stays on** when you switch dashboards or go to another page and back, until you press
    **Replay**. A new browser tab (or a restarted browser) starts in Replay.
  - **If TWS can't be reached**, Live switches back to Replay and says why: the collector reports TWS
    disconnected, or the collector stops, for two checks in a row (about 10 seconds). Press **Live**
    again once it's fixed.

---

## 4. Connecting to TWS (real and live data)

The collector (`tools/fetch_ibkr.py`) connects to Trader Workstation running on your PC. It:
- downloads **1-minute bars**, including pre- and post-market, one trading day at a time, into
  `data/bars/<SYMBOL>/1min/<date>.parquet`
- downloads **daily bars** (10 years by default, `DAILY_YEARS` in `.env`) into
  `data/bars/<SYMBOL>/1day.parquet`, for stocks, ETFs and VIX. The full history is fetched once (and again
  only if you raise `DAILY_YEARS`); after that, only the last month is fetched to bring it up to date.
- in **live mode**, streams today's bars from TWS and writes them every 5 seconds from 04:00 to
  20:00 ET. The chart's **Live** mode then shows them.
- **takes requests from the chart page.** Typing a symbol into a chart, **Load data…** and switching
  to Live all leave a request in `data/control/`. The collector picks it up within a few seconds.
  - For each symbol it fetches the requested day first, then the 5 trading days before it, then the
    daily history.
  - Its progress is shown on the waiting charts and in **Load data…** under *Collector*: connected
    or not, the queue, recent fetches, unknown symbols, and TWS's own error messages.

Days already cached are skipped, so restarting only fetches what's missing. Weekends and US market
holidays (listed through 2027) are never requested. In live mode the collector reconnects by itself,
checking every 30 seconds, if TWS is closed, restarts overnight or the PC sleeps.

### Set up TWS (once)

In TWS: *File → Global Configuration → API → Settings*.
1. Tick **Enable ActiveX and Socket Clients**.
2. Tick **Read-Only API**.
3. Check that **Socket port** is **7496** (live). Paper trading uses 7497.
4. If the collector runs on another machine (e.g. the NAS):
   - untick **Allow connections from localhost only**
   - add that machine's IP address under **Trusted IPs**, so TWS doesn't ask every time
5. Let **Windows Firewall** allow TWS on private networks when it asks. If it didn't ask, allow
   inbound TCP 7496 for TWS yourself.
6. Optional: under *Lock and Exit*, choose **Auto restart** rather than auto log-off, so TWS comes
   back by itself after its nightly restart.

Some things to know:
- **Market data.** Historical and live bars need the same market-data subscriptions as quotes in TWS.
  The expected-move page also needs US options quotes (OPRA).
- **One login at a time.** IBKR allows one session per username. Logging in to IB Gateway (or the
  mobile or web app as the same user) logs TWS out, which may be what broke the Gateway setup.
- **Pacing.** IBKR limits historical requests to roughly 60 per 10 minutes.
  - The collector leaves 2 seconds between requests and sends at most 50 in any 10 minutes.
  - Loading one day for 5 new symbols (6 days each, plus daily history) takes about a minute.
  - A first backfill of 30 days for 2 symbols takes about 12 minutes.
  - Requests from the page jump ahead of a running backfill. Streaming is not affected.

### Market internals (NYSE TICK and TRIN)

Every stock request (from the page, `SYMBOLS`, or Live) also fetches the indexes listed in
`COMPANIONS` for the same days. The default is `TICK-NYSE TRIN-NYSE`.
- **Checked on your account (October 2026):**
  - NYSE TICK and TRIN: real-time, with 1-minute history at least 3 months back.
  - NYSE advance/decline (`AD-NYSE`): real-time, but IBKR returns no intraday history. The same goes for NYSE
    up/down volume (`VOL-NYSE`). The collector records both from live quotes (see "Internals dashboard").
  - Nasdaq TICKs (`TICK-NDX`, `TICK-NASD`): delayed only, so they need a Nasdaq index data
    subscription.
- **`tools/probe_ibkr.py`** re-checks all of this against your TWS.
- **To backfill TICK for days already cached**, run the collector with the same `--days`, e.g.
  `docker compose run --rm collector python tools/fetch_ibkr.py --symbols QQQ --days 250 --client-id 18`.
  Cached QQQ days are skipped and only the missing TICK and TRIN days are fetched.

### Run the collector: pick one

Leave it running: in live mode it also serves the page's requests. The symbols in `SYMBOLS` /
`--symbols` are backfilled for `BACKFILL_DAYS` days and streamed from the start. Anything else can
be added from the page.

**Where TWS is: `IB_HOST`.** It defaults to `host.docker.internal`, Docker's name for the machine running
Docker. That suits Docker running on the same PC as TWS:
- On Docker Desktop (Windows, Mac) the name is built in.
- On Linux, `docker-compose.yml` adds it (`extra_hosts: host.docker.internal:host-gateway`).

Every service gets it, so tools run with `docker compose run --rm chart python tools/...` reach TWS too.
When Docker runs on a different machine from TWS (e.g. the NAS), set `IB_HOST` to the TWS PC's LAN
address in `.env`.

**A. On the NAS in Docker, next to the chart.** Recommended if the NAS is always on.
```bash
cp .env.example .env        # set IB_HOST to your PC's IP address, e.g. 192.168.1.50; adjust SYMBOLS
docker compose --profile collector up -d --build
docker compose logs -f collector     # watch it connect, backfill, then stream
```

**B. On the Windows PC that runs TWS.** Nothing to open on the network.
1. Install Python 3.11+ from python.org, ticking "Add python.exe to PATH".
2. Edit `tools\run_collector_windows.bat`: set `DATA_DIR` to the chart's `data` folder on the NAS
   share, and `SYMBOLS`.
3. Double-click the file and leave its window open.

**C. By hand, anywhere.**
```bash
pip install -r requirements.txt
python tools/fetch_ibkr.py --symbols QQQ SPY --days 30 --live --host 192.168.1.50 --port 7496 \
    --data-dir /path/to/intraday-charts/data
#   leave out --live to backfill once and stop; --port 7497 for paper
#   --date 2026-10-16 fetches that day and the 5 before it instead of --days
```

### Watchlists, and thinkorswim share links

In **Load data…**:
- **Save as watchlist** keeps the symbols in the box under a name. The **Watchlists…** list loads
  them back. Watchlist symbols are also suggested in every chart's symbol box.
- **Import file…** reads an exported watchlist and keeps the stock and ETF symbols. It accepts:
  - thinkorswim or broker CSVs with a *Symbol* column
  - FinViz exports (*Ticker* column)
  - TWS exports (`DES,AAPL,STK,...` lines)
  - any text list
  Futures (`/ES`), indexes (`$SPX`) and options are skipped and listed.

thinkorswim share links (`tos.mx/!…`) can't be read. The page behind the link shows only the item's
name ("Zone", a watchlist) and a button that opens thinkorswim. The symbols are delivered only inside
thinkorswim, in a private format. To use a shared watchlist here, ask the person who shared it for
the symbols as text, or for the CSV that thinkorswim exports. Then paste or import it.

**If it doesn't connect**, the log line says why:
- *Connection refused*: TWS isn't running, or the API setting or port is wrong.
- *Timed out*: a firewall is in the way, or IB_HOST is wrong.
- TWS asks you to accept the connection: add the collector's IP under Trusted IPs.

### Testing a signal: VZO vs MACD with a fixed stop

`tools/backtest_signals.py` replays the cached bars and trades three signal sets with the same stop.
It compares them with each other and with random entries. These signals exist only here: no study draws
them on the charts.
- **Strategies:**
  - `vzo_rules`: Khalil & Steckler's rules, with the ADX(14) > 18 and EMA(60) trend filter
  - `vzo_tos`: thinkorswim's STO_VZO_Lower arrows: VZO crossing up through +5 (long) or down
    through −5 (short)
  - `vzo_tos_x`: the same arrows plus the VZO exit signal (previous VZO above +40, current lower,
    MACD not above its signal line) closing longs
  - `whale`: the Trading BUY/SELL Signal arrows with the script's default 30-minute filter;
    `whale_raw` without the filter. The script's own ATR(200) target and stop are not used, so every
    strategy is judged with the same stop.
  - `sde`: Supply Demand Edge arrows (long on a TICK-confirmed new low failure, short on a new high);
    `tick_fade` / `tick_follow`: trade against / with a TICK extreme (±1000). They need TICK-NYSE in
    the cache; days without it have no TICK trades.
  - `vzo_zero`: VZO crossing 0
  - `macd`: MACD(12,26,9) crossing its signal line
  - `vzo_conf_macd`, `vzo_conf_trail`, `vzo_conf_both`: a VZO trigger confirmed by MACD and ADX.
    - Trigger: VZO crosses up through +5 (long) or down through −5 (short), as on thinkorswim.
      `--vzo-trigger zones` uses the original −40 / +40 levels instead.
    - Within 3 bars, MACD must be converging: its histogram rose (long) or fell (short) two bars
      running.
    - ADX(14) must be at least 20, with the +DI − −DI spread moving toward the trade.
    - Exits: the MACD line crossing back over its signal line (plus the fixed stop), a trailing stop
      of the same distance, or whichever comes first.
- **Fills:** entry at the next bar's open after a signal. Exit on the stop, the exit or opposite
  signal, or at the last bar before 16:00.
- **Output:** trades, win rate, average and total P&L per share after costs, profit factor, maximum
  drawdown, t-stat, how many random-entry runs it beat, and the first half of the days vs the second.

```bash
# fill the cache first: e.g. 60 days of QQQ (a second client id, so it can run next to the live collector)
docker compose run --rm collector python tools/fetch_ibkr.py --symbols QQQ --days 60 --client-id 18
# then test; --tf picks the bar size (1, 2, 3, 5 or 15), --stops the stop distances on QQQ's price
docker compose run --rm chart python tools/backtest_signals.py --symbol QQQ --tf 1 --stops 0.15 0.30
docker compose run --rm chart python tools/backtest_signals.py --symbol QQQ --tf 3 --out data/reports
```

### Market events: what moved QQQ, and why

`tools/market_events.py` goes through the cached QQQ bars, finds the significant moves, and matches each
one to its likely cause. Results go on the charts (the Events study) and into a table.

**What counts as a significant move** (each threshold is a setting):
- **Gap:** the 09:30 open is at least 0.75 x ATR(14) from the prior close (`--gap-atr`).
- **Range day:** the regular-session range is at least 1.5 x ATR(14) (`--range-atr`).
- **15-minute move:** between 07:00 and 16:00, a 15-minute move at least 6 x the median 15-minute move
  of the previous 20 days (`--burst-mult`; at most 3 per day, largest first, `--max-bursts`). This
  catches the 08:30 releases before the open too.

**Likely causes:**
- **Scheduled events** from `app/data/market_calendar.json`: FOMC decisions (14:00), CPI, jobs report,
  GDP and PCE (08:30), and earnings after the close for NVDA, AAPL, MSFT, AMZN, META, GOOGL, AVGO, TSLA
  and NFLX, from October 2025 through April 2027 (dates from the Fed, BLS, BEA and the companies). Monthly
  options expiration (third Friday; quad witching in March, June, September, December) is added
  automatically. A 15-minute move matches a release if it starts from 5 minutes before to 30 minutes
  after it (60 minutes for the Fed); a gap matches last night's earnings, a release before the open,
  or yesterday's Fed decision. Moves before October 2025 have no scheduled-event dates in the file;
  add rows to it in the same format to extend it.
- **IBKR headlines** (`--news`, needs TWS): from the news feeds your account has (Briefing and Dow Jones
  on your login), filed under QQQ, SPY, NVDA, AAPL, MSFT, AMZN, META, GOOGL, AVGO, TSLA, NFLX, COST and AMD.
  - Each symbol's headlines are read once, page by page, then matched to the moves. Expect a few
    minutes for this.
  - Windows: 15-minute move, 45 minutes before it to 15 minutes into it; gap, from the previous close
    to the open; range day, the whole session, closest to its biggest 15-minute move.
  - Best first: just before the move, filed under QQQ or SPY, not a press release. Parts of one story
    ("-2-", "-3-") count once.
  - IBKR keeps about 6 months of headlines, so older moves get none. The run prints how far back they go.
- **GDELT** (`--gdelt`, needs internet): for moves still unexplained, top news-wire headlines from the
  free GDELT news database for the hour around the move. GDELT is broad world news, so treat its
  headlines as leads rather than causes.

**Output:**
- `data/events.json`: the scheduled events (including the next 60 days, so live charts show what's
  coming) and the moves with their cause, e.g. `Move -0.84%: CPI (Sep) 08:30`. Entries you added
  yourself are kept; re-running replaces only the tool's own entries (marked `"source": "market_events"`).
- `data/reports/significant_moves.csv` and `.html`: one row per move with day, kind, start and end time,
  move in $ and %, size, Type, Notes, Source and headlines.
  - **Type** is `Scheduled` when a scheduled event may explain the move. Otherwise it is `News` when
    headlines were found (`--news`, `--gdelt`), and blank when nothing was found.
  - **Notes:**
    - Scheduled: the events, e.g. `AAPL earnings last night; AMZN earnings last night`.
    - News: the best 2 headlines with their time (ET) and the symbols they were filed under, e.g.
      `12:50 Chip export rule eased [QQQ,NVDA]`.
  - **Source** names where each item in Notes came from, in the same order:
    - Scheduled: who publishes the event: the Federal Reserve (FOMC), the Bureau of Labor Statistics
      (CPI, jobs report), the Bureau of Economic Analysis (GDP, PCE), the company for earnings, and the
      Options Clearing Corporation for options expiration. Each event's source is set in
      `app/data/market_calendar.json`.
    - News: the news feed, e.g. `Dow Jones Global Equity Trader (DJ-N)` or `GDELT (reuters.com)`.
  - **headlines** has every headline found for the move (up to 5), including for scheduled ones.

```bash
docker compose run --rm chart python tools/market_events.py                # scheduled events only
docker compose run --rm collector python tools/market_events.py --news --gdelt --client-id 20
```
Read-only: it requests headlines from TWS and places no orders.

---

## 5. Configuration

- **`data/events.json`**: scheduled events and headlines for the Events study. Edit by hand, or let
  `tools/market_events.py` fill it (it keeps your own entries). For example:
  ```json
  [{"date": "2026-10-21", "time": "10:00", "label": "Existing home sales", "kind": "scheduled"},
   {"date": "2026-10-21", "time": "14:00", "label": "Fed speaker", "kind": "scheduled"}]
  ```
  `kind` is `scheduled` or `headline`. Times are US/Eastern, 24-hour.
- **`config.json`**:
  - the default symbol
  - optionally `"default_layout"`: the studies a new chart starts with (none by default), e.g.
    `[{"type": "vwap", "params": {}}]`
- **`.env`**: the TWS address and port, symbols, backfill length, live write interval, and the web port. `WEB_WORKERS` (default 2) sets
  how many processes serve charts; raise it on a NAS with more cores if big grids replay slowly.
- **Security settings in `.env`** (see *Purpose and security model*):

  | Setting | Default | What it does |
  |---|---|---|
  | `ALLOWED_NETWORKS` | this machine + private ranges | Devices that may use the dashboard, e.g. `192.168.1.0/24`. Internet ranges stop the server. |
  | `ALLOWED_HOSTS` | none | Extra names you type to reach the NAS, beyond IPs, machine names, Docker's `*.docker.internal` names and `.local`/`.lan`/`.home` names. |
  | `CHART_BIND` | `0.0.0.0` | The NAS address the port listens on, e.g. its LAN address only. |
  | `APP_UID` / `APP_GID` | 1000 | The user the containers run as. |

  If you narrow `ALLOWED_NETWORKS`, note that pages opened on the NAS itself arrive from Docker's
  gateway (a 172.x address). Include it if you browse on the NAS.
- **Run tools in the container** with `docker compose run --rm chart python tools/...` (not `exec`). That
  way they run as the app user like the server.

---

## 6. How the code is organized, and adding your own

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

### Adding a study

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

### Adding a price type

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

### Adding a drawing tool or a kind of study output

Add a module to `app/static/js/tools/` (or `app/static/js/outputs/`) and list it in that folder's
`index.js`. The comment at the top of `index.js` describes the hooks; the existing modules are short
examples (`hline.js` for a tool, `labels.js` for an output). A tool can also act on its clicks without
storing a drawing (`place`): `avwap.js` adds a study.

---

## 7. Project layout

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
app/saved.py            saved chart views, layouts and watchlists (data/user/)
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
app/static/js/          the pages' code, as ES modules, one job each (no build step; the browser loads them directly):
  earnings/             the earnings page: chart, legend, start-up
  expected-move/        the expected-move page: table and cards, start-up and polling
  main.js               start-up: restores the window and wires the modules together
  state.js              the window's state (charts, layout, day, cursor, preferences) and saving it
  util.js               DOM helpers, server calls, browser storage
  panel.js              one chart: settings, fetching its view, drawing it; the parts below are mixed into it
  panel-header.js       a chart's header (symbol, candle duration, range, price type, f(x), tools, maximize)
  timeframes.js         the candle durations and ranges, as the server lists them
  study-layers.js       draws a chart's studies by running the output modules' hooks
  outputs/              one module per kind of study output (lines, levels, profile, box, event lines, ...)
  legends.js            the legend on each pane, with Settings / Hide / Remove
  drawings.js           drawings stored per symbol; runs the tool modules' hooks (place, draw, alert)
  tools/                one module per drawing tool (alert, horizontal line, trend line)
  styles.js             line types, dash patterns, colours
  params.js             settings parameters (the shape the settings dialog takes)
  keys.js               this browser's storage keys (also used by the dashboards page)
  pricetypes.js         price types: candles, Heikin-Ashi, OHLC bars, line, area, current price line
  primitives.js         canvas drawings: volume profile, extended-hours shading, zones, trend lines
  grid.js               the grid of charts, active chart, splitters, maximize
  layouts.js            the window layouts, as rows of charts (e.g. 2 over 4, or any top/bottom count)
  data.js               bars from TWS: the Day list, requests, waiting messages, polling
  replay.js             the toolbar: layout, day, display options, replay and Live
  saved.js              saved chart views and window layouts
  notify.js             alert messages, sound and desktop notification
  dialogs/              the Studies, settings and Load data dialogs, and opening/closing dialogs
app/static/vendor/      TradingView Lightweight Charts 5.2.1 (Apache 2.0), bundled for offline use. Its logo on the
                        charts is replaced by "RP" (to do: link it to the git repository once it exists); the library is
                        credited on the /dashboards page and in Thanks below
tools/fetch_ibkr.py     TWS collector: request queue, backfill, daily history and live streaming (read-only)
tools/run_collector_windows.bat  runs the collector on the TWS PC
tools/earnings_sources.py  where the collector gets earnings dates (SEC EDGAR); off without SEC_CONTACT
tools/option_quotes.py  option chain and snapshot quotes for the expected-move page
tools/recorder.py       records ADD-NYSE and VOLD-NYSE from live quotes (no history at IBKR)
tools/signals.py        buy/sell rules for the backtester only (never drawn on the charts)
tools/backtest_signals.py  VZO vs MACD (and random entries) with a fixed stop, on the cached bars
tools/market_events.py  significant QQQ moves matched to scheduled events and headlines (events.json + report)
app/data/market_calendar.json  Fed, CPI, jobs, GDP, PCE and big-holding earnings dates (Oct 2025 - Apr 2027)
tools/probe_ibkr.py     checks which data your TWS login delivers: live, delayed, history depth (QQQ, SPY, TICK/AD/TRIN), news feeds
tests/                  pytest suite: Python tests, plus browser tests in tests/ui (section 9)
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
LICENSE, NOTICE         Apache License 2.0, and the third-party notice for Lightweight Charts
```

---

## 8. Known limitations

- **Up to 5 days per minute chart.** Longer history is used for warm-up and daily levels, but isn't drawn;
  for longer stretches use 1d, 1w or 1M candles.
- **Early closes.** Half-day sessions (e.g. the day after US Thanksgiving) are treated as full days.
- **Volume profile.** It is approximated from 1-minute bars, with each bar's volume spread evenly
  across the bar's high-low range.
- **Drawings are per browser.** Drawings and the current window are stored in the browser. Use
  saved layouts and views (kept on the NAS) to move a setup to another device.
- **Holiday list.** US market holidays are listed through 2027. Later holidays are requested,
  come back empty, and are reported as "no bars".
- **Big grids replay more slowly.** Every chart is recalculated on the NAS at each step: about
  0.1 s per chart on a desktop CPU. A 3×3 grid therefore steps roughly once a second.
- **Earnings dates.** Only companies that file 8-K reports with the SEC; see "Earnings view". An Item 2.02
  filing within 45 days of a later one (e.g. a preliminary-results notice) counts as part of that report.
- **Expected move.** Option snapshots from a live TWS haven't been tested yet (only against the test suite's
  invented chain). Strikes are read from the SMART chain; an expiry missing a strike is skipped, not interpolated.
- **News headlines.** IBKR keeps about 6 months of headlines, and their times are read as UTC; the
  match to real headlines hasn't been checked against a live TWS yet.

---

## 9. Development and tests

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
  samples in SEC EDGAR's format, so no network), and the daylight-saving changes.
- **Browser tests** (`tests/ui/`): start the real server on a temporary folder of synthetic bars and drive
  both pages in Chromium. They cover the chart, studies and their settings, replay, drawings,
  saved layouts, Load data, Live mode, price types (including the current price line), the earnings page and the dashboards page. Any JavaScript error
  fails the test. JavaScript coverage (from Chromium) is printed at the end of the run.
- **Security tests** (`tests/test_security.py`): home-network-only access, foreign host names, changes
  from other sites, the startup check, public TWS addresses, and no order calls anywhere.
- **Docker smoke test** (`sh tests/docker_smoke.sh`): builds the image and checks the running container.
  It serves pages, refuses foreign hosts and cross-site changes, runs as a normal user with no capabilities
  and read-only system files, hands old data to the app user, survives a restart, and refuses a public TWS
  address.
- **CI** (`.github/workflows/ci.yml`) runs the linter, the dependency audit and every test on Python 3.12
  (the Docker image's version), plus the Docker smoke test.
- **Dependencies** are pinned in `requirements.txt` (generated from `requirements.in`, see its header).
- All test data is invented. Synthetic symbols end in `-DEMO`, and the browser tests' copies live only
  in a temporary folder.

---

## 10. Licence

Apache License 2.0: see `LICENSE` and `NOTICE`. The bundled TradingView Lightweight Charts library is
also Apache 2.0 (`app/static/vendor/lightweight-charts.LICENSE`).

---

## 11. Thanks

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

