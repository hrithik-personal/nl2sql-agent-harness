"""FastAPI surface — the universal HTTP entry point.

Thin adapter over the orchestrator library. `run_sql` is scoped off-by-default
(ENABLE_RUN_SQL=1 to turn on), matching the tool permission matrix.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from nl2sql.executor import SandboxExecutor
from nl2sql.pipeline import build_engine, to_agent_result
from nl2sql.retrieve import PgVectorRetriever
from nl2sql.schemas import AgentResult
from nl2sql.telemetry import init_telemetry

app = FastAPI(title="nl2sql-agent-harness")
_engine = None
_executor = SandboxExecutor()


def engine():
    global _engine
    if _engine is None:
        init_telemetry()
        _engine = build_engine()
    return _engine


class AskRequest(BaseModel):
    question: str
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    answer: str


class RunSqlRequest(BaseModel):
    sql: str


@app.get("/schema")
def get_schema() -> dict:
    retr = PgVectorRetriever()
    return {"tables": [c.model_dump() for c in retr.cards.values()]}


@app.post("/ask", response_model=AgentResult)
def ask(req: AskRequest) -> AgentResult:
    return to_agent_result(engine().run(req.question, thread_id=req.thread_id))


@app.post("/ask/resume", response_model=AgentResult)
def resume(req: ResumeRequest) -> AgentResult:
    return to_agent_result(engine().resume(req.thread_id, req.answer))


@app.post("/run_sql")
def run_sql(req: RunSqlRequest) -> dict:
    if os.getenv("ENABLE_RUN_SQL", "0") != "1":
        raise HTTPException(status_code=403, detail="run_sql is disabled (set ENABLE_RUN_SQL=1)")
    retr = PgVectorRetriever()
    result = _executor(req.sql, allowed_tables=set(retr.cards))
    return result.model_dump()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
