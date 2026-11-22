"""LangGraph text-to-SQL agent with a self-correction (reflection) loop.

    START -> guard_input -> inspect_schema -> generate_sql -> validate_sql -> execute_query -> END
                 |                                ^               |  (syntax)       |  (db error)
                 v (blocked)                      |               v                 v
                END                               +------- reflection_node <--------+
                                                          (max MAX_RETRIES loops)
"""
from __future__ import annotations

import time
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from sqlalchemy.engine import Engine

from app.database import clean_db_error, execute_sql, inspect_schema
from app.guardrails import InputGuard
from app.llm import SYSTEM_PROMPT, LLMClient, clean_sql
from app.security import validate_sql
from app.state import AgentState

DEFAULT_MAX_RETRIES = 3


def build_graph(
    engine: Engine,
    llm: LLMClient,
    guard: InputGuard | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    max_rows: int = 1000,
):
    """Compile the agent graph. Dependencies are injected so tests can fake them."""
    dialect = engine.dialect.name
    sqlglot_dialect = {"postgresql": "postgres"}.get(dialect, dialect)

    # ------------------------------------------------------------------ nodes
    def guard_input_node(state: AgentState) -> dict[str, Any]:
        """Screen raw user text (NeMo Guardrails + scanner) BEFORE the LLM sees it."""
        if guard is None:
            return {"blocked": False}
        result = guard.check(state["user_query"])
        if result.allowed:
            return {"blocked": False, "logs": ["Input guardrails: passed."]}
        return {
            "blocked": True,
            "block_reason": result.reason,
            "block_layer": result.layer,
            "logs": [f"Input guardrails ({result.layer}): BLOCKED - {result.reason}"],
        }

    def inspect_schema_node(state: AgentState) -> dict[str, Any]:
        schema = inspect_schema(engine)
        n_tables = len(schema.splitlines()) if schema else 0
        return {"schema": schema, "retry_count": state.get("retry_count", 0),
                "logs": [f"Schema reflected: {n_tables} table(s)."]}

    def generate_sql_node(state: AgentState) -> dict[str, Any]:
        system = SYSTEM_PROMPT.format(dialect=dialect, schema=state["schema"])
        user = f"Question: {state['user_query']}"
        if state.get("correction_prompt"):
            user += "\n\n" + state["correction_prompt"]
        sql = clean_sql(llm.complete(system, user))
        label = "Regenerated SQL" if state.get("correction_prompt") else "Generated SQL"
        return {"generated_sql": sql, "logs": [f"{label}: {sql}"]}

    def validate_sql_node(state: AgentState) -> dict[str, Any]:
        """AST safety check. 'forbidden' stops the run; 'syntax' is sent to reflection."""
        verdict = validate_sql(state["generated_sql"], sqlglot_dialect)
        if verdict.kind == "ok":
            return {"error_message": None, "blocked": False, "logs": ["AST validation: read-only SELECT confirmed."]}
        if verdict.kind == "forbidden":
            return {
                "blocked": True,
                "block_reason": verdict.reason,
                "block_layer": "ast-sql-filter",
                "error_message": None,
                "db_result": None,
                "logs": [f"AST validation: BLOCKED - {verdict.reason}"],
                "attempts": [{"attempt": state.get("retry_count", 0) + 1, "sql": state["generated_sql"],
                              "status": "blocked", "error": verdict.reason, "seconds": 0.0}],
            }
        return {
            "blocked": False,
            "error_message": verdict.reason,
            "logs": [f"AST validation: syntax problem - {verdict.reason}"],
            "attempts": [{"attempt": state.get("retry_count", 0) + 1, "sql": state["generated_sql"],
                          "status": "syntax_error", "error": verdict.reason, "seconds": 0.0}],
        }

    def execute_query_node(state: AgentState) -> dict[str, Any]:
        attempt = state.get("retry_count", 0) + 1
        started = time.perf_counter()
        try:
            result = execute_sql(engine, state["generated_sql"], max_rows)
        except Exception as exc:  # noqa: BLE001 - any DB error feeds the reflection loop
            elapsed = time.perf_counter() - started
            msg = clean_db_error(exc)
            return {
                "error_message": msg,
                "db_result": None,
                "logs": [f"Execution failed (attempt {attempt}): {msg}"],
                "attempts": [{"attempt": attempt, "sql": state["generated_sql"], "status": "db_error",
                              "error": msg, "seconds": round(elapsed, 4)}],
            }
        elapsed = time.perf_counter() - started
        return {
            "error_message": None,
            "db_result": result,
            "logs": [f"Execution succeeded (attempt {attempt}): {len(result['rows'])} row(s) in {elapsed * 1000:.1f} ms."],
            "attempts": [{"attempt": attempt, "sql": state["generated_sql"], "status": "success",
                          "error": None, "seconds": round(elapsed, 4)}],
        }

    def reflection_node(state: AgentState) -> dict[str, Any]:
        """Read the error, bump the retry counter and build a correction prompt."""
        retry = state.get("retry_count", 0) + 1
        prompt = (
            "Your previous query failed. Fix it using ONLY columns/tables from the schema.\n"
            f"Previous SQL: {state['generated_sql']}\n"
            f"Database error: {state['error_message']}"
        )
        return {
            "retry_count": retry,
            "correction_prompt": prompt,
            "logs": [f"Reflection {retry}/{max_retries}: analysing error '{state['error_message']}' and asking the model to rewrite the query."],
        }

    # ----------------------------------------------------------------- routes
    def after_guard(state: AgentState) -> str:
        return "blocked" if state.get("blocked") else "ok"

    def after_validate(state: AgentState) -> str:
        if state.get("blocked"):
            return "blocked"
        if state.get("error_message"):  # unparseable SQL
            return "retry" if state.get("retry_count", 0) < max_retries else "give_up"
        return "execute"

    def after_execute(state: AgentState) -> str:
        if not state.get("error_message"):
            return "done"
        return "retry" if state.get("retry_count", 0) < max_retries else "give_up"

    # ------------------------------------------------------------------ graph
    g = StateGraph(AgentState)
    g.add_node("guard_input_node", guard_input_node)
    g.add_node("inspect_schema_node", inspect_schema_node)
    g.add_node("generate_sql_node", generate_sql_node)
    g.add_node("validate_sql_node", validate_sql_node)
    g.add_node("execute_query_node", execute_query_node)
    g.add_node("reflection_node", reflection_node)

    g.add_edge(START, "guard_input_node")
    g.add_conditional_edges("guard_input_node", after_guard, {"ok": "inspect_schema_node", "blocked": END})
    g.add_edge("inspect_schema_node", "generate_sql_node")
    g.add_edge("generate_sql_node", "validate_sql_node")
    g.add_conditional_edges(
        "validate_sql_node", after_validate,
        {"execute": "execute_query_node", "retry": "reflection_node", "blocked": END, "give_up": END},
    )
    g.add_conditional_edges(
        "execute_query_node", after_execute,
        {"done": END, "retry": "reflection_node", "give_up": END},
    )
    g.add_edge("reflection_node", "generate_sql_node")  # the self-correction loop
    return g.compile()


def run_agent(graph, question: str) -> dict[str, Any]:
    """Invoke the compiled graph and add a summary ``status`` + total timing."""
    started = time.perf_counter()
    final = graph.invoke({
        "user_query": question, "generated_sql": "", "db_result": None,
        "error_message": None, "retry_count": 0, "logs": [], "attempts": [], "blocked": False,
    })
    if final.get("blocked"):
        status = "blocked"
    elif final.get("error_message") or not final.get("db_result"):
        status = "failed"
    else:
        status = "success"
    final["status"] = status
    final["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    return final
