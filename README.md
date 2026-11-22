# SQL & Database Analytics Agent

A text-to-SQL analytics agent built with **LangGraph**, **SQLAlchemy**, an **AST-based SQL safety filter** (sqlglot), **NeMo Guardrails**, and a **Streamlit + Plotly** dashboard. It answers plain-English questions against a database, automatically repairs queries that fail (self-correction loop, max 3 retries), and refuses anything that is not a read-only `SELECT`.

- **Repository**: `[Insert URL]`

## Architecture

```
START -> guard_input -> inspect_schema -> generate_sql -> validate_sql -> execute_query -> END
            |                                  ^              |  syntax        |  DB error
            v blocked                          |              v                v
           END                                 +------ reflection_node <-------+   (max 3 loops)
                                                           validate_sql: forbidden SQL -> END (blocked)
```

| Node | File | Responsibility |
|---|---|---|
| `guard_input_node` | `app/graph.py`, `app/guardrails.py` | NeMo Guardrails input rail + built-in scanner screen the raw text **before the LLM sees it** |
| `inspect_schema_node` | `app/database.py` | SQLAlchemy `inspect()` reflection -> prompt-ready schema text |
| `generate_sql_node` | `app/llm.py` | LLM writes the SQL (uses correction prompt on retries) |
| `validate_sql_node` | `app/security.py` | sqlglot AST check: read-only, single statement, no dangerous functions |
| `execute_query_node` | `app/database.py` | Runs the SQL; catches DB errors into `error_message` |
| `reflection_node` | `app/graph.py` | Increments `retry_count`, builds a correction prompt from the error, loops to the generator |

State (`app/state.py`) tracks `user_query`, `generated_sql`, `db_result`, `error_message`, `retry_count` (plus schema, logs, attempts and block info).

### Defence in depth

1. **NeMo Guardrails input rail** (`guardrails_config/`) - blocks tautologies (`OR 1=1`), comment sequences, `<script>` tags, stacked/destructive SQL, UNION injection, prompt-injection phrases.
2. **Built-in scanner** (`app/input_scanner.py`) - the same rules, always on; it is the logic behind the NeMo custom action and the fallback if NeMo cannot start (the guard never fails open).
3. **AST filter** (`app/security.py`) - parses the *generated* SQL with sqlglot and rejects `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/PRAGMA/ATTACH/SELECT INTO`, multiple statements, and file/sleep functions. Walks the whole tree, so comments, casing or CTE tricks do not help.
4. **Read-only connection** (`app/database.py`) - `PRAGMA query_only=ON` on SQLite, `default_transaction_read_only=on` on PostgreSQL. Even a filter bypass cannot write.

Security blocks end the run immediately (no retry). Only *syntax/DB errors* enter the reflection loop.

## Project structure

```
sql-analytics-agent/
├── app.py                    # Streamlit entry point  ->  streamlit run app.py
├── app/
│   ├── config.py             # env-based settings
│   ├── state.py              # LangGraph state
│   ├── graph.py              # StateGraph + reflection loop + run_agent()
│   ├── database.py           # engine, schema reflection, read-only execute
│   ├── security.py           # AST SQL safety filter (sqlglot)
│   ├── input_scanner.py      # regex scan of raw user text
│   ├── guardrails.py         # NeMo Guardrails wrapper + fallback
│   ├── llm.py                # OpenAI client + deterministic MockLLM
│   ├── charts.py             # Plotly chart selection/building
│   └── service.py            # wires everything together for the UI
├── guardrails_config/        # NeMo: config.yml, rails.co, actions.py
├── scripts/seed_db.py        # creates + seeds the sample database
├── data/sample.db            # pre-seeded SQLite database
├── tests/                    # pytest suite (58 tests)
├── .env.example  requirements.txt  pytest.ini  .gitignore
└── README.md
```

## Installation

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then edit .env
```

### Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/sample.db` | PostgreSQL also works: `postgresql+psycopg2://user:pass@host:5432/db` (`pip install psycopg2-binary`) |
| `LLM_PROVIDER` | `auto` | `auto` = OpenAI if `OPENAI_API_KEY` set, else offline `MockLLM`; `openai`; `mock` |
| `OPENAI_API_KEY` | _(empty)_ | Required for real LLM use |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `MAX_RETRIES` | `3` | Self-correction cap |
| `USE_NEMO_GUARDRAILS` | `true` | Falls back to built-in scanner if NeMo fails to start |

Secrets live only in `.env` (git-ignored). `.env.example` is committed.

### Database

The repo ships `data/sample.db` and the app auto-seeds the SQLite file if it is missing. To (re)create it, or to seed another database:

```bash
python scripts/seed_db.py                                   # data/sample.db
python scripts/seed_db.py postgresql+psycopg2://u:p@h/db    # any SQLAlchemy URL
```

Tables: `customers`, `products`, and `orders (id, customer_id, product_id, order_date, quantity, amount, region, status)` (300 rows).

## Run

```bash
streamlit run app.py
```

Dashboard: question box, sidebar example buttons, collapsible **Generated SQL**, **Execution telemetry** (status, attempts, retries, timing, per-attempt table) and **Self-correction & guardrail log**, a results table, and an automatic Plotly chart (line for time series, pie for <=6 categories, bar otherwise; switchable).

## Tests

```bash
pytest
```

58 tests covering: AST filter (11 write ops, stacked statements, dangerous functions, safe reads), input scanner and NeMo rail, the self-correction loop (real SQLite error **and** mocked DB error), the 3-retry cap, syntax-error routing, DB-untouched guarantees, chart selection, and end-to-end Streamlit UI runs (`streamlit.testing.AppTest`).

## Verification test cases

**Test Case 1 - self-correction.** With no OpenAI key (or `LLM_PROVIDER=mock`) run `streamlit run app.py` and ask *"Show orders sorted by date."* The offline MockLLM deliberately writes `ORDER BY created_at`; the log shows `no such column: created_at` -> `Reflection 1/3` -> regenerated `ORDER BY order_date` -> results rendered. (A real LLM given the schema will usually get the column right first time; the loop is exercised deterministically by the mock and by `tests/test_graph.py`.)

**Test Case 2 - injection block.** Enter `DROP TABLE orders; --` (or click the sidebar example). The NeMo input rail blocks it, a red security warning is shown, no SQL is generated, and `orders` still has 300 rows. If a model ever *did* emit a write statement, the AST filter blocks it (tested in `test_write_sql_from_llm_is_blocked_and_db_untouched`).

**Test Case 3 - test suite.** `pytest` -> all pass.

## Notes & limitations

- `MockLLM` targets SQLite (`strftime`); use OpenAI for PostgreSQL.
- The built-in scanner is deliberately conservative: a question containing `--`, `/* */` or phrases like "delete from" is rejected.
- Results are capped at `MAX_RESULT_ROWS` (default 1000).
