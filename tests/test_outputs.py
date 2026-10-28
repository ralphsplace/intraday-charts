"""Study outputs: the Python list of kinds matches the page's drawing modules, and a malformed result fails only
its own study, with a message, instead of reaching the page."""
import re
from pathlib import Path

from app import studies
from app.studies import outputs
from app.studies.base import P, study

JS = Path(__file__).resolve().parents[1] / "app/static/js/outputs"


def test_output_kinds_match_the_drawing_modules():
    keys = set()
    for f in JS.glob("*.js"):
        if f.name != "index.js":
            keys |= set(re.findall(r'^\s*key: "(\w+)"', f.read_text(), re.M))
    listed = set(re.findall(r"^import (\w+) from", (JS / "index.js").read_text(), re.M))
    assert keys == set(outputs.OUTPUTS) == listed


def test_problems_finds_malformed_results():
    assert outputs.problems({"lines": [{"id": "a", "data": []}], "note": "x"}) == []
    assert outputs.problems({"markers": []}) == ["unknown output 'markers'"]
    assert outputs.problems({"levels": [{"price": "700", "label": "PDH"}]}) == ["levels[0].price should be number"]
    assert outputs.problems({"box": [1, 2]}) == ["box should be a dict"]
    assert outputs.problems({"note": 3}) == ["note should be text"]


def test_a_malformed_study_fails_alone(demo, monkeypatch):
    @study("broken_demo", "Broken", "Overlays", "price", [P("n", "N", "int", 1)], lambda p: "Broken", "",)
    def _broken(ctx, p):
        return {"levels": [{"price": None, "label": "x"}], "arrows": []}
    try:
        from app import engine
        layout = [{"uid": "a", "type": "broken_demo", "params": {}}, {"uid": "b", "type": "vwap", "params": {}}]
        v = engine.build_view("QQQ-DEMO", "2026-10-16", tf=3, cursor=640, studies=layout)
        bad, good = v["studies"]["a"], v["studies"]["b"]
        assert not bad["ok"] and "bad output" in bad["error"] and "arrows" in bad["error"]
        assert good["ok"] and good["lines"]
    finally:
        studies.REGISTRY.pop("broken_demo", None)
