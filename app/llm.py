"""LLM clients behind one tiny interface: ``complete(system, user) -> str``."""
from __future__ import annotations

import difflib
import re
from typing import Protocol

from app.config import Settings

SYSTEM_PROMPT = """You are an expert SQL analyst. Convert the user's question into ONE read-only SQL query.

Rules:
- Use ONLY the tables and columns listed in the schema below. Never invent columns.
- Output a single SELECT statement (CTEs allowed). Never write INSERT/UPDATE/DELETE/DROP/ALTER/CREATE.
- Target dialect: {dialect}.
- Return ONLY the SQL, with no explanation and no markdown fences.

Database schema:
{schema}
"""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


def clean_sql(raw: str) -> str:
    """Strip markdown fences / chatter that models sometimes add around SQL."""
    text = raw.strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    return text.strip()


class OpenAILLM:
    def __init__(self, api_key: str, model: str):
        from langchain_openai import ChatOpenAI

        self._chat = ChatOpenAI(api_key=api_key, model=model, temperature=0)

    def complete(self, system: str, user: str) -> str:
        reply = self._chat.invoke([("system", system), ("human", user)])
        return reply.content if isinstance(reply.content, str) else str(reply.content)


class MockLLM:
    """Deterministic offline text-to-SQL model for demos and tests.

    On a first attempt it deliberately "hallucinates" a ``created_at`` column
    for date-ordering questions. When the prompt contains a database error it
    repairs the query from the schema - exactly the behaviour Verification
    Test Case 1 expects to observe.
    """

    _DATE_SYNONYMS = {"created", "at", "time", "timestamp", "date", "day", "ordered", "placed"}

    def complete(self, system: str, user: str) -> str:
        question = self._question(user)
        error = self._error(user)
        if error:
            return self._repair(system, user, error)
        return self._first_attempt(question)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _question(user: str) -> str:
        m = re.search(r"Question:\s*(.+)", user)
        return (m.group(1) if m else user).lower()

    @staticmethod
    def _error(user: str) -> str | None:
        m = re.search(r"Database error:\s*(.+)", user)
        return m.group(1).strip() if m else None

    def _first_attempt(self, q: str) -> str:
        if re.search(r"sorted by date|order(ed)? by date|by date|latest|most recent|newest", q):
            return "SELECT * FROM orders ORDER BY created_at"  # <- intentional bad column
        if re.search(r"month|trend|over time", q):
            return ("SELECT strftime('%Y-%m', order_date) AS month, SUM(amount) AS total_sales "
                    "FROM orders GROUP BY month ORDER BY month")
        if "region" in q:
            return "SELECT region, SUM(amount) AS total_sales FROM orders GROUP BY region ORDER BY total_sales DESC"
        if "status" in q:
            return "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY order_count DESC"
        if "categor" in q:
            return ("SELECT p.category, SUM(o.amount) AS total_sales FROM orders o "
                    "JOIN products p ON p.id = o.product_id GROUP BY p.category ORDER BY total_sales DESC")
        if "customer" in q:
            return ("SELECT c.name, SUM(o.amount) AS total_spent FROM orders o "
                    "JOIN customers c ON c.id = o.customer_id GROUP BY c.name ORDER BY total_spent DESC LIMIT 5")
        if re.search(r"how many|count|number of", q):
            return "SELECT COUNT(*) AS total_orders FROM orders"
        return "SELECT * FROM orders LIMIT 20"

    def _repair(self, system: str, user: str, error: str) -> str:
        prev = re.search(r"Previous SQL:\s*(.+)", user)
        sql = prev.group(1).strip() if prev else "SELECT * FROM orders"
        bad = re.search(r"no such column:\s*([\w.]+)|column \"?([\w.]+)\"? does not exist", error, re.I)
        if not bad:
            return sql
        bad_col = (bad.group(1) or bad.group(2)).split(".")[-1]

        # Column names listed in the schema, e.g. "orders(id INTEGER PK, order_date DATE, ...)"
        columns = re.findall(r"[\(,]\s*(\w+)\s+[A-Z]", system)
        tokens = set(bad_col.lower().split("_"))
        if tokens & self._DATE_SYNONYMS:
            candidates = [c for c in columns if "date" in c.lower()]
        else:
            candidates = difflib.get_close_matches(bad_col, columns, n=1, cutoff=0.4)
        if not candidates:
            return sql
        return re.sub(rf"\b{re.escape(bad_col)}\b", candidates[0], sql)


def build_llm(settings: Settings) -> tuple[LLMClient, str]:
    """Return (client, human-readable provider label)."""
    provider = settings.llm_provider
    if provider == "openai" or (provider == "auto" and settings.openai_api_key):
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return OpenAILLM(settings.openai_api_key, settings.openai_model), f"OpenAI ({settings.openai_model})"
    return MockLLM(), "MockLLM (offline demo)"
