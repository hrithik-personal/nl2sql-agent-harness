"""Default wiring: build the real Deps and the engine, and run a question.

The surfaces (FastAPI / MCP / Streamlit) all go through here so they share one
orchestrator instance and identical behaviour.
"""

from __future__ import annotations

from nl2sql.agents import explainer, planner, verifier, writer
from nl2sql.orchestration.base import Deps, RunResult
from nl2sql.orchestration.langgraph_engine import LangGraphEngine
from nl2sql.schemas import AgentResult


def build_default_deps() -> Deps:
    from nl2sql.executor import SandboxExecutor
    from nl2sql.retrieval_cache import RetrievalCassette
    from nl2sql.retrieve import PgVectorRetriever

    return Deps(
        # record/replay the retrieved context so offline runs are deterministic on
        # any machine (the inner pgvector retriever is built lazily — never in replay)
        retriever=RetrievalCassette(lambda: PgVectorRetriever()),
        planner=planner.plan,
        writer=writer.write,
        executor=SandboxExecutor(),
        verifier=verifier.verify,
        explainer=explainer.explain,
    )


def _make_checkpointer():
    """Durable checkpointer for interrupts/resume across restarts.

    CHECKPOINTER=postgres uses LangGraph's PostgresSaver (app schema); otherwise
    the engine falls back to in-memory (fine for a single process / tests).
    """
    import os

    if os.getenv("CHECKPOINTER", "memory").lower() != "postgres":
        return None
    from langgraph.checkpoint.postgres import PostgresSaver

    from nl2sql.config import get_settings

    saver = PostgresSaver.from_conn_string(get_settings().app_dsn())
    saver.setup()
    return saver


def build_engine(deps: Deps | None = None, checkpointer=None) -> LangGraphEngine:
    return LangGraphEngine(
        deps or build_default_deps(), checkpointer=checkpointer or _make_checkpointer()
    )


def to_agent_result(res: RunResult) -> AgentResult:
    st = res.state
    return AgentResult(
        answer=st.answer,
        needs_clarification=res.interrupted,
        clarifying_question=res.clarifying_question,
        trace=st.trace,
        thread_id=res.thread_id,
    )
