"""Market internals: -VIX derived from VIX, ADD/VOLD recorded from live quotes, the collector's handling of both,
the mixed "2 over 4" layout's data, and the chart view on these symbols."""
import pandas as pd
import pytest

import fake_tws
import recorder
from app import control, engine, store
from test_collector import Clock, drain, make

ET = "America/New_York"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return tmp_path


def bars(day, values):
    t = pd.date_range(f"{day} 09:30", periods=len(values), freq="1min", tz=ET)
    return pd.DataFrame({"time": t, "open": values, "high": [v + 1 for v in values], "low": [v - 1 for v in values],
                         "close": values, "volume": 0.0})


# ---------------------------------------------------------------- -VIX
def test_minus_vix_is_vix_upside_down(cache):
    store.write_day("VIX", "2026-10-16", bars("2026-10-16", [17.0, 18.0, 16.5]))
    store.write_daily("VIX", pd.DataFrame({"date": ["2026-10-15"], "open": [17.0], "high": [19.0], "low": [16.0],
                                           "close": [18.0], "volume": [0.0]}))
    inv = store.read_day("-VIX", "2026-10-16")
    assert list(inv["close"]) == [-17.0, -18.0, -16.5]
    assert list(inv["high"]) == [-16.0, -17.0, -15.5] and list(inv["low"]) == [-18.0, -19.0, -17.5]
    assert (inv["high"] >= inv["low"]).all()
    assert store.list_days("-VIX") == ["2026-10-16"] and "-VIX" in store.list_symbols()
    assert store.read_daily("-VIX")[["high", "low", "close"]].values.tolist() == [[-16.0, -19.0, -18.0]]
    with pytest.raises(ValueError):
        store.write_day("-VIX", "2026-10-16", inv)


def test_symbol_rules():
    assert [control.clean_symbol(s) for s in ("-vix", "add-nyse", "VOLD-NYSE", "VOL-NYSE", "-QQQ")] == \
        ["-VIX", "ADD-NYSE", "VOLD-NYSE", "VOL-NYSE", None]
    assert control.fetchable("-VIX") == "VIX" and control.fetchable("ADD-NYSE") is None and control.fetchable("QQQ") == "QQQ"
    assert all(control.is_index(s) for s in ("VIX", "-VIX", "ADD-NYSE", "TICK-NYSE")) and not control.is_index("QQQ")


# ---------------------------------------------------------------- recording ADD / VOLD
class Ticker:
    def __init__(self, contract):
        self.contract, self.bid, self.ask = contract, float("nan"), float("nan")


class QuoteIB:
    def __init__(self):
        self.tickers = {}

    def reqMktData(self, contract, *a):
        self.tickers[contract.symbol] = Ticker(contract)
        return self.tickers[contract.symbol]

    def cancelMktData(self, contract):
        self.tickers.pop(contract.symbol, None)


def test_recorder_builds_minute_bars_from_bid_minus_ask(cache):
    ib, clock = QuoteIB(), Clock("2026-10-20 09:30:05")
    rec = recorder.Recorder(ib, ["ADD-NYSE", "VOLD-NYSE"], fake_tws.qualify, write_every=5, clock=clock.monotonic)
    rec.sync(clock.now())
    assert set(ib.tickers) == {"AD-NYSE", "VOL-NYSE"}
    quotes = [(1500, 1400), (1600, 1300), (1450, 1500), (1700, 1200)]          # advancing, declining
    for bid, ask in quotes:                                                       # four samples in the 09:30 minute
        ib.tickers["AD-NYSE"].bid, ib.tickers["AD-NYSE"].ask = bid, ask
        ib.tickers["VOL-NYSE"].bid, ib.tickers["VOL-NYSE"].ask = bid * 1e6, ask * 1e6
        clock.advance(10)
        rec.sync(clock.now())
    ib.tickers["AD-NYSE"].bid = -1                                                # "no value": skipped
    clock.advance(30)
    rec.sync(clock.now())
    rec.flush()
    add = store.read_day("ADD-NYSE", "2026-10-20")
    assert add[["open", "high", "low", "close"]].values.tolist() == [[100.0, 500.0, -50.0, 500.0]]
    assert store.read_day("VOLD-NYSE", "2026-10-20")["close"].tolist() == [5e8, 5e8]     # 09:30, and the 09:31 sample


def test_recorder_keeps_the_morning_after_a_restart_and_only_runs_in_regular_hours(cache):
    store.write_day("ADD-NYSE", "2026-10-20", bars("2026-10-20", [10.0, 20.0]))   # 09:30, 09:31 from before
    ib, clock = QuoteIB(), Clock("2026-10-20 09:32:00")
    rec = recorder.Recorder(ib, ["ADD-NYSE"], fake_tws.qualify, write_every=0, clock=clock.monotonic)
    rec.sync(clock.now())
    ib.tickers["AD-NYSE"].bid, ib.tickers["AD-NYSE"].ask = 900, 600
    clock.advance(1)
    rec.sync(clock.now())
    assert store.read_day("ADD-NYSE", "2026-10-20")["close"].tolist() == [10.0, 20.0, 300.0]
    late = Clock("2026-10-20 16:05")
    rec.sync(late.now())
    assert ib.tickers == {}                                                       # unsubscribed after the close
    early = recorder.Recorder(QuoteIB(), ["ADD-NYSE"], fake_tws.qualify)
    early.sync(pd.Timestamp("2026-10-20 08:00", tz=ET))
    assert early.tickers == {}


def test_an_indicator_that_cant_be_had_is_skipped_not_fatal(cache):
    """TWS crash of 2026-10-27: an unqualified contract made reqMktData raise and the collector restart in a loop."""
    ib, clock = fake_tws.FakeIB(now=lambda: pd.Timestamp("2026-10-20 10:00", tz=ET)), Clock("2026-10-20 10:00")
    unqualified = recorder.Recorder(ib, ["ADD-NYSE"], fake_tws.Contract, clock=clock.monotonic)    # no conId
    unqualified.sync(clock.now())
    assert unqualified.tickers == {} and "conId" in unqualified.failed["ADD-NYSE"]
    unqualified.sync(clock.now())                                                  # not retried every pass
    missing = recorder.Recorder(ib, ["ADD-NYSE", "VOLD-NYSE"], lambda name: None if name == "AD-NYSE" else fake_tws.qualify(name),
                                clock=clock.monotonic)
    missing.sync(clock.now())
    assert list(missing.tickers) == ["VOLD-NYSE"] and "no AD-NYSE contract" in missing.failed["ADD-NYSE"]


# ---------------------------------------------------------------- the collector
def test_collector_fetches_vix_for_minus_vix_and_nothing_for_recorded(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=True, record=[])
    control.submit(["-VIX", "ADD-NYSE"], day="2026-10-16")
    drain(col, clock)
    asked = {r[0] for r in ib.requests}
    assert "VIX" in asked and "-VIX" not in asked and "ADD-NYSE" not in asked and "AD-NYSE" not in asked
    assert "TICK-NYSE" not in asked                                                # indexes don't pull in the companions
    assert store.list_days("-VIX") == store.list_days("VIX") != []


def test_collector_records_in_live_mode(cache):
    clock = Clock("2026-10-20 10:00")
    ib, col = make(cache, clock, live=True, record=["ADD-NYSE", "VOLD-NYSE"])
    for _ in range(40):
        col.step()
        clock.advance(5)
    assert control.read_status()["recording"] == ["ADD-NYSE", "VOLD-NYSE"]
    assert control.read_status()["not_recording"] == {}
    assert all(t.contract.conId for t in ib.tickers)                               # subscribed with qualified contracts
    col.close()
    add, vold = store.read_day("ADD-NYSE", "2026-10-20"), store.read_day("VOLD-NYSE", "2026-10-20")
    assert len(add) >= 3 and len(vold) >= 3
    assert abs(vold["close"].iloc[-1]) > 1e6                                      # volumes, in shares
    assert not ib.tickers                                                         # closed: unsubscribed


def test_chart_view_on_internals(cache):
    import synthetic
    synthetic.generate(cache)
    for sym, studies in (("-VIX", ["ma_cloud", "bollinger"]), ("ADD-NYSE", ["ma_cloud", "bollinger"]),
                         ("VOLD-NYSE", ["ema"]), ("TICK-NYSE", ["session_levels"])):
        v = engine.build_view(sym, "2026-10-16", tf=3, cursor=700, days=2,
                              studies=[{"uid": s, "type": s, "params": {}} for s in studies])
        assert v["bars"] and all(r["ok"] for r in v["studies"].values()), sym
    v = engine.build_view("-VIX", "2026-10-16", tf=2)
    assert all(b["close"] < 0 for b in v["bars"])


def test_connect_is_read_only_and_skips_the_account(monkeypatch):
    """The chart collector never needs positions, orders or executions, so TWS isn't asked for them."""
    import ib_async
    from ib_async.ib import StartupFetchNONE
    from argparse import Namespace
    import fetch_ibkr
    seen = {}
    monkeypatch.setattr(ib_async.IB, "connect", lambda self, *a, **kw: seen.update(kw))
    fetch_ibkr.connect(Namespace(host="h", port=7496, client_id=17))
    assert seen["readonly"] is True and seen["fetchFields"] == StartupFetchNONE
