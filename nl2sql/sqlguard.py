"""Static SQL safety analysis (pure, no DB).

Layer 4 of the executor sandbox: parse with sqlglot and allow exactly one
read-only SELECT. Rejects stacked statements and any DML/DDL anywhere in the
AST — including writes hidden inside a CTE, e.g.
    WITH g AS (DELETE FROM orders RETURNING *) SELECT * FROM g;
Also injects a LIMIT when the query has none.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Any of these appearing anywhere in the tree means "not a pure read".
_FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,  # SET/CALL/VACUUM/GRANT and other non-query statements
)


@dataclass
class GuardResult:
    ok: bool
    sql: str = ""  # cleaned SQL (LIMIT injected) when ok
    error_type: str = ""  # invalid_sql | forbidden
    message: str = ""
    tables: tuple[str, ...] = ()


def validate_select(
    sql: str,
    allowed_tables: set[str] | None = None,
    max_rows: int = 1000,
) -> GuardResult:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return GuardResult(False, error_type="invalid_sql", message="empty SQL")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception as e:  # noqa: BLE001 - surface any parse failure uniformly
        return GuardResult(False, error_type="invalid_sql", message=f"parse error: {e}")

    if len(statements) != 1:
        return GuardResult(
            False,
            error_type="forbidden",
            message=f"expected exactly one statement, got {len(statements)}",
        )

    root = statements[0]

    # Reject any write/DDL node anywhere in the tree (covers CTE-hidden DML).
    for node in root.walk():
        if isinstance(node, _FORBIDDEN):
            return GuardResult(
                False,
                error_type="forbidden",
                message=f"non-SELECT statement is not allowed ({type(node).__name__})",
            )

    # Top level must be a query (SELECT / UNION / WITH-wrapped select).
    query = root.this if isinstance(root, exp.With) else root
    if not isinstance(query, (exp.Select, exp.Union, exp.Subquery)):
        return GuardResult(
            False,
            error_type="forbidden",
            message=f"top-level statement must be a SELECT (got {type(root).__name__})",
        )

    # CTE names are local aliases, not real tables — don't flag them as unknown.
    cte_names = {c.alias_or_name for c in root.find_all(exp.CTE)}
    tables = tuple(
        sorted({t.name for t in root.find_all(exp.Table) if t.name and t.name not in cte_names})
    )
    if allowed_tables:
        unknown = [t for t in tables if t not in allowed_tables]
        if unknown:
            return GuardResult(
                False,
                error_type="invalid_sql",
                message=f"unknown table(s): {', '.join(unknown)}",
                tables=tables,
            )

    # Inject LIMIT when missing (best effort; executor also hard-caps the fetch).
    try:
        if isinstance(root, exp.Select) and not root.args.get("limit"):
            root = root.limit(max_rows)
        elif (
            isinstance(root, exp.With)
            and isinstance(root.this, exp.Select)
            and not root.this.args.get("limit")
        ):
            root.set("this", root.this.limit(max_rows))
    except Exception:  # noqa: BLE001 - limit injection is non-critical
        pass

    return GuardResult(True, sql=root.sql(dialect="postgres"), tables=tables)
