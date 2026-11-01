# Paper trading

Practise trades in Replay, and test rules on past days, with a paper account. Paper accounts are **simulated on
the NAS from the cached bars**: they never talk to TWS or your IBKR account, and nothing here places a real order.
Results are only as good as the model below: read its limits before trusting a number.

## Paper accounts

Make and manage accounts on the [Config page](config.md#paper-accounts): starting cash, commissions (IBKR Fixed by
default), slippage and whether short selling is allowed. Names are unique across the app; a reset puts the balance
back to the starting cash and keeps the history.

## Practising in Replay

1. On a chart's **≡** menu, under **Paper trading**, pick an account. The chart remembers it.
2. Step the replay to where you want to start (Replay mode, a minute chart).
3. A strip under the chart's header shows the account, your position, unrealized and realized P/L, equity and
   working orders. **Buy** and **Sell** open the order ticket; **Flatten** cancels every order and closes the
   position on the next bar.
4. Step forward: orders fill as the bars they would have filled on come into view. Each fill shows a message with a
   sound. Working orders and your average price are drawn on the chart as labelled lines.

The order ticket offers:

- **Market**, **Limit**, **Stop**, **Trailing stop** (follows the best price by a dollar distance)
- **At a study line**: follows one of the chart's study lines (VWAP, an SMA, …) as it moves. Below the price, a buy
  works as a limit; above, as a stop (the other way round for a sell).
- **Attach a stop and target** (a bracket): once the entry fills, the stop and target work; whichever fills first
  cancels the other.

The ticket starts with as many shares as the account can afford, up to 100.

**Stepping back.** If you step the replay back before trades you made, the strip stops taking orders and asks
whether to remove those trades. Remove them to trade again from there; or step forward to where you were.

**The end of the day.** At the last regular-hours bar, working orders are cancelled and any position is closed at
that bar's close. Positions are never held overnight.

## How fills work

The same rules for practice and for backtests:

- **No look-ahead.** An order placed with the replay at 10:30 can fill on the 10:30 bar (the first one not yet
  shown), never on a bar already on screen. Fills are checked on 1-minute bars, whatever the chart's timeframe.
- **Market** orders fill at the next bar's open, plus slippage.
- **Limit** orders fill when a bar trades through the limit: at the limit, or at the open if the bar opens past it.
- **Stop** orders fill when a bar trades through the stop: at the stop, or at the open when price gaps through it;
  plus slippage.
- **Within one bar**, stops are checked before limits: a bar that touches both your stop and your target exits at the
  stop. Results are never better than they could have been.
- **Trailing stops** move with a bar's best price only after that bar has been checked for a fill.
- **Study lines** use the study's value at the close of the previous bar.
- **A bracket's exits** start working on the bar after the entry fills.
- **Commissions**: IBKR Fixed by default: $0.005 a share, at least $1.00, at most 1% of the trade's value.

## Limits

- Stocks and ETFs only; options aren't simulated.
- An order fills in full when its price trades: no queue position, partial fills or order book.
- No margin, borrow fees or short-sale restrictions.
- Each chart's practice session is one symbol on one day, starting with the account's balance; sessions on several
  charts at once don't share buying power.
- Synthetic (`-DEMO`) symbols are labelled as such in the strip.
