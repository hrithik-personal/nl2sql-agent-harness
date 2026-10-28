# nl2sql-agent-harness

**Ask a question about your data in plain English; get back a trustworthy answer, the SQL behind it, and a full trace of how the agents got there.**

`nl2sql-agent-harness` is a multi-agent **Text-to-SQL analytics agent** over an e-commerce / logistics
Postgres database. A small team of LLM "agents" (plan → write → execute → verify → explain) collaborate
in a self-correcting loop, backed by a sandboxed read-only SQL executor, retrieval over the database
schema, and the production plumbing you'd expect around a real agent: **evals that run in CI**,
**per-agent model routing and budgets**, **structured tool contracts**, **graceful failure handling**,
and **end-to-end observability**.

<p align="center">
  <img src="docs/assets/ui-answer.png" alt="Asking a question and getting an answer with confidence and cost" width="420">
  <img src="docs/assets/ui-sql-trace.png" alt="The generated SQL and the per-agent execution trace" width="420">
</p>

> It's built as a portfolio-grade reference for **production agent engineering** — the emphasis is less
> on squeezing out the last accuracy point and more on everything that makes an agent *operable*:
> measured, routed, budgeted, sandboxed, observable, and honest about its own failures.

---

## How to read this README

This document goes from the big picture to the details. If you're skimming, the first few sections are
enough; each later section drills into one piece.

| Section | What you'll get |
|---|---|
| [What it does](#what-it-does) | The idea in plain English, and a worked example. |
| [Features at a glance](#features-at-a-glance) | A scannable list of everything that's built. |
| [Quick start](#quick-start) | Copy-paste commands to run the whole thing locally. |
| [How it works](#how-it-works) | The agent pipeline, step by step. |
| [Architecture](#architecture) | Components, the data model, and the LangGraph engine. |
| [The production-engineering story](#the-production-engineering-story) | One-line summary of each competency (evals-in-CI, routing & budgets, sandbox, resilience, observability…), linking to the [deep dive](docs/ENGINEERING.md). |
| [Surfaces](#surfaces-how-you-call-it) | The REST API, MCP server, and Streamlit UI. |
| [Project layout](#project-layout) | Where everything lives. |
| [Testing & evaluation](#testing--evaluation) | How correctness is measured and gated. |
| [Tech stack & status](#tech-stack) | Libraries, and what's done vs. planned. |
| [Further reading](#further-reading) | The deeper design docs. |

---

## What it does

You ask a question like *"Which 5 product categories have the most orders?"* and the system:

1. **Finds the relevant tables** by semantic search over the schema (you don't hand it the schema).
2. **Plans** what the query needs, and asks a clarifying question if the request is ambiguous.
3. **Writes** the SQL.
4. **Executes it safely** in a read-only sandbox (no query can ever modify data).
5. **Verifies** the result actually answers the question — and if not, **loops back and tries again**
   with the failure as feedback.
6. **Explains** the answer in plain English, and reports its **confidence** and the **dollar cost** of
   the run.

Every run produces a structured trace, so you can always see *why* you got the answer you did:

```
Question: "Which 5 product categories have the most orders?"
Answer:   "The top 5 are Grocery (753), Sports (709), Home (640), Beauty (624), Apparel (613)."
SQL:      SELECT p.category, count(DISTINCT o.id) AS order_count
          FROM orders o JOIN order_items oi ON oi.order_id = o.id
          JOIN products p ON p.id = oi.product_id
          GROUP BY p.category ORDER BY order_count DESC LIMIT 5
Confidence: 95%   Cost: $0.012
Trace:    retrieve → plan → write → execute → verify → explain   (each with latency, tokens, cost)
```

The data is a synthetic but realistic **e-commerce / logistics** database (sellers, products, customers,
orders, order_items, payments, refunds, couriers, shipments, …) generated deterministically with Faker,
so anyone who clones the repo gets the exact same numbers.

---

## Features at a glance

**The agent**
- 🧠 **Multi-agent self-correction loop** — Planner → Writer → Executor → Verifier → (retry ↺) → Explainer, orchestrated with **LangGraph** (typed state, reducers, conditional edges, checkpointing, interrupts).
- 🔎 **RAG schema-linking** — the agent retrieves the relevant tables/columns via **pgvector** similarity + foreign-key expansion, instead of being handed the whole schema.
- ❓ **Clarifying questions** — ambiguous questions pause the graph (`interrupt()`) and ask one question, then resume from a checkpoint.
- 💬 **Honest answers** — every answer carries a confidence score and degrades to a low-confidence answer rather than crashing or guessing.

**The production layer (the point of the project)**
- ✅ **Evals in CI** — a labelled question set is scored on **execution-match** and gated on a regression threshold in GitHub Actions. Runs **offline and deterministically** via recorded "cassettes" (no API key needed in CI).
- 🔀 **Model routing + per-agent budgets** — one Anthropic key behind a **LiteLLM** proxy; each agent gets its own **virtual key**, its own **model** (stronger for planning/verifying, cheaper for writing/explaining), and its own **spend budget**, visible in a live dashboard.
- 🛡️ **Sandboxed SQL executor** — three independent layers (SQL AST guard + read-only transaction + least-privilege DB role) make destructive queries impossible; an `EXPLAIN` cost gate blocks runaway queries.
- 🔁 **Resilience / failure handling** — bounded semantic retries, transient-error backoff, **per-key model timeouts**, **cross-tier Claude fallback** (Sonnet↔Haiku), and a documented catalogue of [failure modes](docs/FAILURE_MODES.md) each with a reproducing test.
- 🧰 **Typed tool contracts + permissions** — every tool has a strict Pydantic input schema and a permission matrix; the dangerous `run_sql` tool is **off by default**.
- 📊 **Observability** — OpenTelemetry traces → **Arize Phoenix**: one span per agent, LLM token/cost spans nested under each.
- 🧪 **Deterministic everything** — fixed seeds, `temperature=0`, positional tiebreak ordering, occurrence-indexed LLM cassettes, and a **pinned retrieved context** make offline runs byte-identical on any machine (so the eval gate is stable in CI).

**Surfaces**
- 🌐 **FastAPI** REST API · 🔌 **MCP server** (stdio + Streamable HTTP) · 🖥️ **Streamlit** UI.

---

## Quick start

**Prerequisites:** Docker Desktop, Python 3.11+, and an Anthropic API key (only needed for *live* runs —
the tests and evals run without one).

```bash
# 1. clone + configure
git clone <your-fork-url> nl2sql-agent-harness && cd nl2sql-agent-harness
cp .env.example .env                 # then put your ANTHROPIC_API_KEY in .env

# 2. bring up the stack: Postgres (+pgvector) + LiteLLM proxy + Phoenix
docker compose up -d

# 3. python environment
make venv

# 4. mint one budgeted, model-scoped LiteLLM virtual key per agent (writes them to .env)
make litellm-keys

# 5. load deterministic data + build the schema-embedding index
make seed
make index

# 6. run it
make api       # FastAPI        → http://localhost:8000  (/docs for Swagger)
make run       # Streamlit UI   → http://localhost:8501
make mcp       # MCP server over stdio   (make mcp-http for Streamable HTTP)
```

**Verify without spending anything** (offline, no API key):

```bash
make test      # 27 unit + cassette-replayed tests
make eval      # the eval harness → a scorecard in evals/report.md
```

Dashboards that come up with the stack:
- **LiteLLM admin UI** → http://localhost:4000/ui (login `admin` / your `LITELLM_MASTER_KEY`)
- **Arize Phoenix** (traces) → http://localhost:6006

> **Note:** on a pre-existing Postgres volume the `litellm` database isn't auto-created — run
> `make litellm-db` once before `make litellm-keys`. A fresh `docker compose up` creates it automatically.

---

## How it works

At the core is a loop of specialised agents. Each agent does one job and hands structured state to the
next; a **Verifier** decides whether the answer is good enough or the **Writer** should try again.

```mermaid
flowchart LR
    Q([Question]) --> R[Retriever<br/><i>find relevant tables</i>]
    R --> P[Planner<br/><i>intent + clarify?</i>]
    P -. ambiguous .-> I[[interrupt → ask user]]
    I -. answer .-> P
    P --> W[Writer<br/><i>generate SQL</i>]
    W --> E[Executor<br/><i>sandboxed read-only</i>]
    E --> V{Verifier<br/><i>answers the question?</i>}
    V -- retry, with critique --> W
    V -- ok / give up --> X[Explainer<br/><i>NL answer + confidence + cost</i>]
    X --> A([Answer])
```

**Why separate Planner and Writer?** Planning (what tables, what measure, is it ambiguous?) and SQL
authoring are different skills with different failure modes. Splitting them lets each use a different
model and makes retries targeted — the Writer can be corrected by the Verifier without re-planning.

**The self-correction loop in one sequence:**

```mermaid
sequenceDiagram
    participant E as Engine
    participant W as Writer
    participant X as Executor
    participant V as Verifier
    loop until ok OR retry budget / wall-clock exhausted
        E->>W: write(plan, schema, previous critique?)
        W-->>E: SQL draft
        E->>X: execute(sql)  [read-only role, EXPLAIN gate, 1 SELECT, timeout]
        X-->>E: rows  /  structured error
        E->>V: verify(result vs. intent)
        V-->>E: ok | retry(+critique) | abort
    end
    E->>E: explain → answer + confidence + $cost; persist trace & checkpoint
```

If the loop runs out of retries or exceeds its time budget, it doesn't crash or loop forever — it
returns a clearly-marked **low-confidence** answer.

---

## Architecture

### Components

| Component | Responsibility | Lives in |
|---|---|---|
| **Orchestrator** | Runs the agent graph; owns retries, budgets, checkpoints. Pluggable behind a `Protocol`. | [`nl2sql/orchestration/`](nl2sql/orchestration/) |
| **Agents** | Planner / Writer / Verifier / Explainer — each a plain function `(state) → (result, usage)`. | [`nl2sql/agents/`](nl2sql/agents/) |
| **Retriever** | pgvector similarity over schema "cards" + exemplars + FK expansion. | [`nl2sql/retrieve.py`](nl2sql/retrieve.py) |
| **Executor (sandbox)** | Runs the SQL under three independent safety layers. | [`nl2sql/executor.py`](nl2sql/executor.py) |
| **SQL guard** | sqlglot AST check: single SELECT, no DML/DDL (even CTE-hidden), injects LIMIT + deterministic ORDER BY. | [`nl2sql/sqlguard.py`](nl2sql/sqlguard.py) |
| **LLM choke point** | The *only* place that calls a model: routing, cost accounting, structured output, cassettes. | [`nl2sql/llm.py`](nl2sql/llm.py) |
| **Telemetry** | OpenTelemetry → OTLP → Phoenix. | [`nl2sql/telemetry.py`](nl2sql/telemetry.py) |
| **Tool contracts** | Pydantic tool-input schemas + permission matrix. | [`nl2sql/tools/`](nl2sql/tools/) |
| **Surfaces** | FastAPI, MCP server, Streamlit — thin adapters over one shared core. | [`api/`](api/), [`mcp_server/`](mcp_server/), [`app/`](app/) |

### The data model

Two Postgres schemas on one database:
- **`shop`** — the analytics target the agent queries (11 tables: `sellers`, `products`, `customers`,
  `addresses`, `orders`, `order_items`, `payments`, `refunds`, `couriers`, `shipments`, `tracking_events`).
  The agent connects to this schema only through a **least-privilege read-only role** (`analyst_ro`).
- **`app`** — the system's own state: schema-card embeddings (pgvector), exemplars, run traces, and
  LangGraph checkpoints.

A separate **`litellm`** database holds the proxy's own state (virtual keys, budgets, spend).

### The orchestration engine (LangGraph)

The engine is deliberately built on LangGraph *primitives* rather than its prebuilt agents, so the
interesting production behaviour is explicit and swappable:

- **Typed state** (`RunState`, a Pydantic model) flows through the graph.
- **Reducers** (`Annotated[list, operator.add]`) make `sql_drafts` / `verdicts` / `trace` **append**
  across loop iterations instead of overwriting — so the full history is always available.
- A **conditional edge** encodes the ok / retry / abort decision.
- A **checkpointer** (in-memory for tests, PostgresSaver in prod) persists state per `thread_id`, which
  is what makes interrupts resumable and crashed runs recoverable.
- **`interrupt()` + `Command(resume=…)`** implement the clarifying-question human-in-the-loop.
- **`RetryPolicy`** adds backoff on transient errors; **`recursion_limit`** is a hard step cap.

The orchestrator sits behind an `Orchestrator` interface, so a hand-written state-machine engine can be
dropped in later for comparison. The agents themselves are framework-free, so they're trivial to unit
test with fakes.

---

## The production-engineering story

This is the heart of the project — the plumbing that makes the agent *operable*. Each item below is one
competency you'd be expected to demonstrate for a production agent; here's the one-line version, with the
full deep dive (code, config, and the dashboard screenshots) in **[docs/ENGINEERING.md](docs/ENGINEERING.md)**.

| Competency | In short | Deep dive |
|---|---|---|
| **Evals, gated in CI** | A labelled set scored on execution-match, replayed from cassettes (offline, no key), gated on a regression threshold in GitHub Actions. Honest baseline: **61.1% exec-match / 100% valid-SQL**. | [§1](docs/ENGINEERING.md#1-evaluation-gated-in-ci) · [EVAL.md](docs/EVAL.md) |
| **Routing & per-agent budgets** | One Anthropic key behind a LiteLLM proxy; each agent gets its own virtual key, model (Sonnet for judgement, Haiku for authoring), and 30-day budget — a key can't call another agent's model. | [§2](docs/ENGINEERING.md#2-model-routing-budgets--cost-awareness) |
| **How LiteLLM is wired in** | We run the LiteLLM **proxy server** and call it over HTTP (the `litellm_proxy/` route) — which is what unlocks per-key budgets, not the in-process SDK. | [§3](docs/ENGINEERING.md#3-how-litellm-is-wired-in-sdk-vs-proxy) |
| **Timeouts & fallback** | Per-key timeouts (Sonnet 30s / Haiku 20s) fail a hang fast; **Claude-only cross-tier fallback** (Sonnet↔Haiku) covers a single model being overloaded. | [§4](docs/ENGINEERING.md#4-timeouts--fallback-resilience-at-the-model-layer) |
| **SQL sandbox (defense in depth)** | Three independent layers — AST guard (single SELECT, no hidden DML) + read-only transaction + least-privilege `analyst_ro` role — plus an `EXPLAIN` cost gate. | [§5](docs/ENGINEERING.md#5-the-sql-sandbox-defense-in-depth) |
| **Resilience (whole-run)** | Each failure handled where it belongs: semantic retry, transient-error backoff, graceful low-confidence abort, and resumable runs via the checkpointer. | [§6](docs/ENGINEERING.md#6-resilience--failure-handling-whole-run) · [FAILURE_MODES.md](docs/FAILURE_MODES.md) |
| **Typed tool contracts & permissions** | Every tool has a strict Pydantic input schema and a permission matrix; the dangerous `run_sql` is off by default (`403`). | [§7](docs/ENGINEERING.md#7-typed-tool-contracts--permissions) |
| **Observability** | OpenTelemetry → Arize Phoenix: one span per agent, LLM token/cost spans nested underneath — the whole run as a waterfall. | [§8](docs/ENGINEERING.md#8-observability) |

---

## Surfaces (how you call it)

One shared core, three thin adapters — so behaviour is identical however you reach it:

- **FastAPI** ([`api/`](api/)) — `POST /ask`, `POST /ask/resume` (answer a clarifying question),
  `GET /schema`, `GET /health`, and a `run_sql` endpoint that 403s unless explicitly enabled. Swagger at
  `/docs`.
- **MCP server** ([`mcp_server/`](mcp_server/)) — exposes `get_schema`, `ask`, `ask_resume`, `run_sql`
  as tools over **stdio** (for desktop LLM clients) and **Streamable HTTP**, with validated schemas.
- **Streamlit** ([`app/`](app/)) — the UI in the screenshots: answer, SQL, result table, suggested
  chart, confidence, cost, and the agent trace.

---

## Project layout

```
nl2sql-agent-harness/
├─ nl2sql/                     # the library core
│  ├─ orchestration/           # Orchestrator interface + LangGraph engine
│  ├─ agents/                  # planner, writer, verifier, explainer
│  ├─ tools/                   # Pydantic tool contracts + permission matrix
│  ├─ llm.py                   # the single LLM choke point (routing, cost, cassettes)
│  ├─ retrieve.py  catalog.py  # pgvector retrieval + schema introspection
│  ├─ executor.py  sqlguard.py # the sandboxed SQL executor + AST guard
│  ├─ telemetry.py             # OpenTelemetry → Phoenix
│  ├─ schemas.py  config.py    # Pydantic state/models + settings
│  └─ pipeline.py              # default wiring used by all surfaces
├─ api/            app/        # FastAPI + Streamlit
├─ mcp_server/                 # MCP server (stdio + HTTP)
├─ db/                         # shop DDL, roles, Faker seed, app/litellm init
├─ evals/                      # dataset, runner, execution-match comparator, report
├─ tests/  tests/cassettes/    # unit tests + recorded LLM exchanges
├─ litellm/config.yaml         # model routing + fallbacks
├─ scripts/                    # provisioning helpers (virtual keys)
├─ docs/                       # ENGINEERING, PLAN, EVAL, FAILURE_MODES, screenshots
├─ docker-compose.yml  Makefile  .github/workflows/ci.yml
└─ CLAUDE.md                   # guide for AI coding agents working in this repo
```

---

## Testing & evaluation

- **Unit tests** (`make test`) — the SQL guard, the engine's routing/budget logic, the execution-match
  comparator, and tool permissions. No services required; LLM calls are served from cassettes. **27
  tests, green.**
- **Eval harness** (`make eval`) — execution-match scorecard over the labelled set; writes a per-item
  table to `evals/report.md`; **gated in CI**. See [docs/EVAL.md](docs/EVAL.md).
- **Cassettes** — recorded LLM exchanges keyed by a hash of `(agent, model, messages, schema)` plus an
  occurrence index (the self-correction loop can issue the same prompt twice in one run). `LLM_MODE`
  switches between `live`, `record`, and `replay`.
- **Pinned retrieval** — the retrieval step is recorded/replayed too (`tests/cassettes/retrieval/`).
  Ranking tables by embedding similarity is machine-sensitive, so freezing the retrieved context keeps
  replay byte-identical across machines — that's what makes the eval gate reliable on CI hardware, with
  no embedding model needed offline.

---

## Tech stack

**Python 3.11+** · **LangGraph** (orchestration) · **Pydantic** (typed state, structured outputs, tool
schemas) · **LiteLLM** (model routing, budgets, fallback) · **Postgres 16 + pgvector** (data + vector
store) · **sentence-transformers** (`BAAI/bge-small-en-v1.5` embeddings) · **sqlglot** (SQL AST guard) ·
**OpenTelemetry + Arize Phoenix** (observability) · **FastAPI** · **MCP** (FastMCP) · **Streamlit** ·
**Docker Compose** · **GitHub Actions** · **ruff** · **pytest**.

### Status

- **Phase 1 — demoable core:** ✅ data + schema, retrieval, the 4 agents, the LangGraph engine, the SQL
  sandbox, and the surfaces. Verified end-to-end live.
- **Phase 2 — the production layer:** ✅ eval harness in CI, model routing + per-agent budgets, tool
  contracts + permissions, resilience, observability, MCP over stdio + HTTP.
- **Phase 3 — stretch (planned):** a hand-written state-machine engine for comparison, an agentic-RAG
  toggle, and LLM-as-judge for the Explainer.

---

## Further reading

- **[docs/ENGINEERING.md](docs/ENGINEERING.md)** — the production-engineering deep dive: evals-in-CI, routing & budgets, how LiteLLM is wired in, timeouts & fallback, the SQL sandbox, resilience, tool contracts, and observability (with the dashboard screenshots).
- **[docs/PLAN.md](docs/PLAN.md)** — the full design doc: decisions, trade-offs, and the architecture in depth.
- **[docs/EVAL.md](docs/EVAL.md)** — how correctness is measured, and an honest analysis of what fails and why.
- **[docs/FAILURE_MODES.md](docs/FAILURE_MODES.md)** — the catalogue of failure modes and mitigations.
- **[CLAUDE.md](CLAUDE.md)** — orientation for AI coding agents (and a fast onboarding for humans).

---

Designed and built by **Hrithik Kumar**. Licensed under the [MIT License](LICENSE).
