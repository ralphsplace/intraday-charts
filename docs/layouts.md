# Layouts and the watch list

A window is a grid of **cells**, laid out in rows. A cell is a [chart](charts.md) or a watch list. Cells can be
[linked by colour](#symbol-links) so they show the same symbol.

## Choosing a layout

**Layout** in the toolbar switches between 1 chart (the default), 2 or 3 side by side, 2×2, 3×2, 3×3,
4×3, and **2 over 4** (two wide charts above four).

- Layouts with the same number of charts in every row have column and row splitters, each column splitter
  running top to bottom.
- In the others (e.g. 2 over 4) each row has its own column splitters, so the top and bottom rows are sized
  separately.
- Double-click a splitter to make its row's charts (or all rows) equal again.
- Switching to a smaller layout keeps the hidden charts' setups for when you switch back.

**Any number of top and bottom charts:** on the Dashboards page, create a dashboard with "Start from: Top and
bottom rows of charts…" and pick how many charts go on top and how many below (1 to 6 each), e.g. 3 over 5.
The Layout menu shows that dashboard's own layout alongside the named ones.

## Adding and removing charts

Each chart's **≡** menu has a **Layout** section:

- **+ Chart left / + Chart right** adds a chart next to this one in its row. The new chart is a copy of this
  one (same candle duration, range, price type and studies), with its symbol box selected: type a symbol and
  press Enter.
- **+ Row below** adds a new row with one chart under this chart's row.
- **+ Watch list left / + Watch list right** adds a [watch list](#the-watch-list) instead.
- **Remove this chart** closes it up; a row left empty goes away. **Undo** on the message that follows brings
  it back.

Rules:

- Widths stay equal in a row of equal charts; otherwise the new chart takes half the width of the one it's
  added next to.
- A row holds at most 6 cells and a window at most 4 rows. The last chart can't be removed.
- The result is kept for the dashboard in this browser, and **Layouts ▾** can save it like any layout.

Examples, starting from **2 over 4**:

| You want | Do |
|---|---|
| SPY at the far left of the bottom row (2 over 5) | **+ Chart left** on the bottom-left chart, type `SPY`, Enter |
| A watch list column at the right (3 over 4) | **+ Watch list right** on the top-right chart |
| A wide chart under everything | **+ Row below** on any bottom-row chart |

## The watch list

Lists of symbols in **tabs**, with the columns you choose: by default **Last, Chg, Chg %, Volume, High, Low**, from
the cached 1-minute bars of the day on screen. In Replay they follow the cursor; in Live they update every 5 seconds.

- **Click a row**, or move through the list with the **↑ / ↓** keys, to show that symbol on the charts of the
  watch list's [link colour](#symbol-links), or on the **active chart** when it isn't linked.
- **Each tab shows a named watch list** ([below](#named-watch-lists)): a list of symbols you typed or imported, a
  FinViz screen or portfolio ([below](#a-watch-list-from-finviz)), or your account's holdings ([below](#holdings)).
- Symbols not cached for that day say so; **Fetch from TWS** asks the collector for them (in Live it then
  streams them).
- Market internals (TICK, ADD, VOLD and so on) show no % change and no volume, which mean nothing for them.
- **Chg** and **Chg %** are from the prior day's close; **Volume**, **High** and **Low** are for regular hours
  (or premarket, before 09:30).
- Its **≡** menu adds a chart or watch list next to it, or removes it.

### Named watch lists

Watch lists are named, and the names are unique across the whole app. They're defined in the application config
(`data/user/config.json`, one `name: definition` entry each; see the [Config page](config.md)), so every dashboard,
watch list panel, browser and device sees the same ones. **Load data…** reads and saves the same lists.

- A new list is called **Watch list N**, N one more than the highest in use (Watch list 1, Watch list 2, …).
- **Rename** a list by double-clicking its tab: Enter keeps the name, Esc cancels. A name already in use is
  refused. Every tab that shows the list follows the new name, in any dashboard.
- The menu at the watch list's top left switches the tab to another list, or makes a new one: **New watch list…**
  (symbols you type), **New FinViz screen or portfolio…** or **New Holdings list (IBKR)**.
- **Edit** changes the list itself: its symbols, or its FinViz address. Every tab showing it, anywhere, sees the
  change.
- A list's definition depends on its source: `{"source": "symbols", "symbols": [...]}`, `{"source": "finviz",
  "feed": {"address": ...}}` or `{"source": "holdings"}`, plus an id that never changes.
- **Delete** a list from the watch list's menu (**Delete "…"…**, then **Delete** on the message), or on the
  [Config page](config.md), which lists every watch list. A tab showing a deleted list says so.
- Watch lists made before lists were named become named lists (Watch list N) the first time they're opened.

**Edit** takes symbols separated by spaces, commas or lines, or the contents of an exported watch list file (a
thinkorswim or broker CSV with a Symbol column, a FinViz export, a TWS export). Web addresses are never read as
symbols. **thinkorswim share links (`tos.mx/!…`) can't be used**: the page behind one shows only the list's name,
and the symbols are delivered only to thinkorswim itself. In thinkorswim, export the watch list to a file from its
menu and paste the file's contents (or import it under **Load data…**).

### Tabs

Each tab shows one named watch list with its own columns, heat and sorting. Only the tab on view is fetched.

- **+** adds a tab with a new, empty list (Watch list N): type its symbols and press **Apply**.
- Click a tab to show it; double-click it to rename its list.
- **×** on the tab on view closes the tab. The list itself is kept (pick it again from the menu); **Undo** on the
  message that follows brings the tab back. The last tab stays.
- Up to 12 tabs per watch list panel. The tabs, the tab on view and each tab's columns are kept with the dashboard
  and in saved layouts.

### Columns

**Columns** in the watch list's header lists every column the tab can show, by section; tick the ones you want.
**Drag a column's header** onto another to move it there. **Defaults** puts the tab's default set back: each list
type's default columns and their order are set on the [Config page](config.md). Hover a column's name for what it is. Columns, heat and sorting are
kept per tab.

- **Sorting.** Click a column's header: up (▴), down (▾), then the list's own order again. Graphical columns sort
  by what they show (the day-range bar by where the price sits in the range, the sparkline by the day's change).
- **Heat.** Columns marked **heat** in the chooser can shade their cells: deeper green above 0 and deeper red below
  (around 1× for ratios), full colour at ±4% (or 3×). Off until you tick it.
- **Replay.** Every value is worked out up to the cursor, like the charts.
- **Market internals** (TICK, ADD, VOLD) show only their own prices and sparkline; gap, VWAP, ATR and study
  columns mean nothing for them and stay empty. Indexes such as VIX trade no volume, so they have no VWAP or
  relative volume.

| Section | Columns |
|---|---|
| Price and volume | Last, Chg, Chg %, Volume, High, Low, Prev close, Time (of the last bar) |
| The day so far | Open, Gap %, Chg open, Chg open %, VWAP, vs VWAP %, **Day range** (bar), **Today** (sparkline), **Rel vol** (bar), **vs VWAP** (state), **Initial balance** (state) |
| Daily history | Range/ATR (bar), ATR, 52w high, 52w low, From 52w high %, **52w range** (bar), Avg vol (20d), Prior high, Prior low, SMA 50 (d), SMA 200 (d), **ATR zone** (state) |
| Earnings and options | Earnings (the next report in the market calendar, or the last one found on SEC EDGAR), Exp. move % (when the options are cached) |
| Study values | SMA 20 / 50 / 200 and EMA 9 / 21 on 5-minute bars, each with its "vs … %" distance |
| Holdings | Qty, Avg cost, Cost basis, Mkt value, Weight % (bar), Unrl P/L, **Unrl P/L bar**, Unrl P/L %, Day P/L |
| FinViz | Company, Sector, Industry, Mkt cap, P/E, as FinViz exports them |

**The graphical columns:**

- **Day range:** a track from the day's low to its high (widened to the prior close when it's outside), the last
  price as a dot, and ticks for the open (grey), the prior close (amber) and VWAP (teal).
- **52w range:** the same against the 52-week low and high; the grey band is today's range.
- **Today:** the day's prices as a small line, green above the prior close and red below it, the prior close
  dotted, extended hours dimmed.
- **Rel vol, Range/ATR, Weight %:** a bar behind the number (rel vol full at 3×, range/ATR at 1.5×).
- **Unrl P/L bar:** gains to the right in green, losses to the left in red, scaled to the largest in the list.
- **States** (vs VWAP, Initial balance, ATR zone) describe the day so far with a neutral dot: teal above, amber
  below, grey otherwise. They are never buy or sell signals.

### Holdings

A tab of your IBKR account's **stock and ETF positions**, biggest first, with **Qty, Avg cost, Last, Mkt value,
Unrl P/L, Unrl P/L %, Day P/L, Chg %**. The footer adds them up (value, unrealized and day P/L) and says how old the
positions are.

- **Showing it.** In the watch list's menu pick **New Holdings list (IBKR)**: a named list (Watch list N) whose source
  is your holdings. Rename it, e.g. "Holdings".
- **Turning it on.** Set `HOLDINGS=on` in `.env` and restart: `docker compose --profile collector up -d`. The
  collector then reads the account's positions once a minute while it's in Live mode.
- **Read-only, and positions only.** Orders, executions and account balances are never read, and nothing can be
  traded. Account numbers are kept masked (…1234). Off (the default), the account isn't read at all.
- **Values are at the price on screen**, from the cached bars: live in Live, the cursor's price in Replay. The
  positions themselves are always today's.
- Positions in several accounts are added up, with the average cost weighted by shares.
- Options, futures and other positions aren't listed: the footer counts them. Neither are share classes IBKR
  writes with a space (`BRK B`).
- Symbols without bars for the day show their quantity and cost; **Fetch from TWS** gets the bars.

### A watch list from FinViz

A FinViz screen (e.g. top gainers with average volume over 2M) or one of your FinViz portfolios, kept up to date.

1. Set `FINVIZ_TOKEN` in `.env` ([Configuration](configuration.md)) and restart:
   `docker compose --profile collector up -d`.
2. In the watch list's menu pick **New FinViz screen or portfolio…**. It becomes a named list (Watch list N; rename it).
3. Paste the screen's or portfolio's address from your browser's address bar on finviz.com, e.g.
   `https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers&o=-change`, and press **Apply**.

- The collector fetches the list from FinViz's export and the watch list fills in a few seconds later. It's
  fetched again when it's more than 15 minutes old and on screen, or straight away with **Refresh list**.
- The list's name below it opens it on finviz.com.
- Up to 100 symbols are shown (the footer says when FinViz sent more), in FinViz's order: sort the screen on
  finviz.com (e.g. by change) to choose which.
- The prices are still the dashboard's own, from the cached bars; **Fetch from TWS** gets the symbols not
  cached yet.
- Symbols IBKR writes differently, such as share classes (`BRK-B`), are left out.

Needs a **FinViz Elite** subscription: free accounts can't export. Only the address's screen settings (`v`, `f`,
`o`, `s`, `t`) or portfolio number (`pid`) are kept, and only finviz.com addresses are accepted. An `auth=` in a
pasted address is dropped; the token stays in `.env` and is sent only to finviz.com.

## Symbol links

Link cells by colour, as in TWS and thinkorswim: charts and watch lists of the same colour show the same symbol.

- The small square in each chart's and watch list's header picks its colour: red, green, blue, yellow, purple,
  orange, or **Not linked** (dashed). Hover it to see how many others share the colour.
- **Typing a symbol** into a linked chart changes every chart of that colour.
- **Clicking a row** of a linked watch list changes every chart of its colour, and other watch lists of that
  colour mark the row.
- A window can have several colours at once, each with any number of cells. For example, red for a 1-minute and
  a 5-minute chart driven by a watch list of top gainers, and blue for SPY and QQQ charts driven by another.
- A watch list that isn't linked drives the active chart (click a chart to make it active).
- **+ Chart left / right / Row below** copies a chart without its colour, so typing the new chart's symbol
  doesn't change the one it was copied from.
- Colours are kept with the dashboard and in saved layouts. A watch list saved by an earlier version, linked to
  one chosen chart, gets a colour shared with that chart.

## If a dashboard comes back as one chart

Pages ask for their scripts at an address that changes with every update, so no browser (Chrome, Firefox or
any other) can run an old copy with a new page. A browser that opened a dashboard while it still had old
scripts may have saved that dashboard as one chart; clearing the site's data in that browser (Firefox: the
padlock in the address bar, "Clear cookies and site data") brings every dashboard back to how it starts.
