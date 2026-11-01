# Studies

Studies are added, configured and removed the way TWS Advanced Charts does it. Besides the standard
studies (VWAP, SMA, EMA, Bollinger, RSI, MACD and more), the list includes level studies TWS doesn't have:
prior day, support/resistance, session levels, ATR levels and the volume profile. None of them draws buy or
sell signals.

## Adding, configuring, removing

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

## Available studies

### Overlays

Drawn on price.

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

- **Bollinger Bands**, **Keltner Channels** and **Donchian Channels**, with the space between the upper and lower
  bands filled. The fill has its own section in the study's settings: on or off, colour and transparency (85% by
  default). To change it for every new study, use the [Config page](config.md).
- Parabolic SAR

- **Moving average cloud.** Two moving averages, each SMA or EMA with its own length, with the space
  between them filled.

  - One cloud colour while MA 1 is above MA 2, another while MA 2 is above MA 1, each with its own
    transparency. Where the lines cross, the fill switches colour exactly at the crossing.

  - Each line has its own colour, line type, thickness and transparency.
  - **Timeframe: Chart timeframe** (default) calculates on the chart's bars.
  - **Timeframe: Daily** calculates from daily closes (e.g. 50- and 200-day) and draws them as
    today's levels. This replaces the old "Daily moving averages" study; saved charts that used it
    switch over automatically. Long daily lengths need daily history (`DAILY_YEARS`, [Connecting to TWS](tws.md)).

### Volume

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

### Profiles

Horizontal histograms on the price; both share the row settings below.

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

### Oscillators

Each in its own pane below the price.

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
- **DMI Stochastic Extreme.** A stochastic of the DMI oscillator (+DI minus −DI, Wilder smoothing), as in
  thinkorswim's DMI_StochasticExtreme (Barbara Star, *Stocks & Commodities*, January 2013): the sum over 3 bars
  of (oscillator − its 3-bar low) over the sum of its 3-bar range, 0 to 100, with lines at 90 and 10. DMI length
  10 by default. thinkorswim's crossing arrows are left out: lines only.
- **Polarized Fractal Efficiency (PFE).** How efficiently price moved over the last N bars (Hans Hannula,
  1994): the straight-line distance between the close N bars ago and now, as a % of the bar-by-bar path,
  each bar one unit wide. +100 is a straight rise, −100 a straight fall, near 0 a choppy path. EMA-smoothed
  (length 10, smoothing 5 by default), with dashed lines at ±50 (the trend level, adjustable) and 0.

  - Price is in its own units against a one-bar step, as in thinkorswim and TradingView, so readings depend
    on the stock's price and the bar size. On QQQ's 1-minute bars (Oct 28) it spent about 70% of the day
    beyond ±50; on 5-minute bars about 55%.

### Market internals

Mostly NYSE TICK, which the collector fetches with every stock request ([Connecting to TWS](tws.md#market-internals-nyse-tick-and-trin)), and studies that compare the symbol with others.

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

### Symbols a study reads

Relative strength and Heavyweights need bars for symbols that aren't on any
chart (SPY, NVDA, AAPL, ...). The chart asks the collector for them automatically, like a typed symbol:
in Replay it fetches that day (plus the usual 5 days before it and the daily history), and in Live it
streams them. The first time, ten holdings with 10 years of daily history make a long queue (IBKR allows
about 50 history requests per 10 minutes); boxes show "…" until a holding's bars arrive.

### Levels

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
  and moves come from `tools/market_events.py` ([Tools](tools.md#market-events-what-moved-qqq-and-why)).

### Calculation notes

- Moving averages and oscillators are calculated on the chart's timeframe. They use earlier cached
  days to warm up, so they are defined from the first bar of the day.
- RSI, ATR and ADX use Wilder's smoothing, the convention most platforms use. Values can still
  differ slightly from TWS, depending on how much history each platform loads.

## The support / resistance ladder

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
