-- Runs first at container init (as the DB owner).
-- pgvector extension + the two logical schemas.
--   shop : analytics target data (what SQL queries hit)
--   app  : our own state (embeddings, run traces, langgraph checkpoints)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS shop;
CREATE SCHEMA IF NOT EXISTS app;
