"""LangGraph orchestration engine (v1).

Uses the LangGraph primitives the project is meant to demonstrate:
  * StateGraph over the Pydantic `RunState`
  * reducers (declared on RunState) so drafts/verdicts/trace *append* in the loop
  * a conditional edge for the ok / retry / abort decision
  * interrupt() + Command(resume=...) for the clarifying-question human-in-the-loop
  * a checkpointer (PostgresSaver in prod, MemorySaver in tests) for durability/resume
  * recursion_limit as a hard step cap

Nodes close over injected `Deps`, so the whole graph runs under test with fakes
(no DB, no API key).
"""

from __future__ import annotations

import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from nl2sql.orchestration.base import Deps, Orchestrator, RunResult
from nl2sql.schemas import Answer, ExecError, ExecResult, RunState, TraceStep


def _step(agent: str, name: str, t0: float, status: str = "ok", usage=None, **detail) -> TraceStep:
    return TraceStep(
        step=name,
        agent=agent,
        status=status,
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        tokens=getattr(usage, "total_tokens", 0) if usage else 0,
        cost_usd=getattr(usage, "cost_usd", 0.0) if usage else 0.0,
        detail=detail,
    )


class LangGraphEngine(Orchestrator):
    def __init__(self, deps: Deps, checkpointer=None, recursion_limit: int = 25) -> None:
        super().__init__(deps)
        self.checkpointer = checkpointer or MemorySaver()
        self.recursion_limit = recursion_limit
        self.app = self._build()

    # --- nodes ---------------------------------------------------------- #
    def _retrieve(self, state: RunState) -> dict:
        t0 = time.perf_counter()
        ctx = self.deps.retriever(state.question)
        return {"retrieved": ctx, "trace": [_step("retriever", "retrieve", t0,
                                                   tables=[t.table for t in ctx.tables])]}

    def _plan(self, state: RunState) -> dict:
        t0 = time.perf_counter()
        ctx = state.retrieved
        if state.clarification_response:
            plan, usage = self.deps.planner(state.question, ctx, state.clarification_response)
            return {"plan": plan, "trace": [_step("planner", "plan", t0, usage=usage)]}

        plan, usage = self.deps.planner(state.question, ctx, None)
        if plan.needs_clarification:
            # pause the graph; resumes here with the user's answer
            user_answer = interrupt(plan.clarifying_question or "Could you clarify your question?")
            plan2, usage2 = self.deps.planner(state.question, ctx, user_answer)
            return {
                "plan": plan2,
                "clarification_response": user_answer,
                "trace": [_step("planner", "plan", t0, usage=usage2, clarified=True)],
            }
        return {"plan": plan, "trace": [_step("planner", "plan", t0, usage=usage)]}

    def _write(self, state: RunState) -> dict:
        t0 = time.perf_counter()
        critique = state.last_verdict.critique if state.last_verdict else None
        draft, usage = self.deps.writer(state.plan, state.retrieved, critique)
        return {"sql_drafts": [draft], "trace": [_step("writer", "write", t0, usage=usage,
                                                       sql=draft.sql)]}

    def _execute(self, state: RunState) -> dict:
        t0 = time.perf_counter()
        allowed = {t.table for t in state.retrieved.tables} if state.retrieved else set()
        result = self.deps.executor(state.last_sql.sql, allowed)
        status = "error" if isinstance(result, ExecError) else "ok"
        return {"exec_results": [result], "trace": [_step("executor", "execute", t0, status=status)]}

    def _verify(self, state: RunState) -> dict:
        t0 = time.perf_counter()
        verdict, usage = self.deps.verifier(
            state.question, state.plan, state.last_sql.sql, state.last_exec
        )
        out: dict = {"verdicts": [verdict], "trace": [_step("verifier", "verify", t0, usage=usage,
                                                            status=verdict.status)]}
        if verdict.status == "retry":
            out["retry_count"] = state.retry_count + 1
        return out

    def _explain(self, state: RunState) -> dict:
        t0 = time.perf_counter()
        result = next((r for r in reversed(state.exec_results) if isinstance(r, ExecResult)), None)
        verdict = state.last_verdict
        sql = state.last_sql.sql if state.last_sql else None
        total_cost = round(sum(s.cost_usd for s in state.trace), 6)

        if result is None:
            ans = Answer(
                text="I couldn't produce a query I was confident in for that question.",
                confidence=0.2, sql=sql, cost_usd=total_cost, low_confidence=True,
            )
            return {"answer": ans, "trace": [_step("explainer", "explain", t0, status="low_conf")]}

        ans, usage = self.deps.explainer(state.question, sql, result, verdict)
        ans.sql = sql
        ans.cost_usd = round(total_cost + getattr(usage, "cost_usd", 0.0), 6)
        if verdict and verdict.status != "ok":
            ans.low_confidence = True
            ans.confidence = min(ans.confidence, 0.5)
        return {"answer": ans, "trace": [_step("explainer", "explain", t0, usage=usage)]}

    # --- routing -------------------------------------------------------- #
    def _route_after_verify(self, state: RunState) -> str:
        verdict = state.last_verdict
        if verdict and verdict.status == "ok":
            return "explain"
        if verdict and verdict.status == "retry" and state.retry_count <= self.deps.settings.max_retries:
            return "write"
        return "explain"  # abort or budget exhausted -> graceful low-confidence answer

    # --- build / run ---------------------------------------------------- #
    def _build(self):
        g = StateGraph(RunState)
        g.add_node("retrieve", self._retrieve)
        g.add_node("plan", self._plan)
        g.add_node("write", self._write)
        g.add_node("execute", self._execute)
        g.add_node("verify", self._verify)
        g.add_node("explain", self._explain)

        g.add_edge(START, "retrieve")
        g.add_edge("retrieve", "plan")
        g.add_edge("plan", "write")
        g.add_edge("write", "execute")
        g.add_edge("execute", "verify")
        g.add_conditional_edges("verify", self._route_after_verify,
                                {"write": "write", "explain": "explain"})
        g.add_edge("explain", END)
        return g.compile(checkpointer=self.checkpointer)

    def _config(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": self.recursion_limit}

    def _finish(self, thread_id: str) -> RunResult:
        snap = self.app.get_state(self._config(thread_id))
        # interrupted?
        for task in snap.tasks:
            if getattr(task, "interrupts", None):
                q = task.interrupts[0].value
                return RunResult(state=RunState(**snap.values), interrupted=True,
                                 clarifying_question=q, thread_id=thread_id)
        return RunResult(state=RunState(**snap.values), thread_id=thread_id)

    def run(self, question: str, thread_id: str | None = None) -> RunResult:
        import uuid
        tid = thread_id or uuid.uuid4().hex
        self.app.invoke(RunState(question=question), self._config(tid))
        return self._finish(tid)

    def resume(self, thread_id: str, answer: str) -> RunResult:
        self.app.invoke(Command(resume=answer), self._config(thread_id))
        return self._finish(thread_id)
