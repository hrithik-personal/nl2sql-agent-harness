"""Orchestration seam.

Defines the dependency protocols (the agents + retriever + executor) and the
`Orchestrator` interface. Both engines — the LangGraph engine (v1) and the
hand-written state machine (later) — consume the exact same `Deps`, so they are
interchangeable and the whole pipeline is testable with fakes (no DB, no keys).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Protocol

from nl2sql.config import Settings, get_settings
from nl2sql.llm import LLMUsage
from nl2sql.schemas import (
    Answer,
    ExecError,
    ExecResult,
    Plan,
    RetrievedContext,
    RunState,
    SQLDraft,
    Verdict,
)


class Retriever(Protocol):
    def __call__(self, question: str) -> RetrievedContext: ...


class Planner(Protocol):
    def __call__(
        self, question: str, retrieved: RetrievedContext, clarification: str | None
    ) -> tuple[Plan, LLMUsage]: ...


class Writer(Protocol):
    def __call__(
        self, plan: Plan, retrieved: RetrievedContext, critique: str | None
    ) -> tuple[SQLDraft, LLMUsage]: ...


class Executor(Protocol):
    def __call__(self, sql: str, allowed_tables: set[str]) -> ExecResult | ExecError: ...


class Verifier(Protocol):
    def __call__(
        self, question: str, plan: Plan, sql: str, result: ExecResult | ExecError
    ) -> tuple[Verdict, LLMUsage]: ...


class Explainer(Protocol):
    def __call__(
        self, question: str, sql: str, result: ExecResult, verdict: Verdict
    ) -> tuple[Answer, LLMUsage]: ...


@dataclass
class Deps:
    retriever: Retriever
    planner: Planner
    writer: Writer
    executor: Executor
    verifier: Verifier
    explainer: Explainer
    settings: Settings = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()


class Orchestrator(abc.ABC):
    """Common interface implemented by every engine."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    @abc.abstractmethod
    def run(self, question: str, thread_id: str | None = None) -> RunResult:
        """Run the pipeline for one question (fresh run)."""

    @abc.abstractmethod
    def resume(self, thread_id: str, answer: str) -> RunResult:
        """Resume a run that paused on a clarifying question."""


@dataclass
class RunResult:
    state: RunState
    interrupted: bool = False
    clarifying_question: str | None = None
    thread_id: str | None = None
