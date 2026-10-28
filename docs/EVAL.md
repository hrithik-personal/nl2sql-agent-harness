# Evaluation

The agent is scored by **execution-match**: run the agent's SQL and a gold SQL
against the seeded DB and compare result *sets* (order/column-insensitive,
float-tolerant). Ambiguous/unanswerable items are scored on behaviour
(clarify / low-confidence abort). The whole suite replays from cassettes, so it
runs **offline, deterministically, with no API key** — and it's **gated in CI**
(`EVAL_THRESHOLD=0.55`; see [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).

Both the LLM calls *and* the retrieval step are recorded/replayed. Pinning the
retrieved context matters: ranking tables by embedding similarity is
machine-sensitive, so freezing it keeps every prompt byte-identical across
machines — which is what makes the CI gate stable. Replay therefore needs only a
**seeded DB** (for SQL execution and gold comparison): no embedding model, no
pgvector index.

The seeded DB itself must also be byte-identical everywhere, because the
Verifier's prompt contains the SQL's execution result. Two things guarantee that:
**Faker is pinned to an exact version** (`faker==40.43.0`) and the seed uses a
**fixed reference clock** (`db/seed.py`'s `NOW` is a constant, not
`datetime.now()`). Time-window eval items therefore use **absolute dates** tied
to that constant rather than SQL `now()`, so no result drifts with the calendar.

```bash
make seed                 # deterministic shop data (no index needed for replay)
make eval                 # LLM_MODE=replay
EVAL_THRESHOLD=0.7 make eval
```

## Current baseline (20 items)

| metric | value |
|---|---|
| execution-match rate | **72.2%** (13/18 answerable) |
| valid-SQL rate | 100.0% |
| behaviour (clarify/abort) | 0/2 |
| avg retries | 0.15 |
| latency p50/p95 (replay) | ~16 / 48 ms |
| avg cost ($/query, live) | ~$0.012 |

Full per-item table is regenerated to `evals/report.md` on each run.

## Failure analysis ("what I hit, and why")

The 5 answerable misses are **defensible agent variations against a strict gold**,
not invalid SQL (valid-SQL is 100%):

1. **Extra/fewer columns** — `cust_top_by_orders`: the agent returns an extra
   column vs the gold's `(name, count)`. Different column arity → strict miss.
2. **Multi-join measure choices** — `join_top_sellers` and
   `ship_avg_delivery_by_courier`: equally reasonable join paths / "rank by"
   measures that differ from the one the gold happens to encode.
3. **Interval & grouping edges** — `ship_sla_breaches` (SLA interval arithmetic)
   and `time_monthly_revenue_h1_2026` (month bucketing at the window boundary):
   small, defensible differences the strict comparator counts as misses.
4. **Behaviour items (0/2)** — "who are the best sellers?" (the agent answers by
   revenue instead of asking *which* measure) and the unanswerable item (the agent
   clarifies instead of aborting). The clarify/abort machinery exists; the
   planner's policy for *when* to use it needs tuning.

Per-item diffs are regenerated into `evals/report.md` on every run.

## How to push the number up (future work)

- Richer, more diverse few-shot exemplars (schema-linking + phrasing coverage).
- Tighten the Writer prompt on column selection and join/measure conventions.
- Teach the Planner a clearer policy: clarify for undefined measures, abort when
  the requested data isn't in the schema.
- Where the agent's reading is equally valid, align the gold to the canonical one.

The point of this harness is not a vanity score — it's that every prompt/model
change now produces a **measurable, regression-gated** delta.
