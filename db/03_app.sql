-- App-owned state: retrieval index (pgvector) + run traces.
-- bge-small-en-v1.5 => 384-dim embeddings.
SET search_path TO app;

CREATE TABLE IF NOT EXISTS schema_cards (
    table_name  TEXT PRIMARY KEY,
    card_text   TEXT NOT NULL,
    embedding   vector(384)
);

CREATE TABLE IF NOT EXISTS exemplars (
    id         SERIAL PRIMARY KEY,
    question   TEXT NOT NULL,
    sql        TEXT NOT NULL,
    embedding  vector(384)
);

CREATE TABLE IF NOT EXISTS run_traces (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         TEXT,
    question          TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    answer            JSONB,
    trace             JSONB,
    phoenix_trace_id  TEXT
);

-- Approximate-nearest-neighbour indexes (cosine). HNSW is fine on small sets.
CREATE INDEX IF NOT EXISTS idx_schema_cards_embedding
    ON schema_cards USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_exemplars_embedding
    ON exemplars USING hnsw (embedding vector_cosine_ops);
