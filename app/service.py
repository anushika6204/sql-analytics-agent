"""Wires settings -> engine, LLM, guard and compiled graph (used by the UI)."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.config import PROJECT_ROOT, Settings, get_settings
from app.database import get_engine
from app.graph import build_graph, run_agent
from app.guardrails import InputGuard
from app.llm import build_llm


@dataclass
class Agent:
    graph: Any
    engine: Engine
    settings: Settings
    llm_label: str
    guard_status: str

    def ask(self, question: str) -> dict[str, Any]:
        return run_agent(self.graph, question)


def ensure_sample_data(settings: Settings) -> bool:
    """Seed the bundled SQLite sample DB if it is missing/empty. Returns True if seeded."""
    if not settings.database_url.startswith("sqlite"):
        return False
    engine = get_engine(settings.database_url)
    if inspect(engine).get_table_names():
        return False
    engine.dispose()
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from seed_db import seed  # noqa: WPS433

    path = settings.database_url.replace("sqlite:///", "", 1)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    seed(settings.database_url)
    return True


def build_agent(settings: Settings | None = None) -> Agent:
    settings = settings or get_settings()
    ensure_sample_data(settings)
    engine = get_engine(settings.database_url)
    llm, llm_label = build_llm(settings)
    guard = InputGuard(use_nemo=settings.use_nemo_guardrails)
    graph = build_graph(engine, llm, guard, settings.max_retries, settings.max_result_rows)
    return Agent(graph, engine, settings, llm_label, guard.status)
