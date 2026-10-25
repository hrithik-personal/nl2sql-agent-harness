"""Engine wiring tests with injected fakes — no DB, no LLM, no API key.

Exercises the LangGraph engine's pipeline, the Writer<->Verifier self-correction
loop (incl. the accumulator reducers), and the clarify interrupt/resume.
"""

from nl2sql.llm import LLMUsage
from nl2sql.orchestration.base import Deps
from nl2sql.orchestration.langgraph_engine import LangGraphEngine
from nl2sql.schemas import (
    Answer,
    ColumnInfo,
    ExecError,
    ExecResult,
    Plan,
    RetrievedContext,
    SQLDraft,
    TableCard,
    Verdict,
)

CTX = RetrievedContext(
    tables=[
        TableCard(table="orders", columns=[ColumnInfo(name="id", type="int")]),
        TableCard(table="order_items", columns=[ColumnInfo(name="order_id", type="int")]),
    ]
)


def retriever(_q):
    return CTX


def planner_ok(_q, _ctx, _clar):
    return Plan(intent="count orders", tables=["orders"]), LLMUsage()


def planner_needs_clar(_q, _ctx, clar):
    if clar:
        return Plan(intent="count delivered orders", tables=["orders"]), LLMUsage()
    return (
        Plan(intent="?", needs_clarification=True, clarifying_question="Which status?"),
        LLMUsage(),
    )


def writer(_plan, _ctx, _critique):
    return SQLDraft(sql="SELECT count(*) FROM orders", tables_used=["orders"]), LLMUsage()


def executor_ok(_sql, _allowed):
    return ExecResult(columns=["count"], rows=[[42]], rowcount=1)


def verifier_ok(_q, _plan, _sql, _result):
    return Verdict(status="ok"), LLMUsage()


def explainer(_q, _sql, _result, _verdict):
    return Answer(text="There are 42 orders.", confidence=0.9), LLMUsage()


def _deps(**over):
    base = dict(
        retriever=retriever,
        planner=planner_ok,
        writer=writer,
        executor=executor_ok,
        verifier=verifier_ok,
        explainer=explainer,
    )
    base.update(over)
    return Deps(**base)


def test_happy_path():
    eng = LangGraphEngine(_deps())
    res = eng.run("how many orders are there?")
    assert not res.interrupted
    assert res.state.answer.text == "There are 42 orders."
    assert res.state.retry_count == 0
    assert len(res.state.sql_drafts) == 1
    # trace accumulated across all six stages
    steps = {s.step for s in res.state.trace}
    assert {"retrieve", "plan", "write", "execute", "verify", "explain"} <= steps


def test_self_correction_loop():
    calls = {"n": 0}

    def flaky_executor(_sql, _allowed):
        calls["n"] += 1
        if calls["n"] == 1:
            return ExecError(error_type="invalid_sql", message="column foo does not exist")
        return ExecResult(columns=["count"], rows=[[42]], rowcount=1)

    def verifier(_q, _plan, _sql, result):
        if isinstance(result, ExecError):
            return Verdict(status="retry", critique=result.message), LLMUsage()
        return Verdict(status="ok"), LLMUsage()

    eng = LangGraphEngine(_deps(executor=flaky_executor, verifier=verifier))
    res = eng.run("how many orders?")
    assert res.state.retry_count == 1
    assert len(res.state.sql_drafts) == 2  # reducer appended both attempts
    assert len(res.state.exec_results) == 2
    assert res.state.answer.text == "There are 42 orders."


def test_retry_budget_exhausted_gives_low_confidence():
    def always_error(_sql, _allowed):
        return ExecError(error_type="db_error", message="boom")

    def verifier(_q, _plan, _sql, _result):
        return Verdict(status="retry", critique="still broken"), LLMUsage()

    eng = LangGraphEngine(_deps(executor=always_error, verifier=verifier))
    res = eng.run("something impossible")
    assert res.state.answer.low_confidence
    # max_retries=2 -> 3 write attempts, then abort to explain
    assert len(res.state.sql_drafts) == 3


def test_wallclock_budget_aborts_gracefully():
    from nl2sql.config import Settings

    def always_error(_sql, _allowed):
        return ExecError(error_type="db_error", message="boom")

    def verifier(_q, _plan, _sql, _result):
        return Verdict(status="retry", critique="again"), LLMUsage()

    # zero budget + high retry cap => the wall-clock guard (not the retry cap) stops the loop
    settings = Settings(max_wallclock_seconds=0, max_retries=10)
    deps = _deps(executor=always_error, verifier=verifier)
    deps.settings = settings
    eng = LangGraphEngine(deps)
    res = eng.run("slow question")
    assert res.state.answer.low_confidence
    assert len(res.state.sql_drafts) == 1  # stopped before any retry


def test_clarify_interrupt_and_resume():
    eng = LangGraphEngine(_deps(planner=planner_needs_clar))
    res = eng.run("show me orders", thread_id="t1")
    assert res.interrupted
    assert res.clarifying_question == "Which status?"
    assert res.state.answer is None

    res2 = eng.resume("t1", "delivered")
    assert not res2.interrupted
    assert res2.state.answer.text == "There are 42 orders."
    assert res2.state.clarification_response == "delivered"
