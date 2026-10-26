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

```bash
make seed                 # deterministic shop data (no index needed for replay)
make eval                 # LLM_MODE=replay
EVAL_THRESHOLD=0.7 make eval
```

## Current baseline (20 items)

| metric | value |
|---|---|
| execution-match rate | **61.1%** (11/18 answerable) |
| valid-SQL rate | 100.0% |
| behaviour (clarify/abort) | 0/2 |
| avg retries | 0.15 |
| latency p50/p95 (replay) | ~33 / 51 ms |
| avg cost ($/query, live) | ~$0.012 |

Full per-item table is regenerated to `evals/report.md` on each run.

## Failure analysis ("what I hit, and why")

The misses are **mostly defensible agent variations against a strict gold**, not
invalid SQL (valid-SQL is 100%):

1. **Interpretation differences** — e.g. "delivered revenue": the agent filters
   `shipments.status='delivered'`, the gold filters `orders.status='delivered'`.
   Both are reasonable; execution-match (strict) counts it as a miss.
2. **Extra/fewer columns** — `cust_top_by_orders`: the agent also selects
   `customer.id`; the gold returns `(name, count)`. Different column arity → miss.
3. **Boundary semantics** — `time_orders_last_30d`: agent uses
   `current_date - interval '30 days'`, gold uses `now() - …` (171 vs 168 rows).
4. **Genuinely harder joins** — `join_refunds_by_category` hit the retry cap (3
   retries): counting refunds through `order_items` double-counts multi-category
   orders. The agent's own verifier critique flagged this; it couldn't fully fix
   it within the budget → a real, honest failure.
5. **Opinionated behaviour items** — "who are the best sellers?" (the agent
   answers by revenue instead of asking *which* measure) and "average customer
   satisfaction score" (no such data; the agent asks to clarify instead of
   aborting). These show the clarify/abort machinery exists but the planner's
   policy for *when* to use it needs tuning.

## How to push the number up (future work)

- Richer, more diverse few-shot exemplars (schema-linking + phrasing coverage).
- Tighten the Writer prompt on column selection and `now()`/date-boundary conventions.
- Teach the Planner a clearer policy: clarify for undefined measures, abort when
  the requested data isn't in the schema.
- Where the agent's reading is equally valid, align the gold to the canonical one.

The point of this harness is not a vanity score — it's that every prompt/model
change now produces a **measurable, regression-gated** delta.
