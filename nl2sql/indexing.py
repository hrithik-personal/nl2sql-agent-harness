"""Build the retrieval index: embed schema cards + exemplars into pgvector.

Run with `make index` after the DB is seeded.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from nl2sql.catalog import introspect
from nl2sql.config import get_settings
from nl2sql.retrieve import BgeEmbedder

EXEMPLARS_FILE = Path(__file__).resolve().parent.parent / "db" / "exemplars.jsonl"


def main() -> None:
    s = get_settings()
    embedder = BgeEmbedder(s.embedding_model)

    cards = introspect(s)
    card_texts = [c.to_card_text() for c in cards]
    card_vecs = embedder.embed_docs(card_texts)

    exemplars = [
        json.loads(line) for line in EXEMPLARS_FILE.read_text().splitlines() if line.strip()
    ]
    ex_vecs = embedder.embed_docs([e["question"] for e in exemplars])

    conn = psycopg.connect(s.app_dsn(), autocommit=True)
    register_vector(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE app.schema_cards")
        for card, txt, vec in zip(cards, card_texts, card_vecs, strict=True):
            cur.execute(
                "INSERT INTO app.schema_cards (table_name, card_text, embedding) VALUES (%s,%s,%s)",
                (card.table, txt, vec),
            )
        cur.execute("TRUNCATE app.exemplars RESTART IDENTITY")
        for ex, vec in zip(exemplars, ex_vecs, strict=True):
            cur.execute(
                "INSERT INTO app.exemplars (question, sql, embedding) VALUES (%s,%s,%s)",
                (ex["question"], ex["sql"], vec),
            )
    conn.close()
    print(f"indexed {len(cards)} schema cards and {len(exemplars)} exemplars")


if __name__ == "__main__":
    main()
