"""End-to-end UI checks of the Verification Test Cases using Streamlit's AppTest."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture()
def app_env(monkeypatch, db_url):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("USE_NEMO_GUARDRAILS", "true")
    streamlit.cache_resource.clear()
    yield db_url
    streamlit.cache_resource.clear()


def _ask(question: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=60).run()
    at.text_area(key="question").set_value(question).run()
    next(b for b in at.button if b.label == "Run query").click().run()
    return at


def test_case_1_ui_self_corrects_column_reference(app_env):
    at = _ask("Show orders sorted by date.")
    assert not at.exception
    assert any("self-correction" in s.value for s in at.success)
    assert at.code[0].value == "SELECT * FROM orders ORDER BY order_date"
    log = " ".join(t.value for t in at.text)
    assert "no such column: created_at" in log and "Reflection 1/3" in log
    assert len(at.dataframe) >= 1


def test_case_2_ui_blocks_injection_and_keeps_table(app_env):
    at = _ask("DROP TABLE orders; --")
    assert not at.exception
    assert any("Security warning" in e.value for e in at.error)
    assert len(at.dataframe) == 0
    with create_engine(app_env).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar() == 50


def test_chart_rendered_for_aggregate_query(app_env):
    at = _ask("Total sales by region")
    assert not at.exception
    assert len(at.get("plotly_chart")) == 1
