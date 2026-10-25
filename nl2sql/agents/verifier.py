"""Verifier agent: judge the executed result against the intent.

Execution errors short-circuit to a `retry` verdict (no LLM call needed — the
error message becomes the critique). Successful results are judged by the model.
"""

from __future__ import annotations

import json

from nl2sql.llm import LLMUsage, complete_structured
from nl2sql.schemas import ExecError, ExecResult, Plan, Verdict

SYSTEM = (
    "You are the VERIFIER in a text-to-SQL system — a skeptical critic. Given the user question, "
    "the plan, the executed SQL and a sample of its result, decide if the result correctly answers "
    "the question. Return status 'ok' if it does; 'retry' with a specific critique for the Writer "
    "if the SQL is wrong (wrong columns/joins/filters, empty when rows were clearly expected, "
    "mismatched aggregation); 'abort' only if the question cannot be answered from this schema."
)


def verify(
    question: str, plan: Plan, sql: str, result: ExecResult | ExecError
) -> tuple[Verdict, LLMUsage]:
    if isinstance(result, ExecError):
        # deterministic, no LLM: hand the error straight back to the Writer
        status = "abort" if result.error_type == "forbidden" else "retry"
        return (
            Verdict(
                status=status,
                critique=f"{result.error_type}: {result.message}",
                reason="execution failed",
            ),
            LLMUsage(),
        )

    sample = {"columns": result.columns, "rows": result.rows[:10], "rowcount": result.rowcount}
    user = (
        f"QUESTION: {question}\n\nPLAN:\n{plan.model_dump_json()}\n\n"
        f"SQL:\n{sql}\n\nRESULT SAMPLE:\n{json.dumps(sample, default=str)}"
    )
    return complete_structured("verifier", SYSTEM, user, Verdict)
