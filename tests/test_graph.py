"""Graph behaviour: self-correction loop, retry cap, and security short-circuits."""
import pytest

from app import graph as graph_module
from app.graph import build_graph, run_agent
from app.guardrails import InputGuard
from tests.conftest import ScriptedLLM

BAD = "SELECT * FROM orders ORDER BY created_at"
GOOD = "SELECT * FROM orders ORDER BY order_date"


def test_self_correction_with_real_sqlite_error(engine):
    """First query uses a non-existent column; reflection must repair it."""
    llm = ScriptedLLM(BAD, GOOD)
    result = run_agent(build_graph(engine, llm), "Show orders sorted by date.")

    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert result["generated_sql"] == GOOD
    assert len(result["db_result"]["rows"]) == 50
    assert [a["status"] for a in result["attempts"]] == ["db_error", "success"]
    assert "no such column: created_at" in result["attempts"][0]["error"]
    # the reflection node ran, and the 2nd prompt carried the DB error back to the LLM
    assert any(line.startswith("Reflection 1/3") for line in result["logs"])
    assert len(llm.calls) == 2
    assert "no such column: created_at" in llm.calls[1][1]
    assert BAD in llm.calls[1][1]


def test_self_correction_with_mocked_database_error(engine, monkeypatch):
    """Mock the DB layer to raise 'no such column' once, then behave normally."""
    real_execute = graph_module.execute_sql
    calls = {"n": 0}

    def flaky_execute(eng, sql, max_rows=1000):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("no such column: created_at")
        return real_execute(eng, sql, max_rows)

    monkeypatch.setattr(graph_module, "execute_sql", flaky_execute)
    llm = ScriptedLLM("SELECT created_at FROM orders", "SELECT order_date FROM orders")
    result = run_agent(build_graph(engine, llm), "Show order dates")

    assert calls["n"] == 2
    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert result["generated_sql"] == "SELECT order_date FROM orders"
    assert result["error_message"] is None


def test_retry_loop_is_capped_at_three(engine):
    llm = ScriptedLLM(BAD)  # never fixes the query
    result = run_agent(build_graph(engine, llm, max_retries=3), "Show orders sorted by date.")

    assert result["status"] == "failed"
    assert result["retry_count"] == 3
    assert len(llm.calls) == 4  # 1 initial attempt + 3 retries, then give up
    assert "no such column" in result["error_message"]
    assert result["db_result"] is None


def test_syntax_error_is_routed_through_reflection(engine):
    llm = ScriptedLLM("SELEC * FROM orders", "SELECT * FROM orders")
    result = run_agent(build_graph(engine, llm), "Show all orders")
    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert [a["status"] for a in result["attempts"]] == ["syntax_error", "success"]


def test_clean_query_needs_no_retry(engine):
    llm = ScriptedLLM("```sql\nSELECT COUNT(*) AS n FROM orders\n```")  # fences are stripped
    result = run_agent(build_graph(engine, llm), "How many orders?")
    assert result["status"] == "success"
    assert result["retry_count"] == 0
    assert result["db_result"]["rows"] == [[50]]
    assert len(llm.calls) == 1


def test_write_sql_from_llm_is_blocked_and_db_untouched(engine, count_orders):
    """Even if the model emits a destructive statement, the AST filter stops it."""
    before = count_orders()
    llm = ScriptedLLM("DELETE FROM orders")
    result = run_agent(build_graph(engine, llm), "clean up the orders")

    assert result["status"] == "blocked"
    assert result["block_layer"] == "ast-sql-filter"
    assert result["db_result"] is None
    assert len(llm.calls) == 1  # no reflection retry for security blocks
    assert count_orders() == before


def test_injection_blocked_before_llm_and_database(engine, count_orders):
    """Verification Test Case 2: 'DROP TABLE orders; --'."""
    before = count_orders()
    llm = ScriptedLLM(GOOD)
    graph = build_graph(engine, llm, guard=InputGuard(use_nemo=False))
    result = run_agent(graph, "DROP TABLE orders; --")

    assert result["status"] == "blocked"
    assert llm.calls == []            # LLM never saw the input
    assert result["attempts"] == []   # database never queried
    assert result["db_result"] is None
    assert count_orders() == before   # table intact


def test_injection_blocked_by_nemo_layer(engine, count_orders):
    guard = InputGuard(use_nemo=True)
    if guard._rails is None:
        pytest.skip("NeMo Guardrails not available")
    llm = ScriptedLLM(GOOD)
    result = run_agent(build_graph(engine, llm, guard=guard), "DROP TABLE orders; --")
    assert result["status"] == "blocked"
    assert result["block_layer"] == "nemo-guardrails"
    assert llm.calls == []


def test_database_is_read_only_even_if_filter_is_bypassed(engine, count_orders):
    """Defence in depth: the connection itself refuses writes."""
    from app.database import execute_sql

    with pytest.raises(Exception):
        execute_sql(engine, "DELETE FROM orders")
    assert count_orders() == 50


def test_schema_inspection_populates_state(engine):
    llm = ScriptedLLM("SELECT 1")
    result = run_agent(build_graph(engine, llm), "anything")
    assert "orders(" in result["schema"] and "order_date" in result["schema"]
    assert "order_date" in llm.calls[0][0]  # schema was injected into the system prompt
