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
Phases 1–2 implemented. **27 tests green, ruff clean** (verified without external services via
fakes + the execution-match comparator):
- SQL-safety guard (single-SELECT, CTE-hidden-DML rejection, LIMIT injection)
- LangGraph engine: happy path, self-correction loop, retry budget, **wall-clock budget**, clarify interrupt/resume
- execution-match comparator; tool permission matrix

Written and wired, pending a live DB + API key to run end-to-end: agents, pgvector retriever,
DB-side of the sandbox executor, FastAPI, Streamlit, MCP server (stdio + HTTP), eval harness,
`docker-compose`, LiteLLM routing/fallback, OTel→Phoenix. See [`docs/FAILURE_MODES.md`](docs/FAILURE_MODES.md).

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
