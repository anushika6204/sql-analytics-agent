"""Database access: engine creation, schema reflection and read-only execution."""
from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine


def get_engine(database_url: str) -> Engine:
    """Create an engine whose connections are read-only at the driver level.

    This is defence-in-depth: even if a write statement slipped past the AST
    filter, the database itself would reject it.
    """
    kwargs: dict[str, Any] = {}
    if database_url.startswith("postgresql"):
        kwargs["connect_args"] = {"options": "-c default_transaction_read_only=on"}
    engine = create_engine(database_url, future=True, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_query_only(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA query_only = ON")
            cur.close()

    return engine


def inspect_schema(engine: Engine) -> str:
    """Reflect table metadata (columns, types, PKs, FKs) into prompt-ready text."""
    insp = inspect(engine)
    lines: list[str] = []
    for table in sorted(insp.get_table_names()):
        pk = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
        cols = []
        for col in insp.get_columns(table):
            tag = " PK" if col["name"] in pk else ""
            cols.append(f"{col['name']} {col['type']}{tag}")
        line = f"{table}({', '.join(cols)})"
        fks = [
            f"{','.join(fk['constrained_columns'])} -> "
            f"{fk['referred_table']}({','.join(fk['referred_columns'])})"
            for fk in insp.get_foreign_keys(table)
        ]
        if fks:
            line += "  FK: " + "; ".join(fks)
        lines.append(line)
    return "\n".join(lines)


def execute_sql(engine: Engine, sql: str, max_rows: int = 1000) -> dict[str, Any]:
    """Run a SQL statement and return {'columns': [...], 'rows': [[...], ...]}.

    Raises sqlalchemy exceptions; the graph's execute node catches them.
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [list(r) for r in result.fetchmany(max_rows)]
    return {"columns": columns, "rows": rows}


def clean_db_error(exc: Exception) -> str:
    """Extract the concise driver error (e.g. 'no such column: created_at')."""
    orig = getattr(exc, "orig", None)
    msg = str(orig) if orig is not None else str(exc)
    return msg.strip().splitlines()[0] if msg.strip() else exc.__class__.__name__
