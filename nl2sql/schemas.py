"""Typed state and agent I/O models.

Framework-free on purpose: no LangGraph / LangChain imports here, so the exact
same models drive either orchestration engine. Accumulator fields on `RunState`
carry an `operator.add` reducer in their `Annotated` metadata; LangGraph reads it
to *append* across the self-correction loop, and it is harmless to every other
consumer.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Schema catalog / retrieval
# --------------------------------------------------------------------------- #


class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool = True


class TableCard(BaseModel):
    table: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[dict[str, str]] = Field(
        default_factory=list
    )  # {column, ref_table, ref_column}
    sample_values: dict[str, list[str]] = Field(default_factory=dict)

    def to_card_text(self) -> str:
        """Compact, embedding-friendly rendering of the table."""
        cols = ", ".join(f"{c.name} {c.type}" for c in self.columns)
        pk = ", ".join(self.primary_key) or "-"
        fks = (
            "; ".join(
                f"{fk['column']} -> {fk['ref_table']}.{fk['ref_column']}"
                for fk in self.foreign_keys
            )
            or "-"
        )
        samples = "; ".join(
            f"{col}: {', '.join(vals[:5])}" for col, vals in self.sample_values.items() if vals
        )
        return (
            f"TABLE {self.table}\n"
            f"columns: {cols}\n"
            f"primary key: {pk}\n"
            f"foreign keys: {fks}\n"
            f"sample values: {samples}"
        )


class Exemplar(BaseModel):
    question: str
    sql: str


class RetrievedContext(BaseModel):
    tables: list[TableCard] = Field(default_factory=list)
    exemplars: list[Exemplar] = Field(default_factory=list)

    def schema_text(self) -> str:
        return "\n\n".join(t.to_card_text() for t in self.tables)

    def exemplar_text(self) -> str:
        return "\n\n".join(f"Q: {e.question}\nSQL: {e.sql}" for e in self.exemplars)


# --------------------------------------------------------------------------- #
# Agent outputs
# --------------------------------------------------------------------------- #


class Plan(BaseModel):
    """Structured intent produced by the Planner (dialect-agnostic)."""

    intent: str = Field(description="One-line restatement of what the user wants")
    metrics: list[str] = Field(default_factory=list, description="e.g. 'sum(order_items.price)'")
    dimensions: list[str] = Field(default_factory=list, description="group-by columns")
    filters: list[str] = Field(default_factory=list, description="natural-language filter clauses")
    time_range: str | None = None
    sort: str | None = None
    limit: int | None = None
    tables: list[str] = Field(default_factory=list, description="candidate tables/joins")
    needs_clarification: bool = False
    clarifying_question: str | None = None


class SQLDraft(BaseModel):
    sql: str
    tables_used: list[str] = Field(default_factory=list)
    rationale: str = ""


class ExecResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    rowcount: int = 0
    duration_ms: float = 0.0
    truncated: bool = False


class ExecError(BaseModel):
    error_type: Literal["invalid_sql", "forbidden", "too_expensive", "timeout", "db_error"]
    message: str


class Verdict(BaseModel):
    status: Literal["ok", "retry", "abort"]
    critique: str = ""  # fed back to the Writer on a retry
    reason: str = ""


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "area", "scatter"]
    x: str
    y: str


class Answer(BaseModel):
    text: str
    confidence: float = 0.0
    sql: str | None = None
    chart: ChartSpec | None = None
    cost_usd: float = 0.0
    low_confidence: bool = False


# --------------------------------------------------------------------------- #
# Trace + run state
# --------------------------------------------------------------------------- #


class TraceStep(BaseModel):
    step: str
    agent: str
    status: str = "ok"
    latency_ms: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)
    phoenix_trace_id: str | None = None


class RunState(BaseModel):
    """Canonical state threaded through the pipeline / graph.

    `sql_drafts`, `exec_results`, `verdicts` and `trace` are accumulators: nodes
    return a single-element list and the `operator.add` reducer appends it.
    """

    question: str
    clarification_response: str | None = None

    retrieved: RetrievedContext | None = None
    plan: Plan | None = None

    sql_drafts: Annotated[list[SQLDraft], operator.add] = Field(default_factory=list)
    exec_results: Annotated[list[ExecResult | ExecError], operator.add] = Field(
        default_factory=list
    )
    verdicts: Annotated[list[Verdict], operator.add] = Field(default_factory=list)

    retry_count: int = 0
    trace: Annotated[list[TraceStep], operator.add] = Field(default_factory=list)

    answer: Answer | None = None
    aborted: bool = False

    # convenience accessors ------------------------------------------------- #
    @property
    def last_sql(self) -> SQLDraft | None:
        return self.sql_drafts[-1] if self.sql_drafts else None

    @property
    def last_exec(self) -> ExecResult | ExecError | None:
        return self.exec_results[-1] if self.exec_results else None

    @property
    def last_verdict(self) -> Verdict | None:
        return self.verdicts[-1] if self.verdicts else None


class AgentResult(BaseModel):
    """What the surfaces (FastAPI / MCP) return to a caller."""

    answer: Answer | None = None
    needs_clarification: bool = False
    clarifying_question: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    thread_id: str | None = None
