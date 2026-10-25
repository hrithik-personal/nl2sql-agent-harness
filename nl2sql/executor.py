"""Sandboxed SQL executor.

Defense in depth before a single row is read:
  1. least-privilege `analyst_ro` role (granted SELECT on `shop` only)
  2. read-only transaction (`default_transaction_read_only=on`)
  3. statement timeout
  4. sqlglot static guard (single SELECT, no DML/DDL anywhere)
  5. row-cap LIMIT
  6. EXPLAIN (FORMAT JSON) pre-flight — reject invalid or over-cost queries
"""

from __future__ import annotations

import datetime as _dt
import time
from decimal import Decimal

import psycopg

from nl2sql.config import Settings, get_settings
from nl2sql.schemas import ExecError, ExecResult
from nl2sql.sqlguard import validate_select


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    return v


class SandboxExecutor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()

    def _connect(self) -> psycopg.Connection:
        opts = (
            f"-c default_transaction_read_only=on "
            f"-c statement_timeout={self.s.sql_statement_timeout_ms} "
            f"-c search_path=shop"
        )
        return psycopg.connect(self.s.readonly_dsn(), options=opts, autocommit=True)

    def __call__(self, sql: str, allowed_tables: set[str]) -> ExecResult | ExecError:
        guard = validate_select(sql, allowed_tables=allowed_tables, max_rows=self.s.sql_max_rows)
        if not guard.ok:
            return ExecError(error_type=guard.error_type, message=guard.message)  # type: ignore[arg-type]
        safe_sql = guard.sql

        try:
            with self._connect() as conn, conn.cursor() as cur:
                # (6) EXPLAIN pre-flight
                try:
                    cur.execute(f"EXPLAIN (FORMAT JSON) {safe_sql}")
                    plan = cur.fetchone()[0]
                    total_cost = float(plan[0]["Plan"]["Total Cost"])
                except psycopg.Error as e:
                    return ExecError(error_type="invalid_sql", message=str(e).strip())
                if total_cost > self.s.sql_max_explain_cost:
                    return ExecError(
                        error_type="too_expensive",
                        message=f"estimated cost {total_cost:.0f} exceeds cap "
                        f"{self.s.sql_max_explain_cost:.0f}; add a filter",
                    )

                # execute
                t0 = time.perf_counter()
                cur.execute(safe_sql)
                cols = [d.name for d in cur.description] if cur.description else []
                fetched = cur.fetchmany(self.s.sql_max_rows + 1)
                truncated = len(fetched) > self.s.sql_max_rows
                rows = [[_jsonable(c) for c in r] for r in fetched[: self.s.sql_max_rows]]
                return ExecResult(
                    columns=cols,
                    rows=rows,
                    rowcount=len(rows),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                    truncated=truncated,
                )
        except psycopg.errors.QueryCanceled:
            return ExecError(error_type="timeout", message="statement timed out")
        except psycopg.Error as e:
            return ExecError(error_type="db_error", message=str(e).strip())
