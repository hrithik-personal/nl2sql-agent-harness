"""Schema introspection -> embedding-ready TableCards.

Reads the *structure* of the `shop` schema (tables, columns, keys) plus a few
sample values per low-cardinality text column. This is distinct from execution:
introspection reads metadata once; execution runs SQL against the data.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from nl2sql.config import Settings, get_settings
from nl2sql.schemas import ColumnInfo, TableCard

_TEXT_TYPES = ("TEXT", "VARCHAR", "CHAR", "CHARACTER")


def introspect(settings: Settings | None = None, schema: str = "shop") -> list[TableCard]:
    s = settings or get_settings()
    engine = create_engine(s.app_dsn())
    insp = inspect(engine)
    cards: list[TableCard] = []

    with engine.connect() as conn:
        for table in sorted(insp.get_table_names(schema=schema)):
            cols = insp.get_columns(table, schema=schema)
            columns = [
                ColumnInfo(name=c["name"], type=str(c["type"]), nullable=bool(c["nullable"]))
                for c in cols
            ]
            pk = insp.get_pk_constraint(table, schema=schema).get("constrained_columns") or []
            fks = [
                {
                    "column": (fk["constrained_columns"] or [""])[0],
                    "ref_table": fk["referred_table"],
                    "ref_column": (fk["referred_columns"] or [""])[0],
                }
                for fk in insp.get_foreign_keys(table, schema=schema)
            ]
            samples: dict[str, list[str]] = {}
            for c in cols:
                if any(t in str(c["type"]).upper() for t in _TEXT_TYPES):
                    rows = conn.execute(
                        text(
                            f'SELECT DISTINCT "{c["name"]}" FROM {schema}.{table} '
                            f'WHERE "{c["name"]}" IS NOT NULL LIMIT 5'
                        )
                    ).fetchall()
                    vals = [str(r[0]) for r in rows]
                    if vals:
                        samples[c["name"]] = vals
            cards.append(
                TableCard(
                    table=table,
                    columns=columns,
                    primary_key=list(pk),
                    foreign_keys=fks,
                    sample_values=samples,
                )
            )
    return cards
