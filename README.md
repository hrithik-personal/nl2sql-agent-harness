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
Phase 1 (core) in progress. Verified so far: SQL-safety guard, LangGraph orchestration engine
(happy path, self-correction loop, retry budget, clarify interrupt/resume).

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
