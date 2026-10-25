"""Streamlit demo UI — calls the FastAPI surface.

Shows the answer, the generated SQL (the 'citation'), a chart when suggested,
confidence + cost, and the full agent trace (including retries).
"""

from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="nl2sql-agent-harness", layout="wide")
st.title("nl2sql-agent-harness")
st.caption("Ask a question about the e-commerce / logistics database in plain English.")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
    st.session_state.pending_clarification = None

question = st.text_input("Your question", placeholder="Top 10 sellers by delivered revenue")
go = st.button("Ask", type="primary")


def render(res: dict) -> None:
    if res.get("needs_clarification"):
        st.session_state.thread_id = res.get("thread_id")
        st.session_state.pending_clarification = res.get("clarifying_question")
        st.warning(f"Clarify: {res['clarifying_question']}")
        return

    st.session_state.pending_clarification = None
    ans = res.get("answer") or {}
    st.subheader("Answer")
    st.write(ans.get("text", ""))
    cols = st.columns(3)
    cols[0].metric("Confidence", f"{ans.get('confidence', 0):.0%}")
    cols[1].metric("Cost", f"${ans.get('cost_usd', 0):.4f}")
    cols[2].metric("Low confidence", "yes" if ans.get("low_confidence") else "no")

    if ans.get("sql"):
        st.subheader("SQL")
        st.code(ans["sql"], language="sql")

    chart = ans.get("chart")
    if chart:
        st.caption(f"suggested chart: {chart['type']} of {chart['y']} by {chart['x']}")

    with st.expander("Agent trace"):
        st.dataframe(pd.DataFrame(res.get("trace", [])))


if go and question:
    with st.spinner("thinking…"):
        r = requests.post(f"{API}/ask", json={"question": question}, timeout=120)
        render(r.json())

if st.session_state.pending_clarification:
    reply = st.text_input("Your clarification")
    if st.button("Send clarification") and reply:
        with st.spinner("thinking…"):
            r = requests.post(
                f"{API}/ask/resume",
                json={"thread_id": st.session_state.thread_id, "answer": reply},
                timeout=120,
            )
            render(r.json())
