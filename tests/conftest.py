"""Shared fixtures: an isolated seeded SQLite DB and scriptable fake LLMs."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

# Streamlit warns about a missing ScriptRunContext when AppTest runs in bare mode; it is expected.
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from seed_db import seed  # noqa: E402

from app.database import get_engine  # noqa: E402


class ScriptedLLM:
    """Returns pre-programmed SQL answers in order and records every prompt it receives."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        idx = min(len(self.calls) - 1, len(self.answers) - 1)  # repeat the last answer if exhausted
        return self.answers[idx]


@pytest.fixture()
def db_url(tmp_path) -> str:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    seed(url, n_orders=50)
    return url


@pytest.fixture()
def engine(db_url):
    eng = get_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def count_orders(engine):
    from sqlalchemy import text

    def _count() -> int:
        with engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()

    return _count
