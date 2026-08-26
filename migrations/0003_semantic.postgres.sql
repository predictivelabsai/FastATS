-- PostgreSQL-only: pgvector-backed semantic search. Skipped on SQLite, where
-- the service layer falls back to keyword search.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE candidates ADD COLUMN IF NOT EXISTS embedding vector(1536);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector(1536);

ALTER TABLE candidates ADD COLUMN IF NOT EXISTS embedded_at TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedded_at TEXT;

CREATE INDEX IF NOT EXISTS idx_candidates_embedding
    ON candidates USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
