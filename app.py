"""Streamlit dashboard:  streamlit run app.py"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.charts import CHART_TYPES, build_figure, suggest_chart, to_dataframe
from app.service import build_agent

st.set_page_config(page_title="SQL Analytics Agent", page_icon="🛡️", layout="wide")

EXAMPLES = [
    "Show orders sorted by date.",
    "Total sales by region",
    "Monthly sales trend",
    "Order count by status",
    "Top 5 customers by spend",
    "DROP TABLE orders; --",
]


@st.cache_resource(show_spinner="Starting agent (database, LLM, guardrails)...")
def get_agent():
    return build_agent()


agent = get_agent()

# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Agent configuration")
    st.markdown(f"**LLM:** {agent.llm_label}")
    st.markdown(f"**Guardrails:** {agent.guard_status}")
    st.markdown(f"**Max retries:** {agent.settings.max_retries}")
    st.markdown(f"**Database:** `{agent.engine.url.render_as_string(hide_password=True)}`")
    st.divider()
    st.caption("Try an example")
    for i, example in enumerate(EXAMPLES):
        if st.button(example, key=f"ex{i}", width="stretch"):
            st.session_state["question"] = example
            st.session_state["auto_run"] = True

# --------------------------------------------------------------- query panel
st.title("🛡️ SQL & Database Analytics Agent")
st.caption("Ask a question in plain English. Queries are validated (AST filter + NeMo Guardrails) and self-correct on database errors.")

question = st.text_area("Your question", key="question", height=90,
                       placeholder="e.g. Show orders sorted by date.")
run_clicked = st.button("Run query", type="primary")

if (run_clicked or st.session_state.pop("auto_run", False)) and question.strip():
    with st.spinner("Thinking..."):
        st.session_state["result"] = agent.ask(question)

result = st.session_state.get("result")
if result:
    status = result["status"]
    attempts = result.get("attempts", [])

    if status == "blocked":
        st.error(f"🚫 **Security warning:** request blocked. {result.get('block_reason', '')}")
        st.caption(f"Blocked by: `{result.get('block_layer', 'unknown')}` — the database was not queried.")
    elif status == "failed":
        st.error(f"The agent could not produce a working query after {result.get('retry_count', 0)} retries. "
                 f"Last error: {result.get('error_message')}")
    else:
        retries = result.get("retry_count", 0)
        msg = f"✅ Query succeeded — {len(result['db_result']['rows'])} row(s)"
        if retries:
            msg += f" after {retries} self-correction retr{'y' if retries == 1 else 'ies'}"
        st.success(msg)

    # --- collapsible feeds -------------------------------------------------
    if result.get("generated_sql"):
        with st.expander("Generated SQL", expanded=True):
            st.code(result["generated_sql"], language="sql")
    with st.expander("Execution telemetry"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Status", status.upper())
        c2.metric("Attempts", len(attempts))
        c3.metric("Retries used", result.get("retry_count", 0))
        c4.metric("Total time", f"{result.get('elapsed_seconds', 0) * 1000:.0f} ms")
        if attempts:
            st.dataframe(pd.DataFrame(attempts), width="stretch", hide_index=True)
    with st.expander("Self-correction & guardrail log", expanded=bool(result.get("retry_count")) or status == "blocked"):
        for line in result.get("logs", []):
            st.text(f"• {line}")

    # --- results + chart ---------------------------------------------------
    if status == "success":
        df = to_dataframe(result["db_result"])
        st.subheader("Results")
        st.dataframe(df, width="stretch", hide_index=True)

        spec = suggest_chart(df)
        if spec:
            st.subheader("Chart")
            kind = st.radio("Chart type", CHART_TYPES, index=CHART_TYPES.index(spec["type"]),
                            horizontal=True, key=f"kind_{hash(result['generated_sql'])}")
            st.plotly_chart(build_figure(df, {**spec, "type": kind}), width="stretch")
        else:
            st.caption("No chartable numeric data in this result.")
