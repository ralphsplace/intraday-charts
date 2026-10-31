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
- **Where a tab's symbols come from**, in the menu at its top left:
  - **Own list:** **Edit** takes symbols separated by spaces, commas or lines, or a thinkorswim share link. A new
    watch list starts with the symbols on screen.
  - **A watch list saved under Load data…**
  - **FinViz:** a FinViz screen or portfolio ([below](#a-watch-list-from-finviz)).
  - **Holdings (IBKR):** your account's stock and ETF positions ([below](#holdings)).
- Symbols not cached for that day say so; **Fetch from TWS** asks the collector for them (in Live it then
  streams them).
- Market internals (TICK, ADD, VOLD and so on) show no % change and no volume, which mean nothing for them.
- **Chg** and **Chg %** are from the prior day's close; **Volume**, **High** and **Low** are for regular hours
  (or premarket, before 09:30).
- Its **≡** menu adds a chart or watch list next to it, or removes it.

### Tabs

Each tab is a list of its own: its own source and its own columns. Only the tab on view is fetched.

- **+** adds a tab, with its own list: type its symbols and press **Apply**.
- Click a tab to show it. **Double-click** it to rename it (Enter keeps the name, Esc cancels); a tab without a
  name of its own is named after what it shows ("Holdings", "FinViz", a saved list's name).
- **×** on the tab on view closes it; **Undo** on the message that follows brings it back. The last tab stays.
- Up to 12 tabs per watch list. The tabs, their names, the tab on view and each tab's columns are kept with the
  dashboard and in saved layouts.

### Columns

**Columns** in the watch list's header lists the columns the tab can show; tick the ones you want. **Defaults**
puts the tab's default set back. Hover a column's name for what it is.

| Column | What it is | Lists |
|---|---|---|
| Last, High, Low | the day's last price, high and low (regular hours) | all |
| Chg, Chg % | change from the prior day's close | all |
| Volume | the day's volume (regular hours; premarket before 09:30) | all |
| Qty | shares held, over all accounts (negative: short) | Holdings |
| Avg cost | average cost per share, as IBKR reports it | Holdings |
| Cost basis | quantity × average cost | Holdings |
| Mkt value | quantity × the price on screen | Holdings |
| Unrl P/L, Unrl P/L % | market value − cost basis, and as a % of the cost basis | Holdings |
| Day P/L | quantity × change from the prior close | Holdings |

### Holdings

A tab of your IBKR account's **stock and ETF positions**, biggest first, with **Qty, Avg cost, Last, Mkt value,
Unrl P/L, Unrl P/L %, Day P/L, Chg %**. The footer adds them up (value, unrealized and day P/L) and says how old the
positions are.

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
2. In the watch list's menu pick **FinViz screen or portfolio…**.
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
