"""Shared LangGraph state."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # --- required by the project brief -------------------------------------
    user_query: str
    generated_sql: str
    db_result: Optional[dict[str, Any]]   # {"columns": [...], "rows": [[...]]}
    error_message: Optional[str]
    retry_count: int
    # --- supporting fields -------------------------------------------------
    schema: str
    correction_prompt: Optional[str]      # built by reflection_node for the generator
    blocked: bool                         # True when a security layer stopped the request
    block_reason: str
    block_layer: str
    # Append-only telemetry (reducer concatenates lists returned by nodes)
    logs: Annotated[list[str], operator.add]
    attempts: Annotated[list[dict[str, Any]], operator.add]
