# Tools: backtests and market events

## Testing a signal: VZO vs MACD with a fixed stop

`tools/backtest_signals.py` replays the cached bars and trades each signal set with the same stop.
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

## Market events: what moved QQQ, and why

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
