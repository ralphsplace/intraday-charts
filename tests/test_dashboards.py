"""Dashboards: addresses, create / rename / duplicate / delete / default, and starting layouts."""
import json

import pytest
from fastapi.testclient import TestClient

from app import dashboards, saved, store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))   # a device on the home network


def test_seeded_dashboard_and_addresses(client):
    d = client.get("/api/dashboards").json()
    assert [(i["name"], i["type"]) for i in d["items"]] == [("QQQs", "charts"), ("Internals", "charts")]
    assert d["default"] == "main"
    root = client.get("/")
    assert root.status_code == 200 and "window.DASHBOARD" in root.text and '"name": "QQQs"' in root.text
    assert 'id="grid"' in root.text                              # the chart page
    assert 'id="grid"' in client.get("/qqqs").text               # any letter case
    assert "Create a dashboard" in client.get("/config").text      # managed on the Config page
    moved = client.get("/dashboards", follow_redirects=False)
    assert moved.status_code == 307 and moved.headers["location"] == "/config?tab=dashboards"
    missing = client.get("/NoSuchBoard")
    assert missing.status_code == 404 and "/config?tab=dashboards" in missing.text
    assert client.get("/static/dash.js").status_code == 200


def test_news_dashboard_is_gone(client, tmp_path):
    for path in ("/static/news.js", "/static/news.html", "/api/bars?symbol=QQQ", "/api/news?symbol=QQQ&start=a&end=b"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/dashboards", json={"name": "N", "type": "news"}).status_code == 400
    # a News dashboard saved by the earlier version is dropped; if it was the default, the first one takes over
    (tmp_path / "user").mkdir(exist_ok=True)
    (tmp_path / "user" / "dashboards.json").write_text(json.dumps({"default": "news", "items": [
        {"id": "main", "name": "QQQs", "type": "charts", "settings": {}},
        {"id": "news", "name": "News", "type": "news", "settings": {}}]}))
    d = client.get("/api/dashboards").json()
    assert [i["name"] for i in d["items"]] == ["QQQs", "Internals"] and d["default"] == "main"
    assert client.get("/News").status_code == 404


def test_create_rename_default_delete(client):
    made = client.post("/api/dashboards", json={"name": "SPY", "type": "charts"}).json()
    assert client.get("/SPY").status_code == 200
    assert client.post("/api/dashboards", json={"name": "spy", "type": "charts"}).status_code == 400   # name taken
    for bad in ("api", "dashboards", "two words", "", "-x", "x" * 41):
        assert client.post("/api/dashboards", json={"name": bad, "type": "charts"}).status_code == 400, bad
    assert client.patch(f"/api/dashboards/{made['id']}", json={"name": "Spiders"}).status_code == 200
    assert client.get("/SPY").status_code == 404 and client.get("/Spiders").status_code == 200
    client.post(f"/api/dashboards/{made['id']}/default")
    assert '"name": "Spiders"' in client.get("/").text
    client.delete(f"/api/dashboards/{made['id']}")
    d = client.get("/api/dashboards").json()
    assert d["default"] == "main" and [i["name"] for i in d["items"]] == ["QQQs", "Internals"]
    assert client.delete("/api/dashboards/internals").status_code == 200
    assert client.delete("/api/dashboards/main").status_code == 400                # never the last one
    assert client.delete("/api/dashboards/nope").status_code == 404


def test_start_layout_and_copy(client):
    lay = {"layout": "1x1", "configs": [{"symbol": "QQQ", "tf": 5, "days": 1, "studies": []}]}
    client.put("/api/saved/layouts/One", json=lay)
    made = client.post("/api/dashboards", json={"name": "Solo", "type": "charts", "start_layout": "One"}).json()
    assert made["settings"]["start"] == lay
    assert '"start"' in client.get("/Solo").text
    assert client.post("/api/dashboards", json={"name": "B", "type": "charts", "start_layout": "Nope"}).status_code == 404
    cp = client.post("/api/dashboards", json={"name": "Solo-2", "type": "charts", "copy_of": made["id"]}).json()
    assert cp["settings"] == made["settings"] and cp["copied_from"] == made["id"]
    assert f'"copied_from": "{made["id"]}"' in client.get("/Solo-2").text


def test_settings_saved_per_dashboard(client):
    client.patch("/api/dashboards/main", json={"settings": {"note": "kept"}})
    assert dashboards.find("main")["settings"] == {"note": "kept"}
    assert saved.path("dashboards").exists()


def test_internals_dashboard_is_built_in_once(client, tmp_path):
    d = client.get("/api/dashboards").json()
    item = next(i for i in d["items"] if i["name"] == "Internals")
    start = item["settings"]["start"]
    assert item["id"] == "internals" and start["layout"] == "2/4"
    assert [c["symbol"] for c in start["configs"]] == ["QQQ", "SPY", "VOLD-NYSE", "-VIX", "TICK-NYSE", "ADD-NYSE"]
    assert "Market internals" in d["templates"]["internals"]
    page = client.get("/Internals").text
    assert '"id": "internals"' in page and "VOLD-NYSE" in page
    # deleted once, it stays deleted
    assert client.delete("/api/dashboards/internals").status_code == 200
    assert [i["name"] for i in client.get("/api/dashboards").json()["items"]] == ["QQQs"]
    assert "internals" in json.loads((tmp_path / "user" / "dashboards.json").read_text())["seeded"]
    # and more can be made from the template
    made = client.post("/api/dashboards", json={"name": "Breadth", "type": "charts", "start_template": "internals"}).json()
    assert made["settings"]["start"]["layout"] == "2/4"
    assert client.post("/api/dashboards", json={"name": "X", "type": "charts", "start_template": "nope"}).status_code == 404


def test_a_dashboard_already_called_internals_is_kept(client, tmp_path):
    (tmp_path / "user").mkdir(exist_ok=True)
    (tmp_path / "user" / "dashboards.json").write_text(json.dumps({"default": "main", "items": [
        {"id": "main", "name": "QQQs", "type": "charts", "settings": {}},
        {"id": "abc", "name": "internals", "type": "charts", "settings": {"note": "mine"}}]}))
    d = client.get("/api/dashboards").json()
    assert [(i["id"], i["name"]) for i in d["items"]] == [("main", "QQQs"), ("abc", "internals")]



def test_dashboard_from_top_and_bottom_counts(client):
    made = client.post("/api/dashboards", json={"name": "Wide", "type": "charts", "start_rows": [3, 5]}).json()
    assert made["settings"]["start"] == {"layout": "3/5", "configs": [], "prefs": {}}
    for bad in ([0, 2], [2, 7], [2], [1, 2, 3], ["a", 2]):
        r = client.post("/api/dashboards", json={"name": "Bad", "type": "charts", "start_rows": bad})
        assert r.status_code in (400, 422), bad
    assert client.get("/api/dashboards").json()["max_per_row"] == 6


def test_pages_ask_for_this_versions_scripts(client):
    """A browser mustn't run yesterday's scripts with today's page after an update (Firefox kept old copies)."""
    from app import server
    v = server.STATIC_VERSION
    for page in ("/", "/Internals", "/config", "/earnings"):
        r = client.get(page)
        assert r.headers["cache-control"] == "no-store"
        assert r.text.count('"/static/') == r.text.count(f'"/static/{v}/') > 0, page   # every file, versioned
    for path in (f"/static/{v}/js/grid.js", f"/static/{v}/style.css", "/static/js/grid.js",
                 "/static/_v0123456789/js/grid.js", f"/static/{v}/vendor/lightweight-charts.standalone.production.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    assert client.get(f"/static/{v}/js/grid.js").text == client.get("/static/js/grid.js").text
    assert client.get(f"/static/{v}/../server.py").status_code == 404
    assert client.get("/static/_vnot-a-version/js/grid.js").status_code == 404
