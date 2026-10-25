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
    from nl2sql.retrieve import PgVectorRetriever

    return Deps(
        retriever=PgVectorRetriever(),
        planner=planner.plan,
        writer=writer.write,
        executor=SandboxExecutor(),
        verifier=verifier.verify,
        explainer=explainer.explain,
    )


def build_engine(deps: Deps | None = None, checkpointer=None) -> LangGraphEngine:
    return LangGraphEngine(deps or build_default_deps(), checkpointer=checkpointer)


def to_agent_result(res: RunResult) -> AgentResult:
    st = res.state
    return AgentResult(
        answer=st.answer,
        needs_clarification=res.interrupted,
        clarifying_question=res.clarifying_question,
        trace=st.trace,
        thread_id=res.thread_id,
    )
