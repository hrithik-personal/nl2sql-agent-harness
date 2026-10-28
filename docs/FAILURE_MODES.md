# Failure modes & mitigations

Real failure modes this system is designed to detect and recover from. Each has a
reproducing case in the eval set or unit tests.

| # | Failure mode | How it surfaces | Mitigation | Where |
|---|---|---|---|---|
| 1 | **Hallucinated column/table** | Writer references a column that doesn't exist | sqlglot unknown-table reject + `EXPLAIN` error → Verifier `retry` with the error as critique | `sqlguard.py`, `executor.py`, `agents/verifier.py` |
| 2 | **Join fan-out / cartesian** | Accidental cross join blows up the row estimate | `EXPLAIN` cost gate rejects when estimated cost exceeds the cap | `executor.py` (`sql_max_explain_cost`) |
| 3 | **Over-filtered empty result** | Correct-looking SQL returns 0 rows when rows were expected | Verifier judges result vs intent → `retry` | `agents/verifier.py` |
| 4 | **Ambiguous question** | "Who are the best sellers?" — by revenue? volume? rating? | Planner returns `needs_clarification` → graph `interrupt()` asks one question, resumes from the checkpoint | `agents/planner.py`, `orchestration/langgraph_engine.py` |
| 5 | **Retry budget exhausted** | Writer can't produce correct SQL within `max_retries` | Graceful **low-confidence** answer, never a loop | engine `_route_after_verify` |
| 6 | **Wall-clock budget exceeded** | A run takes too long | `_over_budget` routes straight to a low-confidence answer | engine `_over_budget` |
| 7 | **LLM error / timeout / overload** | Transient 5xx, network blip, slow response, or a single model rate-limited (429/529) | Per-deployment `timeout` in LiteLLM (so a hang fails fast); LangGraph `RetryPolicy` (backoff) on LLM nodes; **cross-tier Claude fallback** (Sonnet↔Haiku) at the proxy | engine `LLM_RETRY`, `litellm/config.yaml` |
| 8 | **Stacked / CTE-hidden write** | `SELECT 1; DROP TABLE…` or `WITH x AS (DELETE…)` | sqlglot AST reject (any DML/DDL) + read-only txn + `analyst_ro` role — three independent layers | `sqlguard.py`, `executor.py`, `db/02_roles.sql` |
| 9 | **Cost spike** | A query path burns too many tokens | Per-run token/cost budget + per-agent LiteLLM key budgets; `$/query` surfaced in trace & scorecard | `config.py`, `litellm/config.yaml` |
| 10 | **Unanswerable from schema** | Asking for data the DB doesn't hold | Verifier/Planner `abort` → low-confidence answer | `agents/verifier.py` |

## Node-crash semantics
If a node raises an unhandled exception, LangGraph stops **that run** and
propagates, but the checkpointer has persisted state up to the last successful
step, so the run is **resumable** by `thread_id`. The surfaces (FastAPI/MCP)
return a clean error; the server and other runs are unaffected.
