-- Portable embedding store (both engines). Source of truth for vectors; on
-- PostgreSQL the semantic service also uses the pgvector columns from 0003 for
-- indexed ANN search, while SQLite computes cosine similarity in Python here.

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, model)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_entity
    ON embeddings(organization_id, entity_type);
