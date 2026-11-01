# Config page

`http://<your-nas>:8050/config` (also **Config** in the drop-down at the top left of every page).

**What it's for:** the settings that belong to the whole app rather than to one chart or dashboard. They are kept
in the **application config**, one file on the NAS (`data/user/config.json`), so every dashboard, browser and device
uses the same ones (the list of dashboards is its own file, `data/user/dashboards.json`). Changes are saved as you
make them. The page opens on the section you used last; `/config?tab=<section>` opens one directly.

## Dashboards

Create, rename, duplicate and delete dashboards, choose the default, and read the environment check: see
[Dashboards](dashboards.md).

## Watch lists

Every [named watch list](layouts.md#named-watch-lists), with its source (symbols, FinViz or Holdings) and what's in
it.

- **Rename:** type the new name and press Enter (Esc cancels). Names are unique; a name in use is refused. The list
  keeps its id, so every tab showing it, in any dashboard, follows the new name.
- **Delete:** click twice (the button asks "Delete? Yes"). The list is removed everywhere; tabs that showed it say
  so.

## Watch list columns

The columns a new tab starts with, and their order, for each type of watch list: **Symbols**, **FinViz** and
**Holdings**.

- **+ a column** under *Available* adds it at the end; **▲ / ▼** move it; **×** removes it. Symbol always comes first.
- **Built-in defaults** puts the type's original columns back.
- A tab can still choose its own (**Columns** in the watch list, and dragging its headers).

## Study defaults

The settings and colours each study starts with when it's added to a chart, and what the **Defaults** button in a
study's settings puts back.

1. Pick a study on the left (**Find a study** filters the list). Studies with your own defaults are marked **•**.
2. Change its inputs, colours, line types and thicknesses, and press **Save as defaults**. Only the settings that
   differ from the built-in ones are kept.
3. **Built-in defaults** removes your defaults for that study.

Studies already on charts keep their own settings: the defaults apply to studies added afterwards. Values that
aren't allowed (a length out of range, say) are brought within range, as in a study's own settings.

## Paper accounts

Accounts for practising trades in Replay and for backtests. They're simulated on the NAS from the cached bars and
never talk to TWS or your IBKR account.

- **New account** makes "Paper N" with the defaults; names are unique across the app.
- **Rename** keeps the account's history. **Reset** puts the balance back to the starting cash; the trades before it
  stay in the history. **Delete** asks first; the history file is kept aside on the NAS (`.deleted`).
- **Settings**, for new accounts (the defaults) or one account: starting cash; commission per share, minimum per
  order and at most a % of the trade's value (IBKR Fixed by default: $0.005, $1.00, 1%); slippage per share on
  market and stop fills; and whether short selling is allowed (on by default).

Each account's history is in `data/user/paper/<id>.json`.

## The file

`data/user/config.json` has one section per part of this page:

```json
{
 "watchlists": {"Core": {"id": "29905c4e259c", "source": "symbols", "symbols": ["QQQ", "SPY"]},
                "Holdings": {"id": "cbdf586dbe13", "source": "holdings"}},
 "watch_columns": {"quote": ["symbol", "last", "change", "pct", "gap_pct"]},
 "studies": {"sma": {"length": 21, "sma_color": "#ff9800"}},
 "paper_accounts": {"Morning practice": {"id": "4be1c0d2a9f3", "start_cash": 25000.0, "created": 1793539200,
                    "settings": {"commission": {"per_share": 0.005, "minimum": 1.0, "max_pct": 1.0},
                                 "slippage": 0.01, "shorting": true}}},
 "paper": {"defaults": {"start_cash": 30000.0, "settings": {"...": "as an account's"}}}
}
```

Editing it by hand works too (the page and the charts read it again when it changes). Unknown studies, settings or
columns are ignored.

When the server starts, it brings anything an older version saved on the NAS up to date, once: watch lists from
`data/user/watchlists.json` move into `config.json` (the old file is kept as `watchlists.json.moved`), and saved
views, layouts and dashboards get today's settings. The server's log lists what it changed.

If a hand edit leaves the file unreadable (a missing comma, say), the app shows defaults and refuses every change
with a message naming the file, so nothing you wrote is lost; fix the typo and it picks the file up again. Saved
views, layouts and dashboards (`data/user/*.json`) work the same way.
