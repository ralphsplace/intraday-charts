# Known limitations

- **Up to 5 days per minute chart.** Longer history is used for warm-up and daily levels, but isn't drawn;
  for longer stretches use 1d, 1w or 1M candles.
- **Early closes.** Half-day sessions (e.g. the day after US Thanksgiving) are treated as full days.
- **Volume profile.** It is approximated from 1-minute bars, with each bar's volume spread evenly
  across the bar's high-low range.
- **Drawings are per browser.** Drawings and the current window are stored in the browser. Use
  saved layouts and views (kept on the NAS) to move a setup to another device.
- **Holiday list.** US market holidays are listed through 2027. Later holidays are requested,
  come back empty, and are reported as "no bars".
- **Big grids replay more slowly.** Every chart is recalculated on the NAS at each step: about
  0.1 s per chart on a desktop CPU. A 3×3 grid therefore steps roughly once a second.
- **Earnings dates.** Only companies that file 8-K reports with the SEC; see "Earnings view". An Item 2.02
  filing within 45 days of a later one (e.g. a preliminary-results notice) counts as part of that report.
- **Expected move.** Option snapshots from a live TWS haven't been tested yet (only against the test suite's
  invented chain). Strikes are read from the SMART chain; an expiry missing a strike is skipped, not interpolated.
- **Option chain.** Values before an expiry are Black-Scholes estimates (no dividends or early exercise), and
  live TWS chain snapshots haven't been tested yet (only against the test suite's invented chain). The default
  (±9 strikes, 2 expiries, plus the expiry strip) is about 120 snapshots; ±15 for 4 expiries is about 300 and can
  take up to a minute.
- **News headlines.** IBKR keeps about 6 months of headlines, and their times are read as UTC; the
  match to real headlines hasn't been checked against a live TWS yet.
- **FinViz watch lists.** Tested against FinViz's export format, not yet against a live FinViz Elite account.
  Share classes FinViz writes with a dash (`BRK-B`) are left out.
