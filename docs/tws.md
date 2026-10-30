# Connecting to TWS

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

## Set up TWS (once)

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
  The expected-move and option-chain pages also need US options quotes (OPRA).
- **One login at a time.** IBKR allows one session per username. Logging in to IB Gateway (or the
  mobile or web app as the same user) logs TWS out, which may be what broke the Gateway setup.
- **Pacing.** IBKR limits historical requests to roughly 60 per 10 minutes.
  - The collector leaves 2 seconds between requests and sends at most 50 in any 10 minutes.
  - Loading one day for 5 new symbols (6 days each, plus daily history) takes about a minute.
  - A first backfill of 30 days for 2 symbols takes about 12 minutes.
  - Requests from the page jump ahead of a running backfill. Streaming is not affected.

## Market internals (NYSE TICK and TRIN)

Every stock request (from the page, `SYMBOLS`, or Live) also fetches the indexes listed in
`COMPANIONS` for the same days. The default is `TICK-NYSE TRIN-NYSE`.

- **Checked on your account (October 2026):**
  - NYSE TICK and TRIN: real-time, with 1-minute history at least 3 months back.
  - NYSE advance/decline (`AD-NYSE`): real-time, but IBKR returns no intraday history. The same goes for NYSE
    up/down volume (`VOL-NYSE`). The collector records both from live quotes (see [the Internals dashboard](dashboards.md#the-internals-dashboard)).

  - Nasdaq TICKs (`TICK-NDX`, `TICK-NASD`): delayed only, so they need a Nasdaq index data
    subscription.

- **`tools/probe_ibkr.py`** re-checks all of this against your TWS.
- **To backfill TICK for days already cached**, run the collector with the same `--days`, e.g.
  `docker compose run --rm collector python tools/fetch_ibkr.py --symbols QQQ --days 250 --client-id 18`.
  Cached QQQ days are skipped and only the missing TICK and TRIN days are fetched.

## Run the collector: pick one

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

### If it doesn't connect

The collector's log line says why:

- *Connection refused*: TWS isn't running, or the API setting or port is wrong.
- *Timed out*: a firewall is in the way, or IB_HOST is wrong.
- TWS asks you to accept the connection: add the collector's IP under Trusted IPs.

## Watchlists, and thinkorswim share links

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
