"""The application config (data/user/config.json): study defaults that new studies and the server use, each
watch list type's default columns, the Config page's endpoints, and edits that are safe and checked."""
import json

import pytest
from fastapi.testclient import TestClient

import synthetic
from app import app_config, engine, store, studies, study_values, watch_fields


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(cache):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_sections_are_read_fresh_after_a_change(cache):
    assert app_config.section("studies") == {} and app_config.section("watchlists") == {}
    app_config.put_section("studies", {"sma": {"length": 21}})
    assert app_config.section("studies") == {"sma": {"length": 21}}
    with app_config.editing() as d:
        d["studies"]["ema"] = {"length": 8}
    assert set(app_config.section("studies")) == {"sma", "ema"}
    with pytest.raises(KeyError):
        app_config.section("nope")


def test_study_defaults_feed_the_catalog_and_the_server(cache, client):
    r = client.put("/api/config/studies/sma", json={"length": 21, "sma_color": "#ff0000", "bogus": 1, "source": "close"}).json()
    assert r["customized"] == ["length", "sma_color"]                       # only known keys that differ from built-in
    p = {x["key"]: x for x in r["params"]}
    assert p["length"]["default"] == 21 and p["length"]["factory"] == 50 and p["sma_color"]["default"] == "#ff0000"
    assert json.loads((cache / "user" / "config.json").read_text())["studies"] == {"sma": {"length": 21, "sma_color": "#ff0000"}}
    cat = {s["type"]: s for s in client.get("/api/studies").json()["studies"]}
    assert {x["key"]: x["default"] for x in cat["sma"]["params"]}["length"] == 21          # new studies start there
    assert client.put("/api/config/studies/sma", json={"length": 99999}).json()["params"][0]["default"] == 500   # clamped
    assert studies.base.effective_params("sma", {})["length"] == 500
    assert studies.base.effective_params("sma", {"length": 9})["length"] == 9               # a chart's own setting wins
    client.delete("/api/config/studies/sma")
    assert studies.base.effective_params("sma", {})["length"] == 50
    assert client.put("/api/config/studies/nope", json={}).status_code == 404
    client.put("/api/config/studies/sma", json={"length": 50})                          # the same as built-in: nothing kept
    assert app_config.section("studies") == {}


def test_a_study_run_on_the_server_uses_the_defaults(cache, client):
    synthetic.generate(cache)
    day = store.list_days("QQQ-DEMO")[-1]
    before = study_values.value("QQQ-DEMO", day, {"type": "sma", "output": "sma", "tf": 5})["value"]
    client.put("/api/config/studies/sma", json={"length": 20})
    after = study_values.value("QQQ-DEMO", day, {"type": "sma", "output": "sma", "tf": 5})["value"]
    ctx = engine.DayContext("QQQ-DEMO", day, 5)
    sma20 = studies.run_study(ctx, "sma", {"length": 20})["lines"][0]["data"][-1]["value"]
    assert after == pytest.approx(sma20) and after != before


def test_watch_columns_per_list_kind(cache, client):
    cat = client.get("/api/watch/columns").json()
    assert cat["defaults"] == cat["factory"] and set(cat["defaults"]) == {"quote", "finviz", "holding"}
    r = client.put("/api/config/watch-columns/quote", json=["gap_pct", "last", "symbol", "gap_pct", "qty", "nope"]).json()
    assert r["defaults"]["quote"] == ["symbol", "gap_pct", "last"]                   # order kept; no Holdings column
    assert client.get("/api/watch/columns").json()["defaults"]["quote"] == ["symbol", "gap_pct", "last"]
    assert client.put("/api/config/watch-columns/holding", json=["qty", "market_value"]).json()["defaults"]["holding"] == \
        ["symbol", "qty", "market_value"]
    assert client.put("/api/config/watch-columns/quote", json=["symbol"]).status_code == 400
    assert client.put("/api/config/watch-columns/nope", json=["last"]).status_code == 400
    assert client.delete("/api/config/watch-columns/quote").json()["defaults"]["quote"] == watch_fields.DEFAULTS["quote"]
    app_config.put_section("watch_columns", {"finviz": ["bogus"]})                    # a bad hand edit: built-in
    assert watch_fields.defaults()["finviz"] == watch_fields.DEFAULTS["finviz"]


def test_the_config_page(client, cache):
    assert client.get("/config").status_code == 200
    v = client.get("/api/config").json()
    assert {"studies", "watch_columns", "watchlists", "path"} <= set(v) and v["path"] == "data/user/config.json"
    from app import dashboards
    assert not dashboards.valid_name("config")                                       # the page's address is taken


def test_a_broken_config_file_is_never_written_over(cache, client):
    """A typo made by hand reads as empty, but a change is refused (409) instead of replacing the file."""
    from app import jsonfile, watchlists

    p = app_config.path()
    p.parent.mkdir(parents=True)
    p.write_text('{"watchlists": {"Mine": {"source": "symbols", "symbols": ["SPY"]}},')     # trailing comma
    assert app_config.section("watchlists") == {}
    with pytest.raises(jsonfile.BrokenFile, match="config.json"):
        watchlists.create("symbols", {"symbols": ["QQQ"]})
    r = client.put("/api/config/studies/sma", json={"sma_color": "#ffffff"})
    assert r.status_code == 409 and "config.json" in r.json()["detail"]
    assert p.read_text().endswith("]}},")                                                   # untouched
