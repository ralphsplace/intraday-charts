"""Named paper accounts (app/paper/accounts.py) and their endpoints: unique names, "Paper N", settings checked,
history kept through renames, resets and the balance, and a broken file never written over."""
import json

import pytest
from fastapi.testclient import TestClient

from app import store
from app.paper import accounts, engine


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(cache):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_new_accounts_get_numbered_names_and_the_defaults(cache):
    n1, a1 = accounts.create()
    n2, _ = accounts.create()
    assert (n1, n2) == ("Paper 1", "Paper 2")
    assert a1["start_cash"] == 25_000 and a1["settings"]["commission"] == {"per_share": 0.005, "minimum": 1.0, "max_pct": 1.0}
    assert a1["settings"]["shorting"] is True and len(a1["id"]) == 12
    with pytest.raises(ValueError, match="already a paper account"):
        accounts.create("Paper 1")


def test_settings_are_checked(cache):
    for bad in ({"start_cash": 5}, {"settings": {"slippage": -1}}, {"settings": {"commission": {"per_share": 5}}}):
        with pytest.raises(ValueError):
            accounts.create(**bad)


def test_a_rename_keeps_the_history_and_a_reset_the_record(cache):
    name, item = accounts.create("Practice", start_cash=10_000)
    st = engine.new_state(10_000)
    st["cash"] = 10_250.0                                             # a session that made $250
    with accounts.editing_history(item) as h:
        h["sessions"] = [{"id": "s1", "symbol": "QQQ", "day": "2026-10-16", "state": st, "started": 1.0}]
    accounts.rename("Practice", "Morning")
    assert accounts.all_accounts()["Morning"]["balance"] == 10_250
    accounts.reset("Morning")
    h = accounts.history(accounts.find("Morning")[1])
    assert len(h["sessions"]) == 1 and h["resets"][0]["balance"] == 10_250
    assert accounts.all_accounts()["Morning"]["balance"] == 10_000


def test_delete_keeps_the_history_file_aside(cache):
    _, item = accounts.create("Old")
    with accounts.editing_history(item) as h:
        h["sessions"] = []
    accounts.delete("Old")
    assert "Old" not in accounts.all_accounts()
    assert (cache / "user" / "paper" / f"{item['id']}.json.deleted").exists()


def test_endpoints(client, cache):
    r = client.post("/api/paper/accounts", json={"start_cash": 50_000}).json()
    assert r["name"] == "Paper 1" and r["accounts"]["Paper 1"]["balance"] == 50_000
    assert client.post("/api/paper/accounts", json={"name": "Paper 1"}).status_code == 409
    assert client.post("/api/paper/accounts", json={"start_cash": 1}).status_code == 400
    r = client.put("/api/paper/accounts/Paper 1", json={"settings": {"shorting": False}}).json()
    assert r["item"]["settings"]["shorting"] is False and r["item"]["settings"]["slippage"] == 0.01
    assert client.post("/api/paper/accounts/Paper 1/rename", json={"to": "Swing"}).json()["name"] == "Swing"
    assert client.get("/api/paper/accounts/Swing/history").json()["sessions"] == []
    assert client.get("/api/paper/accounts/nope/history").status_code == 404
    assert client.post("/api/paper/accounts/Swing/reset").status_code == 200
    assert "Swing" not in client.delete("/api/paper/accounts/Swing").json()["accounts"]


def test_defaults_on_the_config_page(client, cache):
    d = client.put("/api/paper/defaults", json={"start_cash": 30_000, "settings": {"slippage": 0.02}}).json()
    assert d["start_cash"] == 30_000 and d["settings"]["slippage"] == 0.02
    assert client.post("/api/paper/accounts", json={}).json()["item"]["start_cash"] == 30_000
    assert client.delete("/api/paper/defaults").json()["start_cash"] == 25_000
    assert json.loads((cache / "user" / "config.json").read_text())["paper"] == {}


def test_a_broken_history_file_is_never_written_over(client, cache):
    _, item = accounts.create("A")
    p = accounts.history_path(item["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"sessions": [},')
    assert client.post("/api/paper/accounts/A/reset").status_code == 409
    assert p.read_text() == '{"sessions": [},'
