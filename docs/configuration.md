# Configuration

- **`data/events.json`**: scheduled events and headlines for the Events study. Edit by hand, or let
  `tools/market_events.py` fill it (it keeps your own entries). For example:
  ```json
  [{"date": "2026-10-21", "time": "10:00", "label": "Existing home sales", "kind": "scheduled"},
   {"date": "2026-10-21", "time": "14:00", "label": "Fed speaker", "kind": "scheduled"}]
  ```
  `kind` is `scheduled` or `headline`. Times are US/Eastern, 24-hour.
- **`data/user/config.json`**: the application config, edited on the [Config page](config.md): the named watch lists,
  each watch list type's default columns, and the studies' default settings and colours.
- **`config.json`**:
  - the default symbol
  - optionally `"default_layout"`: the studies a new chart starts with (none by default), e.g.
    `[{"type": "vwap", "params": {}}]`
- **`.env`**: the TWS address and port, symbols, backfill length, live write interval, and the web port. `WEB_WORKERS` (default 2) sets
  how many processes serve charts; raise it on a NAS with more cores if big grids replay slowly.
- **`HOLDINGS` in `.env`**: `on` lets the collector read the account's positions for the watch list's
  [Holdings](layouts.md#holdings) list (read-only, positions only). Empty (the default): the account isn't read.
- **`FINVIZ_TOKEN` in `.env`**: your FinViz Elite API token (the `auth=` value in FinViz's export links, or under
  your FinViz account's settings), for [watch lists from FinViz](layouts.md#a-watch-list-from-finviz). Only the
  collector gets it, and sends it only to finviz.com. Empty: FinViz watch lists are off. If the collector runs on
  the Windows PC instead (`tools/run_collector_windows.bat`), set it in that file too.
- **Security settings in `.env`** (see [Purpose and security model](security.md)):

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
