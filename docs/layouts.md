# Layouts and the watch list

A window is a grid of **cells**, laid out in rows. A cell is a [chart](charts.md) or a watch list.

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

A list of symbols with fixed columns: **Last, Chg, Chg %, Volume, High, Low**, from the cached 1-minute bars
of the day on screen. In Replay they follow the cursor; in Live they update every 5 seconds.

- **Click a row**, or move through the list with the **↑ / ↓** keys, to show that symbol on the linked chart:
  the **Active chart** by default, or a chosen one in **Chart**.
- **Own list** or a watch list saved under **Load data…**. **Edit** takes symbols separated by spaces, commas
  or lines, or a thinkorswim share link. A new watch list starts with the symbols on screen.
- Symbols not cached for that day say so; **Fetch from TWS** asks the collector for them (in Live it then
  streams them).
- Market internals (TICK, ADD, VOLD and so on) show no % change and no volume, which mean nothing for them.
- **Chg** and **Chg %** are from the prior day's close; **Volume**, **High** and **Low** are for regular hours
  (or premarket, before 09:30).
- Its **≡** menu adds a chart or watch list next to it, or removes it.

## If a dashboard comes back as one chart

Pages ask for their scripts at an address that changes with every update, so no browser (Chrome, Firefox or
any other) can run an old copy with a new page. A browser that opened a dashboard while it still had old
scripts may have saved that dashboard as one chart; clearing the site's data in that browser (Firefox: the
padlock in the address bar, "Clear cookies and site data") brings every dashboard back to how it starts.
