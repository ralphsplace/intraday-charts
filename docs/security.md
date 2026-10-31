# Purpose and security model

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
  - Every TWS connection is opened read-only, and doesn't download the account's orders or executions.
  - The account's positions are read only when you turn on the watch list's Holdings list (`HOLDINGS=on`):
    by the collector, once a minute in Live, with account numbers masked. A test checks that nothing else reads
    the account.
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
  are on the [Dashboards](dashboards.md) page, and a ⚠ link appears in every page's toolbar when one needs attention.

- **Hardened container:**
  - The server and collector run as a normal user (`APP_UID`, default 1000), with no Linux capabilities.
  - The system files are read-only and no-new-privileges is set.
  - Only the data folder and `/tmp` can be written.
  - On start, `start.sh` gives the data folder to that user, removes write access for others, then drops root.
- **Outbound connections only where you turn them on.** The dashboard itself makes no internet requests.
  Two things can go online, both reading public data only:

  - the collector, for the earnings page, looks up earnings dates on SEC EDGAR, and only when `SEC_CONTACT` is set
  - the collector, for FinViz watch lists, fetches your FinViz screens and portfolios, and only when
    `FINVIZ_TOKEN` is set. It accepts only finviz.com screen and portfolio addresses, rebuilt from their checked
    settings, and the token stays in the collector (the web server is only told that it's set).
  - `tools/market_events.py --gdelt`, when you run it
  The environment check on the Dashboards page says which are on.

- **Supply chain.** Dependencies are pinned and checked for known vulnerabilities (`pip-audit`) on every
  push.
