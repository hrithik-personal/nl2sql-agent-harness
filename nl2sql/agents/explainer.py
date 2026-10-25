"""Explainer agent: result rows -> natural-language answer + confidence + chart hint."""

from __future__ import annotations

import json

from pydantic import BaseModel

from nl2sql.llm import LLMUsage, complete_structured
from nl2sql.schemas import Answer, ChartSpec, ExecResult, Verdict

SYSTEM = (
    "You are the EXPLAINER in a text-to-SQL system. Given the user question, the SQL and its "
    "result, write a concise, direct natural-language answer (1-3 sentences, cite concrete "
    "numbers). Give a confidence in [0,1]. If the result is naturally chartable (a category/time "
    "dimension plus a numeric measure), propose a chart with the column names to use; otherwise "
    "leave chart null."
)


class _ExplainOut(BaseModel):
    text: str
    confidence: float = 0.7
    chart: ChartSpec | None = None


def explain(
    question: str, sql: str, result: ExecResult, verdict: Verdict
) -> tuple[Answer, LLMUsage]:
    sample = {"columns": result.columns, "rows": result.rows[:30], "rowcount": result.rowcount}
    user = f"QUESTION: {question}\n\nSQL:\n{sql}\n\nRESULT:\n{json.dumps(sample, default=str)}"
    out, usage = complete_structured("explainer", SYSTEM, user, _ExplainOut)
    return (
        Answer(text=out.text, confidence=out.confidence, chart=out.chart, sql=sql),
        usage,
    )
