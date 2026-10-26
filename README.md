# nl2sql-agent-harness

A multi-agent **Text-to-SQL analytics agent** over an e-commerce/logistics Postgres database.
Built to demonstrate production agent-engineering competencies: a multi-agent self-correction
loop (LangGraph), RAG schema-linking, a sandboxed read-only SQL executor, evals-in-CI, model
routing + cost awareness (LiteLLM), tool-schema validation, resilience, and observability (OTel
→ Phoenix).

> Full design: [`docs/PLAN.md`](docs/PLAN.md).

## Pipeline

```
Planner → Writer → Executor(sandbox) → Verifier → (retry ↺) → Explainer
```

## Status
Phases 1–2 implemented and **verified end-to-end against the live stack** (Postgres + LiteLLM +
Phoenix via `docker compose`):

- **27 unit tests green, ruff clean** (guard, engine, comparator, permissions — no services needed).
- **Full pipeline runs live** over FastAPI (`/ask`) and in-process: NL → plan → SQL → sandboxed
  execute → verify → explain, with per-agent **model routing** (Sonnet planner/verifier, Haiku
  writer/explainer) and **cost tracking (~$0.012/query)**.
- **Sandbox proven on the live DB**: DELETE, CTE-hidden DELETE and stacked DROP are rejected, and a
  raw `UPDATE` as `analyst_ro` is blocked by the read-only transaction.
- **Eval harness is deterministic & offline**: 20-item suite replays from cassettes (no API key),
  **61.1% execution-match / 100% valid-SQL**, gated in CI. See [`docs/EVAL.md`](docs/EVAL.md) for the
  honest failure analysis and [`docs/FAILURE_MODES.md`](docs/FAILURE_MODES.md).

Remaining: Phase 3 stretch (hand-written engine, agentic-RAG toggle, LLM-as-judge) and a demo video.

## Quickstart
```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
docker compose up -d            # Postgres (shop+app) + LiteLLM + Phoenix
make seed                       # deterministic Faker data
make index                      # schema catalog + embeddings (pgvector)
make api                        # FastAPI  → localhost:8000
make run                        # Streamlit → localhost:8501
make eval                       # eval harness → scorecard
make test                       # unit + cassette-replayed tests
```
