"""Eval harness.

Runs each labeled question through the agent (LLM in replay/cassette mode),
executes both the agent's SQL and the gold SQL against the seeded DB, and scores
by execution-match. Ambiguous/failure items are scored on behaviour
(clarify / low-confidence abort). Emits a scorecard and gates on a threshold.

    make eval            # LLM_MODE=replay, needs the DB up
    EVAL_THRESHOLD=0.8 make eval
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from evals.compare import execution_match
from nl2sql.executor import SandboxExecutor
from nl2sql.pipeline import build_engine
from nl2sql.retrieve import PgVectorRetriever
from nl2sql.schemas import ExecResult

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"
REPORT = Path(__file__).resolve().parent / "report.md"


@dataclass
class Row:
    id: str
    category: str
    passed: bool
    retries: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    valid_sql: bool = False
    note: str = ""


@dataclass
class Scorecard:
    rows: list[Row] = field(default_factory=list)

    def execution_match_rate(self) -> float:
        answer_rows = [r for r in self.rows if r.category not in ("ambiguous", "failure")]
        return _rate(r.passed for r in answer_rows) if answer_rows else 0.0

    def behaviour_rate(self) -> float:
        rows = [r for r in self.rows if r.category in ("ambiguous", "failure")]
        return _rate(r.passed for r in rows) if rows else 1.0

    def valid_sql_rate(self) -> float:
        rows = [r for r in self.rows if r.category not in ("ambiguous", "failure")]
        return _rate(r.valid_sql for r in rows) if rows else 0.0

    def avg_retries(self) -> float:
        return round(statistics.mean([r.retries for r in self.rows]), 2) if self.rows else 0.0

    def latency_p50(self) -> float:
        lat = sorted(r.latency_ms for r in self.rows)
        return round(statistics.median(lat), 1) if lat else 0.0

    def latency_p95(self) -> float:
        lat = sorted(r.latency_ms for r in self.rows)
        return round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else 0.0

    def avg_cost(self) -> float:
        return round(statistics.mean([r.cost_usd for r in self.rows]), 6) if self.rows else 0.0


def _rate(bools) -> float:
    bools = list(bools)
    return round(sum(1 for b in bools if b) / len(bools), 3) if bools else 0.0


def _rows_of(res) -> list[list] | None:
    return res.rows if isinstance(res, ExecResult) else None


def run() -> Scorecard:
    items = [json.loads(ln) for ln in DATASET.read_text().splitlines() if ln.strip()]
    engine = build_engine()
    executor = SandboxExecutor()
    allowed = set(PgVectorRetriever().cards)

    card = Scorecard()
    for it in items:
        res = engine.run(it["question"])
        st = res.state
        latency = round(sum(s.latency_ms for s in st.trace), 1)
        cost = st.answer.cost_usd if st.answer else 0.0
        retries = st.retry_count

        if it["expect"] == "clarify":
            card.rows.append(Row(it["id"], it["category"], res.interrupted,
                                 retries, latency, cost, note="clarify"))
            continue
        if it["expect"] == "abort":
            ok = bool(st.answer and st.answer.low_confidence)
            card.rows.append(Row(it["id"], it["category"], ok, retries, latency, cost,
                                 note="abort"))
            continue

        agent_sql = st.answer.sql if st.answer else None
        agent_res = executor(agent_sql, allowed) if agent_sql else None
        gold_res = executor(it["gold_sql"], allowed)
        a_rows, g_rows = _rows_of(agent_res), _rows_of(gold_res)
        valid = a_rows is not None
        passed = valid and g_rows is not None and execution_match(a_rows, g_rows)
        card.rows.append(Row(it["id"], it["category"], passed, retries, latency, cost, valid))

    return card


def write_report(card: Scorecard) -> str:
    lines = [
        "# Eval scorecard", "",
        f"- **execution-match rate**: {card.execution_match_rate():.1%}",
        f"- behaviour (clarify/abort) rate: {card.behaviour_rate():.1%}",
        f"- valid-SQL rate: {card.valid_sql_rate():.1%}",
        f"- avg retries: {card.avg_retries()}",
        f"- latency p50/p95: {card.latency_p50()} / {card.latency_p95()} ms",
        f"- avg cost: ${card.avg_cost()}", "",
        "| id | category | passed | retries | valid_sql | $ |",
        "|---|---|---|---|---|---|",
    ]
    for r in card.rows:
        lines.append(
            f"| {r.id} | {r.category} | {'✅' if r.passed else '❌'} | "
            f"{r.retries} | {r.valid_sql} | {r.cost_usd:.4f} |"
        )
    text = "\n".join(lines) + "\n"
    REPORT.write_text(text)
    return text


def main() -> None:
    threshold = float(os.getenv("EVAL_THRESHOLD", "0.7"))
    card = run()
    print(write_report(card))
    emr = card.execution_match_rate()
    if emr < threshold:
        print(f"FAIL: execution-match {emr:.1%} < threshold {threshold:.0%}")
        sys.exit(1)
    print(f"PASS: execution-match {emr:.1%} >= threshold {threshold:.0%}")


if __name__ == "__main__":
    main()
