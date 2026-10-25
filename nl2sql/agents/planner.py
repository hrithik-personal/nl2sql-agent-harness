"""Planner agent: NL question -> structured intent + candidate tables.

Decides whether the question is answerable as-is or needs one clarifying question.
"""

from __future__ import annotations

from nl2sql.llm import LLMUsage, complete_structured
from nl2sql.schemas import Plan, RetrievedContext

SYSTEM = (
    "You are the PLANNER in a text-to-SQL system for an e-commerce/logistics Postgres DB. "
    "Given a user question and the relevant schema, produce a structured query plan: the intent, "
    "metrics, group-by dimensions, filters (as natural language), time range, sort, limit, and the "
    "candidate tables/joins. Do NOT write SQL. "
    "If the question is genuinely ambiguous or missing a detail you cannot reasonably default, set "
    "needs_clarification=true and ask ONE concise clarifying_question; otherwise make sensible "
    "assumptions and proceed."
)


def plan(
    question: str, retrieved: RetrievedContext, clarification: str | None
) -> tuple[Plan, LLMUsage]:
    user = f"QUESTION: {question}\n\nSCHEMA:\n{retrieved.schema_text()}"
    if clarification:
        user += f"\n\nThe user clarified: {clarification}\nProceed; do not ask again."
    return complete_structured("planner", SYSTEM, user, Plan)
