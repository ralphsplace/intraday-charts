"""Strategies from inline conditions, for tests: each list of conditions becomes an unsaved rule, as Config would
save it, and the strategy trades on them (app/paper/rules.py, strategies.py)."""
from app.paper import rules, strategies

PARTS = (("buy", "long"), ("short", "short"), ("exit_long", "exit_long"), ("exit_short", "exit_short"))


def strategy(long=(), short=(), exit_long=(), exit_short=(), within=1, **kw) -> dict:
    """A prepared strategy (what a backtest runs). within > 1: every condition on one of the last n bars, as the
    rules from before #67 read their entry conditions."""
    saved, st = {}, {}
    for (key, name), conds in zip(PARTS, (long, short, exit_long, exit_short), strict=True):
        if not conds:
            continue
        letters = [chr(65 + i) for i in range(len(conds))]
        when = " AND ".join(letters)
        if within > 1 and key in ("buy", "short") and len(letters) > 1:
            when = " AND ".join(f"WITHIN {within} {x}" for x in letters) + " AND (" + " OR ".join(letters) + ")"
        saved[name] = rules.check({"conditions": list(conds), "when": when}, saved, name)
        st[key] = name
    return strategies.prepare({**st, **kw}, saved)
