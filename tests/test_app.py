from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()


def test_final_scenario_renders_all_kpis(app):
    assert not app.exception
    assert any("FINAL" in s.value for s in app.success)
    assert len(app.metric) == 8 and len(app.tabs) == 5
    assert any("SYNTHETIC" in w.value for w in app.warning)


def test_raw_scenario_shows_blocked_banner_and_no_commentary(app):
    app.sidebar.radio[0].set_value("Raw submissions (errors present)").run()
    assert not app.exception
    assert any("BLOCKED" in e.value for e in app.error)
    assert any("blocked" in i.value.lower() for i in app.info)
