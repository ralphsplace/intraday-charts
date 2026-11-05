"""Named backtesting accounts (app/backtesting/accounts.py) and their endpoints: unique names, "Account N", settings
checked, and the defaults for new accounts."""
import json

import pytest
from fastapi.testclient import TestClient

from app import store
from app.backtesting import accounts


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
    assert (n1, n2) == ("Account 1", "Account 2")
    assert a1["start_cash"] == 25_000 and a1["settings"]["commission"] == {"per_share": 0.005, "minimum": 1.0, "max_pct": 1.0}
    assert a1["settings"]["shorting"] is True and len(a1["id"]) == 12
    with pytest.raises(ValueError, match="already a backtesting account"):
        accounts.create("Account 1")


def test_settings_are_checked(cache):
    for bad in ({"start_cash": 5}, {"settings": {"slippage": -1}}, {"settings": {"commission": {"per_share": 5}}}):
        with pytest.raises(ValueError):
            accounts.create(**bad)


def test_rename_and_delete(cache):
    accounts.create("Practice", start_cash=10_000)
    accounts.rename("Practice", "Morning")
    assert accounts.all_accounts()["Morning"]["start_cash"] == 10_000
    accounts.delete("Morning")
    assert "Morning" not in accounts.all_accounts()


def test_endpoints(client, cache):
    r = client.post("/api/backtest-accounts", json={"start_cash": 50_000}).json()
    assert r["name"] == "Account 1" and r["accounts"]["Account 1"]["start_cash"] == 50_000
    assert client.post("/api/backtest-accounts", json={"name": "Account 1"}).status_code == 409
    assert client.post("/api/backtest-accounts", json={"start_cash": 1}).status_code == 400
    r = client.put("/api/backtest-accounts/Account 1", json={"settings": {"shorting": False}}).json()
    assert r["item"]["settings"]["shorting"] is False and r["item"]["settings"]["slippage"] == 0.01
    assert client.post("/api/backtest-accounts/Account 1/rename", json={"to": "Swing"}).json()["name"] == "Swing"
    assert client.put("/api/backtest-accounts/nope", json={"start_cash": 1000}).status_code == 404
    for gone in ("/api/backtest-accounts/Swing/history", "/api/backtest-accounts/Swing/reset"):   # practice is gone (#83)
        assert client.request("GET" if gone.endswith("history") else "POST", gone).status_code in (404, 405)
    assert "Swing" not in client.delete("/api/backtest-accounts/Swing").json()["accounts"]


def test_defaults_on_the_config_page(client, cache):
    d = client.put("/api/backtest-account-defaults", json={"start_cash": 30_000, "settings": {"slippage": 0.02}}).json()
    assert d["start_cash"] == 30_000 and d["settings"]["slippage"] == 0.02
    assert client.post("/api/backtest-accounts", json={}).json()["item"]["start_cash"] == 30_000
    assert client.delete("/api/backtest-account-defaults").json()["start_cash"] == 25_000
    assert json.loads((cache / "user" / "config.json").read_text())["backtesting"] == {}
