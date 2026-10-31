"""Named watch lists, app-wide on the NAS: default names, unique names, renames that keep the id, the three
sources, lists saved before ids existed, Load data's saves, the endpoints; and thinkorswim links explained."""
import json

import pytest
from fastapi.testclient import TestClient

from app import saved, store, watchlist, watchlists


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_default_names_count_up_and_names_are_unique(cache):
    a, _ = watchlists.create("symbols", {"symbols": ["QQQ"]})
    b, _ = watchlists.create("holdings")
    assert (a, b) == ("Watch list 1", "Watch list 2")
    watchlists.rename("Watch list 1", "Index ETFs")
    assert watchlists.create("symbols")[0] == "Watch list 3"                    # one more than the highest in use
    with pytest.raises(ValueError, match="already"):
        watchlists.create("symbols", name="Index ETFs")
    with pytest.raises(ValueError, match="already"):
        watchlists.rename("Watch list 2", "Index ETFs")
    with pytest.raises(ValueError):
        watchlists.rename("Watch list 2", "a/b")
    with pytest.raises(KeyError):
        watchlists.rename("nope", "x")
    assert watchlists.next_name(["Watch list 9", "Watch list x", "Other"]) == "Watch list 10"


def test_a_rename_keeps_the_id_and_contents(cache):
    _, item = watchlists.create("finviz", {"feed": {"address": "https://finviz.com/screener.ashx?f=ta_topgainers", "label": "x"}})
    watchlists.rename("Watch list 1", "Gainers")
    got = watchlists.all_lists()
    assert list(got) == ["Gainers"] and got["Gainers"]["id"] == item["id"] and got["Gainers"]["source"] == "finviz"
    watchlists.update("Gainers", "symbols", {"symbols": ["NVDA"]})
    assert watchlists.all_lists()["Gainers"] == {"id": item["id"], "source": "symbols", "symbols": ["NVDA"]}


def test_lists_saved_before_ids_move_into_the_config_with_ids(cache):
    saved.put("watchlists", "Old", ["QQQ", "SPY"])                               # the file before the config existed
    got = watchlists.all_lists()["Old"]
    assert got["id"] and got["symbols"] == ["QQQ", "SPY"]                         # an id on the first read
    assert json.loads((cache / "user" / "config.json").read_text())["watchlists"]["Old"]["id"] == got["id"]
    watchlists.rename("Old", "Older")
    assert watchlists.all_lists()["Older"]["id"] == got["id"] and "Old" not in watchlists.all_lists()   # a move
    _, item = watchlists.create("symbols", {"symbols": ["A"]}, name="Mine")
    watchlists.set_symbols("Mine", ["B", "C"])                                    # Load data's Save keeps the id
    assert watchlists.all_lists()["Mine"] == {"id": item["id"], "source": "symbols", "symbols": ["B", "C"]}
    for bad in (("nope", {}), ("finviz", {}), ("symbols", {"symbols": "QQQ"})):
        with pytest.raises(ValueError):
            watchlists.create(*bad)


@pytest.fixture
def client(cache):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_endpoints(client, cache):
    r = client.post("/api/watchlists", json={"source": "symbols", "symbols": ["QQQ"]}).json()
    assert r["name"] == "Watch list 1" and r["lists"]["Watch list 1"]["symbols"] == ["QQQ"]
    assert client.post("/api/watchlists", json={"source": "symbols", "name": "Watch list 1"}).status_code == 409
    assert client.put("/api/watchlists/Watch list 1", json={"source": "symbols", "symbols": ["SPY"]}).json()["item"]["symbols"] == ["SPY"]
    assert client.put("/api/watchlists/nope", json={"source": "symbols"}).status_code == 404
    r = client.post("/api/watchlists/Watch list 1/rename", json={"to": "  Mine "}).json()
    assert r["name"] == "Mine" and "Mine" in client.get("/api/watchlists").json()
    assert client.post("/api/watchlists", json={"source": "holdings"}).json()["name"] == "Watch list 1"   # free again
    assert client.post("/api/watchlists/Mine/rename", json={"to": "Watch list 1"}).status_code == 409
    assert client.post("/api/watchlists/nope/rename", json={"to": "x"}).status_code == 404
    # Load data still saves and reads plain symbol lists under the same names
    assert client.put("/api/saved/watchlists/Mine", json=["NVDA"]).status_code == 200
    assert json.loads((cache / "user" / "config.json").read_text())["watchlists"]["Mine"]["symbols"] == ["NVDA"]
    assert client.put("/api/saved/watchlists/Mine", json={"x": 1}).status_code == 400
    assert "Mine" not in client.delete("/api/watchlists/Mine").json()["lists"]


def test_thinkorswim_links_and_web_addresses_are_not_symbols():
    r = watchlist.parse_symbols("HTTP://TOS.MX/!FDKFI2MJ")
    assert r["symbols"] == [] and "can't be read" in r["note"]
    r = watchlist.parse_symbols("QQQ https://example.com/list SPY www.foo.com/a")
    assert r == {"symbols": ["QQQ", "SPY"], "skipped": []}
