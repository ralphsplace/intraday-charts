"""The one-time upgrade at server start (app/upgrade.py): what older versions saved on the server becomes today's
shape, once; a second run changes nothing; and checking whether a file needs it never changes anything."""
import json

import pytest

from app import app_config, saved, store, upgrade, watchlists


@pytest.fixture
def user(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    (tmp_path / "user").mkdir()
    return tmp_path / "user"


def write(p, d):
    p.write_text(json.dumps(d))


def read(p):
    return json.loads(p.read_text())


def test_nothing_to_do_on_a_new_install(user):
    assert upgrade.run() == []
    assert not (user / "config.json").exists()


def test_the_old_watch_list_file_moves_into_the_config_with_ids(user):
    write(user / "watchlists.json", {"Old": ["QQQ", "SPY"], "Both": ["X"]})
    write(user / "config.json", {"watchlists": {"Both": {"id": "keep", "source": "symbols", "symbols": ["Y"]}}})
    done = upgrade.run()
    assert len(done) == 2 and "moved 1 watch list" in done[0]
    lists = watchlists.all_lists()
    assert lists["Both"] == {"id": "keep", "source": "symbols", "symbols": ["Y"]}               # the config wins
    assert lists["Old"]["symbols"] == ["QQQ", "SPY"] and len(lists["Old"]["id"]) == 12
    assert not (user / "watchlists.json").exists() and (user / "watchlists.json.moved").exists()
    assert upgrade.run() == []                                                                 # once only


def test_lists_without_ids_get_one(user):
    write(user / "config.json", {"watchlists": {"A": ["QQQ"], "B": {"source": "holdings"}, "C": {"id": "c", "source": "holdings"}}})
    assert upgrade.run() == ["gave 2 watch list(s) the current shape and an id"]
    lists = app_config.section("watchlists")
    assert lists["A"]["source"] == "symbols" and lists["A"]["id"] and lists["B"]["id"] and lists["C"]["id"] == "c"


def test_a_saved_view_gets_its_price_type_from_the_old_style_name(user):
    write(saved.path("views"), {"V": {"symbol": "QQQ", "tf": 3, "style": "hollow", "studies": []},
                                "W": {"symbol": "QQQ", "tf": 3, "price": {"type": "line", "params": {}}, "style": "bars"},
                                "New": {"symbol": "SPY", "price": {"type": "heikin", "params": {}}}})
    assert upgrade.run() == ["upgraded 2 saved view(s)"]
    v = read(saved.path("views"))
    assert v["V"]["price"] == {"type": "candles", "params": {"up_fill": False}} and "style" not in v["V"]
    assert v["W"]["price"]["type"] == "line" and "style" not in v["W"]                      # a price already set wins
    assert v["New"] == {"symbol": "SPY", "price": {"type": "heikin", "params": {}}}


def test_a_saved_layout_watch_list_from_before_tabs_gets_a_named_list(user):
    old = {"layout": "2", "configs": [
        {"id": "c1", "symbol": "SPY", "tf": 3, "style": "candles", "studies": []},
        {"kind": "watchlist", "id": "w1", "symbols": ["QQQ", "SPY"], "list": "", "link": "c1"}]}
    write(saved.path("layouts"), {"Two": old})
    upgrade.run()
    c = read(saved.path("layouts"))["Two"]["configs"]
    lists = watchlists.all_lists()
    tab = c[1]["tabs"][0]
    assert lists[tab["list"]] == {"id": tab["listId"], "source": "symbols", "symbols": ["QQQ", "SPY"]}
    assert tab["list"] == "Watch list 1" and not {"symbols", "list", "feed"} & set(c[1])
    assert c[0]["link"] == c[1]["link"] == "red"                       # linked by the chart's id: a colour group
    assert c[0]["price"]["type"] == "candles"
    assert upgrade.run() == [] and len(watchlists.all_lists()) == 1    # no second list on a second run


def test_tabs_from_before_named_lists(user):
    write(app_config.path(), {"watchlists": {"Mine": {"id": "m1", "source": "symbols", "symbols": ["A"]}}})
    tabs = [{"id": "t1", "list": "Mine", "columns": None},                                       # names a list
            {"id": "t2", "name": "Gainers", "list": "@feed", "feed": {"source": "finviz", "address": "https://finviz.com/x"}},
            {"id": "t3", "list": "@holdings"},
            {"id": "t4", "list": "@feed", "feed": {}},                                           # a FinViz tab never set up
            {"id": "t5", "name": "Watch list", "list": "", "symbols": ["NVDA"]}]                 # the old default name
    write(saved.path("layouts"), {"L": {"layout": "1", "configs": [{"kind": "watchlist", "id": "w", "tabs": tabs}]}})
    upgrade.run()
    t = read(saved.path("layouts"))["L"]["configs"][0]["tabs"]
    lists = watchlists.all_lists()
    assert t[0]["listId"] == "m1"
    assert t[1]["list"] == "Gainers" and lists["Gainers"]["source"] == "finviz" and "feed" not in t[1]
    assert lists[t[2]["list"]]["source"] == "holdings"
    assert t[3]["list"] == "" and t[3]["listId"] is None
    assert t[4]["list"].startswith("Watch list ") and lists[t[4]["list"]]["symbols"] == ["NVDA"]


def test_dashboards_starting_layouts(user):
    write(saved.path("dashboards"), {"default": "a", "items": [
        {"id": "a", "name": "QQQs", "type": "charts", "settings": {"start": {"layout": "1", "configs": [{"symbol": "QQQ", "style": "line"}]}}},
        {"id": "b", "name": "Plain", "type": "charts", "settings": {}}]})
    assert upgrade.run() == ["upgraded the dashboards' starting layouts"]
    d = read(saved.path("dashboards"))
    assert d["items"][0]["settings"]["start"]["configs"][0]["price"]["type"] == "line" and d["default"] == "a"


def test_checking_never_makes_a_list(user):
    """Whether a file needs upgrading is decided on a copy: the lists a real upgrade would make are made once."""
    write(saved.path("layouts"), {"L": {"layout": "1", "configs": [{"kind": "watchlist", "id": "w", "symbols": ["A"]}]}})
    assert upgrade._needs(upgrade._layout, read(saved.path("layouts")).values())
    assert watchlists.all_lists() == {}
    assert "watchlists" not in read(saved.path("layouts"))["L"]["configs"][0].get("tabs", [{}])[0]


def test_a_broken_file_is_left_alone(user):
    saved.path("views").write_text('{"V": {"style": "hollow"},')                                   # a typo by hand
    assert upgrade.run() == []
    assert saved.path("views").read_text() == '{"V": {"style": "hollow"},'
