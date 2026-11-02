# Paper trading

Practise trades in Replay, and test strategies on past days, with a paper account. Paper accounts are **simulated on
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

## The trade panel

A Buy / Sell panel of its own in the window, next to the charts: on any cell's **≡** menu, **+ Trade panel left** or
**+ Trade panel right**.

- Pick the **account** in its header. It trades the symbol of its [link group](layouts.md) (the coloured square),
  or of the active chart when it isn't linked, at the replay cursor.
- It shows the position, unrealized and realized P/L, equity and the last price; then the order form: **Market**,
  **Limit**, **Stop** or **Trailing stop**, the shares, and **Stop and target** as dollar distances (a bracket),
  then **Buy**, **Sell** or **Flatten**. Orders at a study line are placed from a chart's own ticket, where its
  studies are.
- Below: the **working orders** (× cancels one) and **today's fills**, with why each filled.
- It is the same practice session as a chart's strip: a chart of that symbol in the same account shows the same
  orders and position, and a change in either shows in the other.
- If you step back before trades you made, it says how many and offers **Remove them**.

## Rules

A **rule** is a true / false condition, read at each bar's close. Write rules on the [Config page](config.md#paper-rules),
**Paper rules**, in a form, no code.

**Conditions.** A rule has up to 26 conditions, lettered **A**, **B**, **C**… Each compares a price (open, high, low,
close), a number, or a study's line or level (with its settings): *crosses above*, *crosses below*, *is above*,
*is below*. For example *A: Close crosses above Session levels: OR high*.

**Direction.** *is rising* and *is falling* compare a price or study with itself a bar before (or N bars before:
"than 3 bar(s) before"), so its slope is part of the rule. "VZO is above −40 and the current VZO is above the
previous" is:

- *A: VZO is above −40*
- *B: VZO is rising*
- True when `A AND B`

Any price or study can also be read **bars ago** (the box next to it, blank for this bar): *Close is above High 1 bar
ago* (a close above the previous bar's high), or *VZO is above VZO 3 bars ago*. The rule form only offers the
settings that change a study's values (its length…), not how it's drawn.

**True when.** How the conditions (and other rules) combine, typed or built in groups; both stay in step:

| Write | Means |
| --- | --- |
| `A AND B`, `A && B`, `A & B` | both |
| `A OR B`, `A \|\| B`, `A \| B` | either |
| `NOT A`, `!A` | not |
| `( … )` | grouping, nested as deep as you like |
| `WITHIN 3 A` | A was true on one of the last 3 bars (this one included) |
| `Trend`, `"Rule 1"` | another saved rule, by name (in quotes if the name has spaces, or is one capital letter) |

So `(A OR B) AND NOT (C OR (D AND E))` and `"Above VWAP" AND NOT ("Rule 3" OR WITHIN 5 A)` are both rules. NOT and
WITHIN bind tightest, then AND, then OR, so `A OR B AND C` is `A OR (B AND C)`; the form always writes the brackets.
A new rule is true when all its conditions are (`A AND B AND …`) until you change that. In the groups, each box is
**All of these (AND)** or **Any of these (OR)**; each part can be **NOT**, and **within N bars**; **+ group** nests
one box inside another.

As you type, the expression is checked and a mistake says where (`Expected ')', found the end (at character 9)`).
A rule can't use itself, directly or through other rules. Renaming a rule renames it in every rule and strategy
that uses it; a rule that something uses can't be deleted until that's changed.

**Levels** come from the level studies, by name: **Session levels** (OR high, OR low, PM high, PM low, HOD, LOD, POC,
VAH, VAL, with the opening range's length), **Prior day** (PH, PL, PC, PO, PW high, PW low), **Initial balance** (IB
high, IB low, IB mid), **Support / resistance** (Pivot, R1, R2, S1, S2), **ATR levels**, **Daily range meter**,
**Volume profile** and **TPO**. Each bar reads the level as it was when the bar started, and only once it's
finished: the 15-minute opening range high exists from 09:45, and *Close crosses above HOD* means the bar closed
above the high of the day before it. Levels count in regular hours only. A level is worked out for the rule even if
the study's defaults hide it on the charts. A study whose past values change as new bars arrive is refused: trading
on it would look ahead.

## Strategies

A **strategy** trades on rules. Write strategies on the Config page, **Paper strategies**:

- **Buy if**, **Sell short if**, **Close a long if**, **Close a short if**: each an expression of saved rules, with
  the same AND, OR, NOT, brackets and WITHIN, e.g. **Buy if** `("Rule 1" AND NOT "Rule 3") OR Rule5`. Leave Sell short
  if blank to only buy; leave the Close ones blank to leave a trade only by its stop, target or the end of the day.
  Conditions themselves live in rules: a strategy uses rules by name.
- **Bars**: the timeframe its rules are read on (1, 2, 3, 5 or 15 minutes).
- **Shares**, the **entry order** (market, a limit or stop a distance from the close, or at a study line or level),
  the **exits** (a stop, target or trailing distance from the signal bar's close, and reversing on the opposite
  signal) and the **hours** new trades may start.

A backtest keeps what the rules said when it ran, so changing a rule later doesn't change an old report.

Rules from before strategies were added are upgraded when the server starts: each one's long, short and exit
conditions become rules (*Rule 1 long*, *Rule 1 short*, *Rule 1 exit long*…), and a strategy of the old name trades
on them, with the same results.

## The Paper page

**Paper trading** in the pages menu (address `/paper`) has two sections:

- **Trades**: an account's trades since its last reset, from Replay practice and from saved backtests. Filter by
  symbol and day; see the totals and the equity after each session; write a note on any trade; **Open on the chart**
  opens the default dashboard's first chart at that day, just after the entry, practising in that account.
- **Backtests**: run a saved strategy on a symbol's cached days, with an account's cash and costs. The form starts with
  the defaults set in Config, **Backtests** (symbol, account, random runs, skipping days without bars). It runs in
  the background (you can leave the page). The report has the trades, the equity by day, win rate, average win and
  loss, profit factor, the largest drawdown, trades a day and longs and shorts apart, next to **random entries with
  the same exits** (several runs): a strategy that doesn't beat them has no edge. Days without cached bars stop the run,
  or are skipped if you tick that. Entry signals the account can't afford are skipped, and the report says how
  many. Tick runs to **compare** them side by side; **Save** puts a run's trades into an account, as sessions that
  open on a chart and fill the same.

### A run's report

A run shows as soon as it starts, with its progress, and fills in when it's done. Below the numbers, two tabs:

- **Trades**: each trade. **Click its day** to see that day on a chart, over the page: the trades' entries and exits
  as **arrows** (green up for a buy, red down for a sell or cover, labelled with the trade's number, price, why it
  left and its P/L), at the strategy's timeframe, with the studies its rules read (an opening range rule shows
  Session levels with its opening range). Add studies there with **f(x)** to see what would make the rule better;
  they stay for the next day you look at, while the rules' own studies follow the run. **Open in a new tab** keeps
  the chart; Esc or × closes it. Then change the rules in Config and run again. These arrows are the backtest's own
  trades: they appear only on this review chart, never on the dashboards' charts.
- **Log**: what the run did, day by day, live while it runs: each signal it acted on and the order it placed, each
  fill and why (stop, target, market), entries the account couldn't afford, signals not taken (while in a trade,
  outside the hours, against a trade it doesn't reverse), and a line a day with its trades, P/L and cash. **Show**
  narrows it to a line a day, or to what was refused and skipped. Click a day to see it on a chart.

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
- **Study lines** use the study's value at the close of the previous bar; **levels**, the level as it was before
  the bar.
- **A bracket's exits** start working on the bar after the entry fills.
- **Commissions**: IBKR Fixed by default: $0.005 a share, at least $1.00, at most 1% of the trade's value.

## Limits

- Stocks and ETFs only; options aren't simulated.
- An order fills in full when its price trades: no queue position, partial fills or order book.
- No margin: a position, long or short, may be worth at most the account's equity. No borrow fees or short-sale
  restrictions.
- Each chart's practice session is one symbol on one day, starting with the account's balance; sessions on several
  charts at once don't share buying power.
- Synthetic (`-DEMO`) symbols are labelled as such in the strip.
