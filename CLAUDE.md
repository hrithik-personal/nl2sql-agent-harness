# CLAUDE.md

Orientation for AI coding agents (and a fast onboarding for humans) working in this repo.
Read this before making changes — it captures the invariants that aren't obvious from any single file.

## What this is

A multi-agent **Text-to-SQL** system over an e-commerce/logistics Postgres DB. A LangGraph loop of
agents (Planner → Writer → Executor → Verifier → (retry) → Explainer) turns an English question into a
verified answer + the SQL + a trace. The project's real purpose is to demonstrate **production agent
engineering**: evals-in-CI, model routing + budgets, a sandboxed SQL executor, resilience, tool
contracts, and observability. See [README.md](README.md) for the full tour and [docs/PLAN.md](docs/PLAN.md)
for the design rationale.

Package: `nl2sql`. Python 3.11+.

## Documentation map (where to read, by topic)

Prose docs are layered: the README is the tour, and each topic deep-dives in its own file. When you need
background before changing something, read the matching doc first.

| Topic | Doc |
|---|---|
| Project tour, quick start, features | [README.md](README.md) |
| Production-engineering deep dive — evals-in-CI, model routing & budgets, **how LiteLLM is wired in (proxy/HTTP, not SDK)**, **timeouts & Claude-only fallback**, SQL sandbox, resilience, tool contracts, observability | [docs/ENGINEERING.md](docs/ENGINEERING.md) |
| How correctness is measured + honest failure analysis | [docs/EVAL.md](docs/EVAL.md) |
| Catalogue of failure modes and mitigations | [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md) |
| Full design doc: decisions, trade-offs, architecture | [docs/PLAN.md](docs/PLAN.md) |

Keep this map and the README's section map in sync when you add or move a doc.

## Architecture map (where to look)

| You want to… | Go to |
|---|---|
| Change how the graph runs (nodes, edges, retries, budgets) | `nl2sql/orchestration/langgraph_engine.py` |
| Change what an agent does / its prompt | `nl2sql/agents/{planner,writer,verifier,explainer}.py` |
| Change how a model is called, routed, or costed | `nl2sql/llm.py` (the **only** place that calls an LLM) |
| Change how retrieval is recorded/replayed | `nl2sql/retrieval_cache.py` (pins the retrieved context offline) |
| Change SQL safety rules | `nl2sql/sqlguard.py` (AST) and `nl2sql/executor.py` (runtime) |
| Change retrieval / schema linking | `nl2sql/retrieve.py`, `nl2sql/catalog.py` |
| Add/alter typed state or settings | `nl2sql/schemas.py`, `nl2sql/config.py` |
| Change tool input schemas / permissions | `nl2sql/tools/contracts.py`, `nl2sql/tools/permissions.py` |
| Change a surface | `api/main.py`, `mcp_server/server.py`, `app/streamlit_app.py` |
| Change data / schema / roles / seed | `db/` |
| Change evals | `evals/` |
| Change model routing / fallbacks | `litellm/config.yaml` |

All surfaces go through `nl2sql/pipeline.py` (`build_engine`, `build_default_deps`) so they share one
orchestrator and identical behaviour. Agents are framework-free functions `(state) → (result, usage)`;
the LangGraph dependency lives only in the orchestration layer, behind the `Orchestrator` Protocol in
`nl2sql/orchestration/base.py`.

## Invariants — don't break these

1. **One LLM choke point.** Every model call goes through `nl2sql/llm.py` (`complete_structured`). Never
   import `litellm` / an SDK or call a model anywhere else — routing, per-agent keys, cost accounting,
   structured-output parsing, and the cassette layer all live here and would be bypassed. The call uses
   the litellm SDK only as a **thin HTTP client to the LiteLLM proxy** (`model="litellm_proxy/…"`,
   `api_base`, per-agent virtual `api_key`); per-key budgets/scoping are a proxy feature, so never switch
   to the in-process SDK route (calling the provider directly) — it would silently drop budgets and
   scoping. Timeouts and fallbacks live in `litellm/config.yaml`, not in this file.

2. **Determinism is load-bearing.** The eval suite and tests replay recorded cassettes keyed by a hash of
   `(agent, model, messages, schema)`. Anything that changes a prompt, the schema JSON, the retrieved
   context, or model ids **changes those hashes and breaks replay**. If you change any of them, you must
   **re-record cassettes** (see below). Sources of determinism already in place — keep them:
   - `temperature=0` on every call; fixed Faker seed (`SEED=42`); deterministic `ORDER BY` injected by
     the SQL guard; **occurrence-indexed** LLM cassettes (the loop can issue the same prompt twice per run).
   - **Pinned retrieval** (`retrieval_cache.py`): embedding ranking is machine-sensitive, so in
     record/replay the retrieved context is frozen to a fixture (`tests/cassettes/retrieval/`) and served
     verbatim. This is why offline replay needs *neither the embedding model nor pgvector* and is
     identical across machines. Don't reintroduce live embedding calls into the replay path.

3. **The SQL sandbox is defense-in-depth — never weaken a layer.** (a) `sqlguard.validate_select` must
   reject anything but a single `SELECT` (incl. CTE-hidden/stacked DML); (b) the executor runs in a
   read-only transaction with a `statement_timeout`; (c) it connects as the least-privilege `analyst_ro`
   role; (d) an `EXPLAIN` cost gate runs before execution. Don't route around these or run SQL as the app
   role.

4. **Config only through `Settings`.** `nl2sql/config.py` (pydantic-settings) is the single source for
   env/config. Don't read `os.environ` directly in app code.

5. **Secrets never get committed.** `.env` is gitignored and holds the Anthropic key + LiteLLM virtual
   keys. Never commit it, never print key values, never send them anywhere. The agents never read
   `ANTHROPIC_API_KEY` directly — it lives in the LiteLLM proxy.

6. **Telemetry must never break a request.** `telemetry.py` swallows exporter errors on purpose. Keep
   span instrumentation best-effort; don't let it raise into the request path.

## Running, testing, linting

```bash
make venv          # create .venv and install (public PyPI — see gotcha below)
make test          # 27 unit + cassette-replay tests (LLM_MODE=replay, offline)
make lint          # ruff check .
make fmt           # ruff format .
make eval          # execution-match scorecard (needs the DB up; LLM_MODE=replay)
```

Keep `make test` and `make lint` green before committing. CI runs exactly these.

### LLM modes

`LLM_MODE` (env) controls `nl2sql/llm.py`:
- `replay` (default) — serve only from cassettes; a miss is a hard error. Used by tests/evals/CI.
- `record` — call the real model **and** save the exchange as a cassette.
- `live` — call the real model, ignore cassettes.

**Re-recording cassettes** (after an intentional prompt/model/retrieval change): bring up a DB, seed and
index it, then run the eval flow in `record` mode (`LLM_MODE=record python -m evals.run_evals`). This
regenerates both the LLM cassettes and the retrieval fixtures under `tests/cassettes/`. Review the diff
and commit. A spurious diff on an unrelated change means something broke determinism — investigate rather
than committing the churn. (Replay/CI then need only a seeded DB — no index, no embedding model.)

## Environment gotchas (this machine / sandboxed shells)

- **`docker` isn't on PATH** in non-interactive shells. Prefix with:
  `export PATH="$HOME/.docker/bin:$PATH"` before any `docker`/`docker compose` command.
- **Use public PyPI.** A corporate index may be configured and will 401. `make venv` already pins
  `--index-url https://pypi.org/simple/`; do the same for ad-hoc installs.
- **Postgres init scripts in `db/*.sql` run only on a fresh volume.** On an existing volume, apply changes
  manually (e.g. `make litellm-db` creates the `litellm` database).
- **LiteLLM virtual keys** require the proxy in DB-backed mode (DATABASE_URL set in compose). Mint/refresh
  with `make litellm-keys` (idempotent; rewrites `LITELLM_KEY_*` in `.env`).
- Backgrounded `uvicorn`/`streamlit` may not survive a tool-call shell; launch with `nohup … & disown` and
  verify the port with `curl` before driving it.

## Common tasks

- **Add an eval case:** append a line to `evals/dataset.jsonl` (`question` + gold `sql` + category), then
  record its cassettes (`LLM_MODE=record`) and commit both.
- **Add/change an agent prompt:** edit the agent in `nl2sql/agents/`, then re-record cassettes.
- **Add a tool:** define its Pydantic input in `nl2sql/tools/contracts.py`, add it to the permission
  matrix in `permissions.py`, then expose it in `api/` and/or `mcp_server/`.
- **Change model routing / timeouts / fallbacks:** edit `litellm/config.yaml`. Each deployment carries a
  per-key `timeout` (Sonnet roles 30s, Haiku 20s). Fallbacks are **Claude-only** (single Anthropic key):
  Sonnet roles → `claude-haiku-fallback`, Haiku roles → `claude-sonnet-fallback`. If you add/rename a
  fallback target, also add it to that agent's scoped `models` list in
  `scripts/provision_litellm_keys.py` (a key can only call models it's scoped to) and re-run
  `make litellm-keys`. If the real model id changes, update `AGENT_REAL_MODEL` in `nl2sql/llm.py` (cost
  estimation). Re-record cassettes if prompts/model ids change.

## Conventions

- Match the surrounding style; the codebase favours small, typed, framework-free functions with concise
  comments that explain *why*, not *what*.
- Pydantic models for all structured data crossing a boundary (state, tool inputs, LLM outputs).
- Keep commit messages human-readable and scoped to one logical change.
