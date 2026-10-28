"""The line types are defined twice, once per language: app/studies/base.py for study settings and
app/static/js/styles.js for the page. This keeps the two in step."""
import json
import re
from pathlib import Path

from app.studies import base

JS = (Path(__file__).resolve().parents[1] / "app/static/js/styles.js").read_text()


def js_value(name: str):
    m = re.search(rf"export const {name} = (\[[^\]]*\]|\{{[^}}]*\}});", JS)
    assert m, name
    return json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)))


def test_line_styles_match_python():
    assert js_value("LINE_STYLES") == base.STYLES
    assert js_value("LINE_STYLE_LABELS") == base.STYLE_LABELS
