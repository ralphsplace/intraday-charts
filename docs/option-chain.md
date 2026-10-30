# Option chain view

![QQQ's chain for Mon Nov 2 from TWS, taken after the close: deltas, implied volatility and each expiry's expected move in the strip. Bid and ask are empty outside regular hours, so build structures during the session. The four panels (chain, structure, evaluation, profit/loss grid) scroll under the fixed expiry strip](img/optionsView.png)

`http://<your-nas>:8050/options` (also **Option chain** in the drop-down at the top left of every page).

**What it's for:** building an option structure from the chain and judging it before you trade: its
profit and loss by price and time, its greeks, and where the stock's open interest sits. It is read-only:
it evaluates structures and never places or prepares orders.

Type a stock and press Enter. The chain, the strike profile, the structure, the evaluation and the
profit/loss grid are stacked in one column and scroll together; the toolbar and the expiry strip stay at the top.

## A typical session

1. Type the stock, e.g. `AMZN`, and press Enter. The chain for the first expiry opens.
2. Click the expiry you want in the expiry strip. For a calendar or diagonal, pick the later one under
   **Back expiry**.
3. Pick a template and press **Fill from expected move**, or click bids and asks in the chain to build your own.
4. Read the evaluation: max profit and loss, breakevens, the risk graph **At** a later time, and an
   **IV change** for the drop after earnings.
5. Set a **Loss limit $** to see the stock prices where that loss is reached.
6. **Show levels on the chart** to watch those prices on the stock's charts, and **Save structure** to keep it.

## Expiry strip

The next 8 expiries, each with its days left and expected move (the at-the-money straddle). Click one to view
its chain. The expiry tagged *back* is the later one for calendars and diagonals (pick it under
**Back expiry**); *in structure* marks expiries with legs.

## The chain

Calls and puts for the strikes around the price (**Strikes**: ±5, ±9 or ±15): delta, implied volatility, bid
and ask. A line marks the stock's price, rows inside the expected move are shaded, and the strikes nearest it
are tagged EM.

- **Click a bid to sell, an ask to buy** (one contract; click again for more). The structure's legs are
  highlighted in the chain.

## Strike profile

Gamma exposure by strike for the expiry on view: where the open interest is, weighted by how fast its delta
changes.

- **The bars.** For each strike, gamma × open interest × 100 × price² × 1%: the dollars of delta its options
  gain or lose for a 1% move in the stock. Calls are drawn up (green) and puts down (red), the usual
  convention, which assumes dealers are long calls and short puts.
- The dashed line is the stock's price.
- **Near** shows the 5 strikes either side of the price, **All** every strike in the snapshot (**Strikes** sets
  how many).
- Hover a bar for its value and open interest.
- Below it: the net, the strikes with the most call and put gamma, and how many strikes had no open interest.

How it's usually read: strikes with a lot of gamma are prices the stock often gravitates to or stalls at
near expiry. That's the common reading, not a signal: the convention's dealer positioning is an assumption.

**Open interest** comes from TWS with the quotes. TWS sends it only on a subscription (not with snapshots), so
the collector subscribes for about 3 seconds per batch and cancels. It's as of the previous close and changes
once a day, so later refreshes that day reuse it.

## Structure

The legs with their mid price, delta and theta, and the net debit or credit.

- **Buy/Sell** switches a leg's side, the box sets the number of contracts, × removes it; **Reverse** flips
  every leg.
- **Save structure** keeps it on the NAS by name (`data/user/structures.json`); **Saved** opens one again,
  re-priced at the latest quotes.

### Templates

Filled from the expected move of the expiry you're viewing with **Fill from expected move**:

| Template | Legs |
|---|---|
| Double diagonal | short call and put at the strikes nearest the expected move; long call and put one strike closer, in the back expiry |
| Call diagonal | the call side of the double diagonal |
| Call calendar | short call at the money; long call at the same strike in the back expiry |
| Call vertical | long call at the money, short call at the expected move |
| Straddle | long call and put at the money |
| Strangle | long call and put at the expected move |
| Iron condor | short call and put at the expected move, long wings 2 strikes further out |
| Call butterfly | calls +1 / −2 / +1: the body at the money, wings about the expected move either side |
| Wish list | puts +1 / −3 / +1 at the expected move (below) |

### The wish list

Sell 3 puts at the strike nearest the expected move below the price, and buy 1 put 2 strikes above and 1 put
2 strikes below. It's a put butterfly plus one more short put at its middle strike, or equally a put-side iron
condor's shape with an extra short put:

- usually opened for a credit
- the most profit if the stock closes at the middle strike at expiry
- above the upper wing, every put expires worthless and you keep the credit
- below the lower wing, it's like owning 100 shares bought at the middle strike (less the credit)

So it suits a stock you'd be glad to buy at that price anyway. The max loss shown assumes the stock can go to 0.

## Evaluation

For 1 structure, in $:

- max profit and loss (or *unlimited* with uncovered calls), breakevens, the chance of a profit, and the net
  delta, gamma, theta per day and vega per IV point
- the **risk graph**: profit/loss against the stock's price now (dashed) and **At** a later time (today's close,
  noon or the close of the front expiry), with the expected move shaded; hover for values
- **IV change**: every leg's implied volatility moved by a few points, e.g. the drop after earnings

## Profit / loss by price and time

The structure's value at 11 stock prices (spaced over about 1.5 expected moves) at each time. This is the link
from the stock's price to the structure's.

- **Loss limit $** (e.g. −150) shows the stock prices where that loss is reached at the chosen time.
- **Show levels on the chart** draws the short strikes, breakevens and loss-limit prices as horizontal lines
  on every chart of the stock (in this browser; they can be edited or removed there like any line). Showing
  them again replaces them.

## Where the numbers come from

- Bid, ask and implied volatility are snapshots from TWS, all taken at one time, when the page opens a stock,
  changes what it needs, finds the quotes older than 5 minutes, or on **Refresh quotes**. They're cached in
  `data/chains/<SYMBOL>.json`.
- Values before an expiry are estimates from Black-Scholes with each leg's own implied volatility (4% rate, no
  dividends, European exercise).
- The chance of profit assumes a lognormal move at the front expiry's at-the-money implied volatility.
- **Needs** a US options market-data subscription in IBKR (OPRA), like the expected-move page.
- The default (±9 strikes, 2 expiries, plus the expiry strip) is about 120 snapshots; ±15 for 4 expiries is
  about 300 and can take up to a minute.
