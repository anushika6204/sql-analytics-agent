"""AST-based SQL safety filter (sqlglot).

Only a single, read-only query (SELECT / UNION / WITH ... SELECT) may reach the
database. Everything else is rejected by walking the parsed syntax tree rather
than by fragile keyword matching, so tricks such as comments, odd casing or
stacked statements do not help an attacker.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# Node types that mean "this statement writes / changes state / escapes the sandbox".
_FORBIDDEN_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Drop", "Alter", "AlterTable", "Create",
    "TruncateTable", "Command", "Pragma", "Attach", "Detach", "Grant", "Revoke",
    "Set", "Use", "Transaction", "Commit", "Rollback", "Into", "Copy", "LoadData",
    "Kill", "Analyze", "Refresh", "Install", "Show", "Describe",
)
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name) for name in _FORBIDDEN_NAMES if hasattr(exp, name)
)

# Read-only top-level statement shapes.
_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = tuple(
    t for t in (getattr(exp, "Select", None), getattr(exp, "Union", None),
                getattr(exp, "SetOperation", None), getattr(exp, "Subquery", None)) if t
)

# Functions that read/write files or sleep, even inside a SELECT.
_DANGEROUS_FUNCTIONS = {
    "load_extension", "readfile", "writefile", "pg_sleep", "pg_read_file",
    "pg_read_binary_file", "lo_import", "lo_export", "dblink", "copy",
    "xp_cmdshell", "sleep", "benchmark", "pg_terminate_backend",
}


@dataclass(frozen=True)
class SQLValidation:
    is_safe: bool
    kind: str  # "ok" | "forbidden" (security block) | "syntax" (unparseable -> may be retried)
    reason: str = ""


def validate_sql(sql_query: str, dialect: str | None = None) -> SQLValidation:
    """Parse ``sql_query`` and decide whether it is a safe read-only query."""
    if not sql_query or not sql_query.strip():
        return SQLValidation(False, "syntax", "Empty SQL statement.")

    try:
        statements = [s for s in sqlglot.parse(sql_query, read=dialect) if s is not None]
    except SqlglotError as exc:
        return SQLValidation(False, "syntax", f"SQL could not be parsed: {str(exc).splitlines()[0]}")

    # A trailing ";" followed by a comment parses as an extra empty Semicolon node.
    statements = [s for s in statements if not isinstance(s, exp.Semicolon)]

    if not statements:
        return SQLValidation(False, "syntax", "No SQL statement found.")

    # Report the most specific problem first: any non-read-only statement.
    for stmt in statements:
        if not isinstance(stmt, _ALLOWED_ROOTS):
            return SQLValidation(
                False, "forbidden",
                f"Only read-only SELECT queries are allowed; got {stmt.key.upper()}.",
            )
    if len(statements) > 1:
        return SQLValidation(False, "forbidden", "Multiple statements are not allowed (possible stacked-query injection).")

    root = statements[0]

    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return SQLValidation(False, "forbidden", f"Forbidden operation detected: {node.key.upper()}.")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            name = (node.name or node.key or "").lower()
            if name in _DANGEROUS_FUNCTIONS:
                return SQLValidation(False, "forbidden", f"Forbidden function detected: {name}().")

    return SQLValidation(True, "ok")


def is_safe_select_only(sql_query: str, dialect: str | None = None) -> bool:
    """Boolean convenience wrapper (mirrors the helper in the project brief)."""
    return validate_sql(sql_query, dialect).is_safe
