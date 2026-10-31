# Charts

A dashboard window holds one or more charts ([Layouts](layouts.md)). Click a chart to make it the
**active** one: its border turns green, and **f(x)** studies apply to it.

## A chart's settings

Each chart has its own:

- **Symbol:** type any stock or ETF symbol in the box at the top left and press Enter (Esc undoes).
  The list under it suggests cached symbols and your watchlists. If bars for that symbol and day
  aren't cached, they are fetched from TWS ([Connecting to TWS](tws.md)) and the chart fills in when they
  arrive. A symbol you're typing is never overwritten by a refresh.
- **Candle duration**, in the menu after the symbol: 1, 3, 5 or 15 minutes, or **1d**, **1w** and **1M**
  (daily, weekly and monthly candles).
- **Range shown**, in the menu after it:
  - minutes: Today, 2, 3 or 5 days, with dotted day separators
  - 1d / 1w / 1M: 3 or 6 months, 1, 2, 5 or 10 years. They start at 6 months (1d), 2 years (1w) and
    10 years (1M), and each keeps its own choice.
- **Link colour**, the small square after the symbol: charts and watch lists of the same colour show the same
  symbol ([Symbol links](layouts.md#symbol-links)).
- **Price type**, in the menu after the range (below).
- **Studies:** none by default ([Studies](studies.md)). Each study starts with the defaults set on the
  [Config page](config.md).

### Daily, weekly and monthly candles

They come from the daily prices the collector keeps (10 years; [Connecting to TWS](tws.md)).

- The replay day's candle is built from its 1-minute bars up to the replay time (regular hours), so a
  replay never shows the rest of the day, and in Live it forms as the day goes on.
- A week starts on Monday and a month on the 1st, and the week or month holding the replay day is still forming.
- Symbols without daily prices from IBKR (TICK, TRIN, ADD, VOLD) show one candle per cached 1-minute day.
- Studies that need minutes (VWAP, session levels, prior day, S/R ladder, Saty ATR, events, volume
  profile, $TICK) stay on the chart but draw nothing on 1d / 1w / 1M, and their legend says
  "intraday charts only".

### Price types

The price type's settings are behind the gear button next to its menu (colors, fill, thickness, and settings of
its own; **Defaults** in the dialog puts them back). Saved chart views keep the price type and its settings.

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

## What all charts share

- **Day and replay.** All charts show the same day and replay together. A step moves by the
  shortest minute candles on screen (5 minutes when every chart shows 1d, 1w or 1M).
- **Linked crosshairs** (on by default). Moving over one chart shows the same time on the others.
- **Shade extended hours.** Premarket and after-hours bars get a grey background.
- **Fit levels.** Stretches each price scale so every level line is on screen.

## Resizing

- Drag the thin bar between two charts to make a column wider or a row taller. Double-click it to
  make them equal again. Sizes are remembered for each layout.
- **⤢** in a chart's header (or double-clicking an empty part of the header) maximizes that chart.
  **⤡** or Esc brings the grid back.
- Each chart keeps the same stretch of time on screen when it is resized.
- In small charts (as in 3×3), the study list folds behind a **Studies (n)** button, and level lines
  keep their price-axis labels but drop their names.

## Replay and Live

- **Replay** steps through any cached day without looking ahead. Every study only sees bars that
  had started before the cursor time. Use ◀ ▶ to step one bar, or Play.

  - **Day** lists the days cached for the symbols on screen.
  - To replay another day, open **Load data…**, pick the symbols and the day on the calendar,
    and click **Fetch from TWS**. The charts switch to that day and fill in as the bars arrive.

- **Live** shows today and refreshes every 5 seconds. The replay controls at the bottom are removed while in
  Live, and the charts use the room.

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

## Drawings

The **Alert**, **Line**, **Trend** and **VWAP** tools are in the top bar, next to **Layouts**. Press one, then
click the chart you want it on: any chart in the window, small or large. The chart under the mouse says what to
click. Once it's placed, the tool switches off; Escape or pressing the button again cancels it. Drawings belong to
the symbol, so they appear on every chart of that symbol, on any timeframe.

| Tool | How | Notes |
|---|---|---|
| Alert | Click a price on the chart | Draws `MARK >= price` above the current price, or `MARK <= price` below it. When price gets there, you get a sound, an on-screen message and, if you allowed it, a desktop notification. This happens in Live mode, or while replaying forward. A triggered alert turns grey and shows the time; **Re-arm** resets it. |
| Line | Click a price | A plain horizontal line, with an optional label. |
| Trend | Click two points | Optional **Extend to the right**. |
| VWAP | Click a bar | Adds an **Anchored VWAP** study to that chart, starting at the bar you clicked. Not a drawing: change or remove it like any study (its settings hold the anchor time). |

**Managing drawings.** Every drawing is listed in the chart's legend, with **Settings** (price,
color, line type, thickness) and **×** to delete it. Drawings are stored in this browser. The
[Option chain view](option-chain.md) can add a structure's strikes and breakevens as lines here.

## Saved chart views and layouts

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
