# The production-engineering story

This is the heart of the project. The agent itself (plan → write → execute → verify → explain) is
deliberately modest; what makes this a *portfolio* piece is everything around it that makes an agent
**operable**: measured, routed, budgeted, sandboxed, observable, and honest about its own failures.

Each section below is one competency you'd be expected to demonstrate for a production agent, and how
it's implemented here. For the big picture and quick start, see the [README](../README.md); for the
design rationale, [PLAN.md](PLAN.md).

**Contents**
1. [Evaluation, gated in CI](#1-evaluation-gated-in-ci)
2. [Model routing, budgets & cost awareness](#2-model-routing-budgets--cost-awareness)
3. [How LiteLLM is wired in (SDK vs. proxy)](#3-how-litellm-is-wired-in-sdk-vs-proxy)
4. [Timeouts & fallback (resilience at the model layer)](#4-timeouts--fallback-resilience-at-the-model-layer)
5. [The SQL sandbox (defense in depth)](#5-the-sql-sandbox-defense-in-depth)
6. [Resilience & failure handling (whole-run)](#6-resilience--failure-handling-whole-run)
7. [Typed tool contracts & permissions](#7-typed-tool-contracts--permissions)
8. [Observability](#8-observability)

---

## 1. Evaluation, gated in CI

A manual "looks right to me" is not an eval. Here, a labelled set of questions (`evals/dataset.jsonl`,
covering simple / join / aggregate / time / ambiguous / **failure** cases) is scored by
**execution-match**: run the agent's SQL and a gold SQL against the seeded DB and compare the result
*sets* (order/column-insensitive, float-tolerant). Ambiguous items are scored on behaviour (did it
clarify / abort?).

The whole suite replays from **cassettes** — recorded LLM exchanges — so it runs **offline,
deterministically, and with no API key**, and it's **gated on a regression threshold in CI**
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)). The current honest baseline is **61.1%
execution-match / 100% valid-SQL**; the misses are mostly defensible interpretation differences against
a strict gold, analysed candidly in **[EVAL.md](EVAL.md)**.

> The point isn't the headline number — it's that every prompt or model change now produces a
> **measurable, regression-gated** delta.

---

## 2. Model routing, budgets & cost awareness

One Anthropic API key sits behind a **LiteLLM** proxy. Each agent authenticates with its own **virtual
key**, which is **scoped to a single model** and carries a **30-day budget** — so spend is tracked and
capped *per agent*, and the planner's key literally cannot call the writer's model.

| Agent | Model | Why |
|---|---|---|
| Planner, Verifier | Claude Sonnet | Judgement-heavy: intent, ambiguity, result-sanity |
| Writer, Explainer | Claude Haiku | Cheaper/faster: SQL authoring, phrasing |

`$/query` is computed from real token usage and surfaced in both the trace and the eval scorecard. It's
all visible in the LiteLLM admin UI:

<p align="center">
  <img src="assets/litellm-virtual-keys.png" alt="Per-agent virtual keys, each active, scoped and budgeted" width="420">
  <img src="assets/litellm-dashboard.png" alt="LiteLLM gateway overview: spend, requests, per-model leaderboard" width="420">
</p>

Mint/refresh the keys with `make litellm-keys` ([`scripts/provision_litellm_keys.py`](../scripts/provision_litellm_keys.py));
it's idempotent and rewrites the `LITELLM_KEY_*` values in `.env`.

---

## 3. How LiteLLM is wired in (SDK vs. proxy)

LiteLLM can be used two different ways, and the distinction matters:

| | LiteLLM **Python SDK** (in-process) | LiteLLM **Proxy Server** (gateway over HTTP) |
|---|---|---|
| How you call it | `litellm.completion(model="anthropic/claude-…")`, straight to the provider | A running server you reach over HTTP (OpenAI-compatible) |
| Virtual keys, **per-key budgets**, spend tracking, admin UI | ❌ not available | ✅ available (DB-backed) |

Per-key budgeting, model scoping, and the admin dashboard are **proxy-server features** — they only
exist on the HTTP route. So this project runs the proxy server (the `litellm` service in
[`docker-compose.yml`](../docker-compose.yml), DB-backed) and, from Python, uses the litellm SDK purely
as a **thin HTTP client to that proxy** — note the `litellm_proxy/` prefix in
[`nl2sql/llm.py`](../nl2sql/llm.py):

```python
litellm.completion(
    model=f"litellm_proxy/{model}",   # route to our proxy, not direct to Anthropic
    api_key=_agent_key(agent),        # the per-agent VIRTUAL key
    api_base=s.litellm_base_url,      # http://localhost:4000
    temperature=0,
)
```

Every model call therefore goes over HTTP to the gateway, which owns the real Anthropic key, the
virtual-key budgets, the model scoping, and the cost accounting. That's exactly why the per-agent
budgeting works — we're on the proxy/HTTP route, not the in-process SDK route.

`nl2sql/llm.py` is the **single choke point**: it's the only place in the codebase that calls a model.
Routing, per-agent keys, cost accounting, structured-output parsing, and the cassette record/replay
layer all live here, so nothing can bypass them.

---

## 4. Timeouts & fallback (resilience at the model layer)

Two mechanisms, both configured in [`litellm/config.yaml`](../litellm/config.yaml), guard the model call
itself:

**Per-key timeouts.** Each model deployment sets a `timeout` (Sonnet roles 30s, Haiku roles 20s).
Because each agent's virtual key is scoped to exactly one primary model, a per-deployment timeout is
effectively a **per-key (per-agent) timeout**. If a call doesn't return in time, LiteLLM fails it fast
and triggers the fallback — instead of letting the request hang on the provider's default (~600s).

**Claude-only cross-tier fallback.** We run with a single Anthropic key, so a GPT fallback would just
fail. Instead each role degrades to the *other* Claude tier:

| Primary (role) | Falls back to | Rationale |
|---|---|---|
| Sonnet (Planner, Verifier) | Haiku | Cheaper and more likely to be available when Sonnet is specifically overloaded |
| Haiku (Writer, Explainer) | Sonnet | On a retry, SQL/answer quality matters more than cost |

**What this protects against — and what it doesn't.** With one provider, fallback covers a *single model*
being rate-limited or overloaded (HTTP 429/529) or timing out. It does **not** survive a full Anthropic
outage, because all Claude models would go down together. True provider-level fallback needs a second
provider key (e.g. OpenAI or Bedrock) wired into the fallback list — the config is structured so that's
a two-line change.

This sits *below* the whole-run resilience in [section 6](#6-resilience--failure-handling-whole-run):
the proxy handles the timeout + model fallback on a single call; the LangGraph engine handles retries,
budgets, and graceful degradation across the whole run.

---

## 5. The SQL sandbox (defense in depth)

The agent generates SQL, so the executor assumes the SQL is hostile. **Three independent layers** must
all agree before a query runs, and any one of them blocks a destructive query on its own:

1. **AST guard** (`sqlguard.py`) — parses with sqlglot and rejects anything that isn't a single `SELECT`:
   no `INSERT/UPDATE/DELETE/DROP/…`, including **CTE-hidden** DML and **stacked** statements. It also
   injects a `LIMIT` and a deterministic `ORDER BY`.
2. **Read-only transaction** — the connection runs with `default_transaction_read_only=on` and a
   `statement_timeout`.
3. **Least-privilege role** — queries run as `analyst_ro`, a Postgres role with `SELECT`/`USAGE` only.

A fourth guard, an **`EXPLAIN` cost pre-flight**, rejects queries whose estimated cost exceeds a cap
(catching accidental cartesian joins) *before* they run. All of this is verified against the live DB and
covered by unit tests.

---

## 6. Resilience & failure handling (whole-run)

Different failures are handled by the component best placed to handle them:

- **Semantic failure** (wrong/empty result) → the Verifier's `retry` conditional edge, bounded by a
  retry budget.
- **Transient error** (5xx, blip) → LangGraph `RetryPolicy` with backoff.
- **Slow / overloaded model** → per-key timeout + cross-tier Claude fallback at the proxy
  ([section 4](#4-timeouts--fallback-resilience-at-the-model-layer)).
- **Runaway run** → wall-clock budget + `recursion_limit` → graceful low-confidence abort.
- **Node crash** → the checkpointer has persisted state, so the run is **resumable**; the server and
  other runs are unaffected.

Every one of these has a named entry and a reproducing case in **[FAILURE_MODES.md](FAILURE_MODES.md)**.

---

## 7. Typed tool contracts & permissions

Every tool exposed to an agent or an MCP client has a **strict Pydantic input schema** (malformed input
is rejected, not coerced) and sits under a **permission matrix** ([`nl2sql/tools/`](../nl2sql/tools/)).
`get_schema` and `ask` are safe by default; the raw `run_sql` tool is **off unless explicitly enabled**
(`ENABLE_RUN_SQL=1`), and returns `403` otherwise.

---

## 8. Observability

Every live run emits an OpenTelemetry trace to **Arize Phoenix**: a parent `nl2sql.run` span, one span
per agent node, and LiteLLM `completion` spans (with tokens and cost) nested underneath — so you can see
the whole waterfall, where time went, and what each step cost.

<p align="center">
  <img src="assets/phoenix-trace-waterfall.png" alt="Phoenix trace waterfall: the full run with per-agent and LLM spans" width="640">
</p>

> Traces populate on **live** runs; replay/eval/CI make no LLM calls, so they emit no traces — by design.
