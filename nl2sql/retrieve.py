"""RAG schema-linking: embeddings + pgvector retrieval.

pgvector ranks which tables/exemplars are relevant to a question; the structured
TableCards (held in memory from introspection) are used for FK-graph expansion
and for the context we return. Keeps large schemas out of the prompt.
"""

from __future__ import annotations

from functools import lru_cache

import psycopg
from pgvector.psycopg import register_vector

from nl2sql.catalog import introspect
from nl2sql.config import Settings, get_settings
from nl2sql.schemas import Exemplar, RetrievedContext, TableCard

# bge-* models want this instruction prepended to *queries* (not documents).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache
def _model(name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


class BgeEmbedder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.is_bge = "bge" in model_name.lower()

    def embed_docs(self, texts: list[str]) -> list[list[float]]:
        return [
            v.tolist() for v in _model(self.model_name).encode(texts, normalize_embeddings=True)
        ]

    def embed_query(self, text: str) -> list[float]:
        q = (BGE_QUERY_PREFIX + text) if self.is_bge else text
        return _model(self.model_name).encode([q], normalize_embeddings=True)[0].tolist()


class PgVectorRetriever:
    def __init__(self, settings: Settings | None = None, top_k: int = 6, top_m: int = 4) -> None:
        self.s = settings or get_settings()
        self.top_k = top_k
        self.top_m = top_m
        self.embedder = BgeEmbedder(self.s.embedding_model)
        self.cards: dict[str, TableCard] = {c.table: c for c in introspect(self.s)}

    def _conn(self) -> psycopg.Connection:
        # disable index scans so ranking is EXACT (not approximate HNSW) — the
        # corpus is tiny and this makes retrieval fully deterministic, which the
        # cassette-replay/eval path relies on.
        conn = psycopg.connect(
            self.s.app_dsn(),
            autocommit=True,
            options="-c enable_indexscan=off -c enable_bitmapscan=off",
        )
        register_vector(conn)
        return conn

    def _fk_expand(self, tables: set[str]) -> set[str]:
        expanded = set(tables)
        for t in tables:
            card = self.cards.get(t)
            if not card:
                continue
            for fk in card.foreign_keys:
                expanded.add(fk["ref_table"])
            # also pull tables that FK *into* t
            for other in self.cards.values():
                if any(fk["ref_table"] == t for fk in other.foreign_keys):
                    expanded.add(other.table)
        return expanded

    def __call__(self, question: str) -> RetrievedContext:
        import numpy as np

        # pass as ndarray so pgvector's dumper emits a `vector` (a plain list is
        # inferred as double precision[] and the <=> operator won't match)
        qvec = np.asarray(self.embedder.embed_query(question), dtype=np.float32)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM app.schema_cards "
                "ORDER BY embedding <=> %s, table_name LIMIT %s",  # stable tiebreak
                (qvec, self.top_k),
            )
            ranked = [r[0] for r in cur.fetchall()]
            cur.execute(
                "SELECT question, sql FROM app.exemplars "
                "ORDER BY embedding <=> %s, id LIMIT %s",  # stable tiebreak
                (qvec, self.top_m),
            )
            exemplars = [Exemplar(question=r[0], sql=r[1]) for r in cur.fetchall()]

        tables = self._fk_expand(set(ranked))
        # keep ranked order first, then FK-pulled extras
        ordered = ranked + [t for t in sorted(tables) if t not in ranked]
        cards = [self.cards[t] for t in ordered if t in self.cards]
        return RetrievedContext(tables=cards, exemplars=exemplars)
