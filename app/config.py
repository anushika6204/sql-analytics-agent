"""Central configuration. Secrets come from the environment / .env only."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    llm_provider: str
    openai_api_key: str
    openai_model: str
    max_retries: int
    max_result_rows: int
    use_nemo_guardrails: bool


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    """Read settings fresh each call so tests can override env vars."""
    db_url = os.getenv("DATABASE_URL") or f"sqlite:///{PROJECT_ROOT / 'data' / 'sample.db'}"
    # Relative sqlite paths are resolved against the project root, not the CWD.
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////") and ":memory:" not in db_url:
        rel = db_url.replace("sqlite:///", "", 1)
        db_url = f"sqlite:///{(PROJECT_ROOT / rel).as_posix()}"
    return Settings(
        database_url=db_url,
        llm_provider=(os.getenv("LLM_PROVIDER") or "auto").lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
        max_retries=int(os.getenv("MAX_RETRIES") or 3),
        max_result_rows=int(os.getenv("MAX_RESULT_ROWS") or 1000),
        use_nemo_guardrails=_bool(os.getenv("USE_NEMO_GUARDRAILS"), True),
    )
