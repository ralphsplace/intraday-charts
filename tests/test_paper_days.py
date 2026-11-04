"""A backtest's days worked on at the same time (app/paper/days.py, backtest.run with a pool): the same report as one
day after another, even when the cash the days before leave changes what the account can buy; a limit on how many
days are worked on at once, shared by every run; and a stopped run hands out no more days."""
import os
import threading

import pytest

from app import store
from app.paper import backtest, days, engine
from test_paper_backtest import cross_rule

FREE = {"commission": {"per_share": 0.005, "minimum": 1, "max_pct": 1}, "slippage": 0.01}


@pytest.fixture(scope="module")
def pool():
    p = days.DayPool(limit=lambda: 2)
    yield p
    p.close()


def both(rule, cash, pool, baseline_runs=1):
    """The run one day after another, and with its days in the pool: (report, log) each."""
    out = []
    for p in (None, pool):
        lines, seen = [], []
        rep = backtest.run(rule, "QQQ-DEMO", store.list_days("QQQ-DEMO")[:8], cash, FREE, baseline_runs=baseline_runs,
                           log=lambda d, text, level="info", lines=lines: lines.append((d, text, level)), pool=p,
                           on_day=lambda d, what, pnl=None, seen=seen: seen.append((d, what)))
        out.append((rep, lines, seen))
    return out


def test_the_engine_says_how_far_the_cash_could_be_off():
    st = engine.new_state(1000, FREE)
    engine.place(st, {"side": "buy", "qty": 10, "type": "market"}, 600, 90.0)
    assert st["headroom"] == {"spare": pytest.approx(100, abs=1e-6), "short": None}
    with pytest.raises(engine.PaperError, match="buying power"):
        engine.place(st, {"side": "buy", "qty": 20, "type": "market"}, 601, 90.0)   # not filled yet: 20 shares, $1,800
    assert st["headroom"]["short"] == pytest.approx(800, abs=1e-6)


def test_a_day_fits_another_starting_cash_only_if_every_check_would_decide_the_same():
    c = {"cash_from": 1000.0, "skipped": [], "headroom": {"spare": 100.0, "short": None}}
    assert backtest.fits(c, 1000) and backtest.fits(c, 950) and backtest.fits(c, 50_000)
    assert not backtest.fits(c, 899)                                   # an entry would have been refused
    assert backtest.fits({**c, "headroom": {"spare": None, "short": None}}, 1)      # it bought nothing
    refused = {**c, "skipped": ["Not enough buying power …"]}
    assert backtest.fits(refused, 1000) and not backtest.fits(refused, 1000.5)  # the refusal says the cash


def test_days_in_the_pool_make_the_same_report_as_one_after_another(demo, pool):
    (seq, seq_log, seq_seen), (par, par_log, par_seen) = both(cross_rule(), 100_000, pool)
    assert par == seq and par["trades"] and par["baseline"]["trades"]
    assert par_log == seq_log                                           # in day order, whatever order the days finished in
    assert [d for d, w in par_seen if w == "done"] == par["days"] == [d for d, w in seq_seen if w == "done"]
    assert {d for d, w in par_seen if w == "running"} == set(par["days"]) == {d for d, w in par_seen if w == "worked"}
    going, most = set(), 0                                              # never more days going than the limit (2)
    for d, w in par_seen:
        going = going | {d} if w == "running" else going - {d}
        most = max(most, len(going))
    assert most == 2


@pytest.mark.parametrize("cash", [69_500, 70_000, 70_500, 71_000])
def test_days_the_cash_before_them_changes_are_worked_out_again(demo, pool, cash):
    """100 shares at about $700: the account's whole cash, so the days before decide which entries go in."""
    (seq, seq_log, _), (par, par_log, _) = both(cross_rule(qty=100), cash, pool, baseline_runs=0)
    assert par == seq and par["skipped"]["count"] and par["trades"]               # some went in, some were refused
    again = [x for x in par_log if x[1].startswith("worked out again")]
    assert [x for x in par_log if x not in again] == seq_log
    worked_again[cash] = len(again)


worked_again: dict = {}


def test_some_days_were_worked_out_again():
    assert sum(worked_again.values()) >= 1, worked_again        # the check above isn't vacuous


def test_the_limit_is_shared_and_read_as_days_are_handed_out(demo):
    limit = [1]
    p = days.DayPool(limit=lambda: limit[0])
    try:
        rule, have = cross_rule(), store.list_days("QQQ-DEMO")[:6]
        busiest = [0]

        def started(_day):
            busiest[0] = max(busiest[0], p._busy)

        def one_run(out):
            args = [(rule, "QQQ-DEMO", d, 100_000, FREE, 0, 1, 100_000) for d in have]
            out.extend(r["day"] for r in p.in_order(backtest.day_chunk, args, lambda: None, started))
        a, b = [], []
        threads = [threading.Thread(target=one_run, args=(x,)) for x in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        assert a == b == have and busiest[0] == 1                       # two runs, one day at a time in all
        limit[0] = 3
        busiest[0] = 0
        one_run([])
        assert busiest[0] == 3
        assert p._busy == 0
    finally:
        p.close()


def test_a_stopped_run_hands_out_no_more_days(demo, pool):
    rule, have = cross_rule(), store.list_days("QQQ-DEMO")[:8]
    started, got, at_stop = [], [], []

    def check():
        if got:
            at_stop.append(len(started))
            raise RuntimeError("stopped")
    args = [(rule, "QQQ-DEMO", d, 100_000, FREE, 0, 1, 100_000) for d in have]
    with pytest.raises(RuntimeError, match="stopped"):
        for r in pool.in_order(backtest.day_chunk, args, check, started.append):
            got.append(r)
    assert len(got) == 1 and len(started) == at_stop[0] < len(have)    # nothing handed out once it was stopped
    for _ in range(200):
        if pool._busy == 0:
            break
        threading.Event().wait(0.05)
    assert pool._busy == 0


def test_a_worker_process_that_dies_fails_its_run_and_the_next_runs_work(demo):
    p = days.DayPool(limit=lambda: 2)
    try:
        with pytest.raises(RuntimeError, match="stopped unexpectedly"):
            list(p.in_order(os._exit, [(1,)], lambda: None))           # the process ends mid-day, as if killed
        args = [(cross_rule(), "QQQ-DEMO", d, 100_000, FREE, 0, 1, 100_000) for d in store.list_days("QQQ-DEMO")[:2]]
        assert [r["day"] for r in p.in_order(backtest.day_chunk, args, lambda: None)] == store.list_days("QQQ-DEMO")[:2]
        assert p._busy == 0
    finally:
        p.close()
