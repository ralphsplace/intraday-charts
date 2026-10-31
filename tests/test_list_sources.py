"""Watch lists from outside sources (FinViz): checking and normalizing addresses, the collector's fetcher (against
hand-written answers in FinViz's export format, no network), the collector's requests, and the endpoint."""
import io
import json
import time
import urllib.error

import pytest
from fastapi.testclient import TestClient

import list_sources as fetchers
from app import control, envcheck, list_sources, store
from test_collector import Clock, drain, make

SCREEN = "https://elite.finviz.com/screener.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers&o=-change&auth=SECRET-TOKEN"
CSV = ('﻿"No.","Ticker","Company","Sector","Price","Change","Volume"\r\n'
       '"1","NVDA","NVIDIA Corp","Technology","201.10","4.12%","312000000"\r\n'
       '"2","AMD","Advanced Micro Devices","Technology","160.20","3.50%","61000000"\r\n'
       '"3","BRK-B","Berkshire Hathaway","Financial","480.00","2.00%","3000000"\r\n')


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------- addresses
def test_screens_and_portfolios_are_normalized_and_the_token_dropped():
    ref = list_sources.normalize("finviz", SCREEN)
    assert ref == {"source": "finviz", "kind": "screener", "query": "v=111&f=sh_avgvol_o2000,ta_topgainers&o=-change"}
    assert list_sources.address(ref) == "https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers&o=-change"
    assert list_sources.normalize("finviz", "https://finviz.com/screener.ashx?f=ta_topgainers&v=111") == \
        list_sources.normalize("finviz", "https://finviz.com/export.ashx?v=111&f=ta_topgainers&ft=4")   # same list
    port = list_sources.normalize("finviz", "finviz.com/portfolio.ashx?v=1&pid=1234567")
    assert port == {"source": "finviz", "kind": "portfolio", "query": "pid=1234567"}
    assert list_sources.normalize("finviz", "f=cap_large,ta_topgainers")["query"] == "f=cap_large,ta_topgainers"
    assert list_sources.FinViz.label(ref).startswith("FinViz screen: sh_avgvol_o2000")
    assert list_sources.FinViz.label(port) == "FinViz portfolio 1234567"
    assert list_sources.valid(ref) and list_sources.valid(port)


@pytest.mark.parametrize("bad", [
    "", "QQQ SPY", "https://example.com/screener.ashx?f=ta_topgainers", "https://finviz.com.evil.net/screener.ashx?f=x",
    "file:///etc/passwd", "https://finviz.com/quote.ashx?t=AAPL", "https://finviz.com/screener.ashx?v=111",
    "https://finviz.com/portfolio.ashx?v=1", "https://finviz.com/portfolio.ashx?pid=12a",
    "https://finviz.com/screener.ashx?f=ta_topgainers%26auth%3Dx", "https://finviz.com/screener.ashx?f=a b",
])
def test_anything_else_is_refused(bad):
    with pytest.raises(ValueError):
        list_sources.normalize("finviz", bad)


def test_references_from_elsewhere_are_checked_again():
    ref = list_sources.normalize("finviz", SCREEN)
    assert not list_sources.valid({**ref, "query": ref["query"] + "&auth=x"})
    assert not list_sources.valid({**ref, "kind": "news"})
    assert not list_sources.valid({**ref, "source": "other"})
    assert not list_sources.valid("finviz")
    with pytest.raises(ValueError):
        list_sources.normalize("other", SCREEN)


# ---------------------------------------------------------------- the collector's fetcher
class Answer:
    def __init__(self, body=b"", error=None):
        self.body, self.error, self.urls = body, error, []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.body


def test_finviz_export_reads_the_ticker_column():
    ans = Answer(CSV.encode())
    f = fetchers.FinVizExport("TOKEN", fetch=ans)
    res = f.load(list_sources.normalize("finviz", SCREEN))
    assert res == {"status": "ok", "symbols": ["NVDA", "AMD"], "total": 2, "skipped": ["BRK-B"]}
    assert ans.urls == ["https://elite.finviz.com/export.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers&o=-change&auth=TOKEN"]
    f.load(list_sources.normalize("finviz", "https://finviz.com/portfolio.ashx?v=1&pid=42"))
    assert ans.urls[-1] == "https://elite.finviz.com/portfolio_export.ashx?pid=42&auth=TOKEN"


@pytest.mark.parametrize("answer, says", [
    (Answer(b"<!DOCTYPE html><html>Sign in</html>"), "web page instead of a list"),
    (Answer(b"a,b\n1,2\n"), "no Ticker column"),
    (Answer(error=urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO())), "refused the token"),
    (Answer(error=urllib.error.HTTPError("u", 429, "slow", {}, io.BytesIO())), "limiting requests"),
    (Answer(error=urllib.error.URLError("no network")), "Couldn't reach FinViz"),
])
def test_finviz_failures_say_why(answer, says):
    res = fetchers.FinVizExport("x7Q-not-real", fetch=answer).load(list_sources.normalize("finviz", SCREEN))
    assert res["status"] == "error" and says in res["message"] and "x7Q" not in res["message"]


def test_an_unchecked_reference_is_never_fetched():
    ans = Answer(CSV.encode())
    res = fetchers.FinVizExport("TOKEN", fetch=ans).load({"source": "finviz", "kind": "screener", "query": "f=x&auth=y"})
    assert res["status"] == "error" and ans.urls == []
    assert fetchers.make_fetchers("") == {} and fetchers.make_fetchers(None) == {}
    assert set(fetchers.make_fetchers("T")) == {"finviz"}


# ---------------------------------------------------------------- the collector
def test_the_collector_fetches_a_list_and_keeps_no_token(cache, monkeypatch):
    clock = Clock("2026-10-20 10:00")
    ib, col = make(cache, clock, live=True)
    ans = Answer(CSV.encode())
    col.list_fetchers = {"finviz": fetchers.FinVizExport("SECRET-TOKEN", fetch=ans)}
    ref = list_sources.normalize("finviz", SCREEN)
    control.submit_list(ref)
    drain(col, clock)
    assert len(ans.urls) == 1
    got = list_sources.read(ref)
    assert got["symbols"] == ["NVDA", "AMD"] and got["ref"] == ref and got["fetched"] > 0
    assert not any("SECRET-TOKEN" in p.read_text() for p in cache.rglob("*.json"))
    control.submit_list({**ref, "query": "f=x&auth=y"})            # tampered: ignored
    drain(col, clock)
    assert len(ans.urls) == 1


def test_without_a_token_the_collector_says_lists_are_off(cache, monkeypatch):
    monkeypatch.delenv("FINVIZ_TOKEN", raising=False)
    clock = Clock("2026-10-20 10:00")
    ib, col = make(cache, clock, live=True)
    assert col.list_fetchers == {}
    ref = list_sources.normalize("finviz", SCREEN)
    control.submit_list(ref)
    drain(col, clock)
    assert list_sources.read(ref)["status"] == "off"


# ---------------------------------------------------------------- the endpoint
@pytest.fixture
def client(cache, monkeypatch):
    monkeypatch.delenv("FINVIZ", raising=False)
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_list_source_endpoint(client, cache, monkeypatch):
    body = {"source": "finviz", "address": SCREEN}
    v = client.post("/api/lists/source", json=body).json()
    assert v["status"] == "off" and not v["requested"] and control.pending_requests() == []
    assert "SECRET" not in json.dumps(v)
    monkeypatch.setenv("FINVIZ", "on")
    v = client.post("/api/lists/source", json=body).json()
    assert v["status"] == "missing" and v["requested"]
    assert control.pending_requests()[-1]["list"] == v["ref"]
    n = len(control.pending_requests())
    assert not client.post("/api/lists/source", json={**body, "ask": False}).json()["requested"]   # just looking
    assert len(control.pending_requests()) == n
    list_sources.write(v["ref"], {"status": "ok", "symbols": ["NVDA"], "total": 1, "fetched": time.time()})
    v = client.post("/api/lists/source", json=body).json()
    assert (v["status"], v["symbols"], v["requested"], v["stale"]) == ("ok", ["NVDA"], False, False)
    assert client.post("/api/lists/source", json={**body, "refresh": True}).json()["requested"]
    list_sources.write(v["ref"], {"status": "ok", "symbols": ["NVDA"], "fetched": time.time() - list_sources.STALE_SECONDS - 5})
    assert client.post("/api/lists/source", json=body).json()["requested"]            # due again
    r = client.post("/api/lists/source", json={**body, "address": "https://example.com/screener.ashx?f=x"})
    assert r.status_code == 400 and "finviz.com" in r.json()["detail"]
    assert client.post("/api/lists/source", json={**body, "source": "other"}).status_code == 400


def test_the_environment_check_says_whether_finviz_lists_are_on(monkeypatch):
    monkeypatch.delenv("FINVIZ", raising=False)
    net = next(c for c in envcheck.run() if c["name"] == "Internet access")
    assert "FinViz watch lists are off" in net["detail"]
    monkeypatch.setenv("FINVIZ", "on")
    net = next(c for c in envcheck.run() if c["name"] == "Internet access")
    assert "finviz.com" in net["detail"]
