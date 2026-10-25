"""Writer agent: query plan -> Postgres SQL (structured), cleaned by sqlglot."""

from __future__ import annotations

from nl2sql.llm import LLMUsage, complete_structured
from nl2sql.schemas import Plan, RetrievedContext, SQLDraft

SYSTEM = (
    "You are the WRITER in a text-to-SQL system. Turn the given query plan into a SINGLE "
    "read-only PostgreSQL SELECT statement. Rules: tables live in the `shop` schema (you may "
    "reference them unqualified); use only tables/columns present in the schema; never write "
    "INSERT/UPDATE/DELETE/DDL; prefer explicit JOINs; add a reasonable LIMIT for row-returning "
    "queries. Use the provided examples as style guidance. If a critique of your previous attempt "
    "is given, fix exactly that."
)


def write(
    plan: Plan, retrieved: RetrievedContext, critique: str | None
) -> tuple[SQLDraft, LLMUsage]:
    user = (
        f"PLAN:\n{plan.model_dump_json(indent=2)}\n\n"
        f"SCHEMA:\n{retrieved.schema_text()}\n\n"
        f"EXAMPLES:\n{retrieved.exemplar_text()}"
    )
    if critique:
        user += f"\n\nYOUR PREVIOUS SQL FAILED. Critique to fix:\n{critique}"
    return complete_structured("writer", SYSTEM, user, SQLDraft)
