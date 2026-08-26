"""Semantic indexing and search.

Vectors live in the portable ``embeddings`` table on both engines. On
PostgreSQL we additionally write the pgvector column and let the database do ANN
ordering; on SQLite we compute cosine similarity in Python. With no embeddings
key the FakeEmbedder still produces deterministic vectors, so search runs in dev
and tests — it just isn't semantically meaningful.
"""
from __future__ import annotations

import json

from ats import new_id
from config import settings
from database import Database, utcnow
from embeddings import Embedder, cosine_similarity, get_embedder


def index_entity(db: Database, organization_id: str, entity_type: str, entity_id: str,
                 text: str, *, embedder: Embedder | None = None) -> None:
    embedder = embedder or get_embedder()
    try:
        vector = embedder.embed_one(text or "")
    except Exception:
        # A misconfigured/expired hosted key must not crash the worker; skip
        # indexing and let search fall back to keyword matching.
        return
    now = utcnow()
    existing = db.one("""SELECT id FROM embeddings
        WHERE entity_type=? AND entity_id=? AND model=?""",
        (entity_type, entity_id, settings.embeddings_model))
    with db.transaction() as tx:
        if existing:
            tx.execute("UPDATE embeddings SET vector_json=?,dim=?,created_at=? WHERE id=?",
                       (json.dumps(vector), len(vector), now, existing["id"]))
        else:
            tx.execute("""INSERT INTO embeddings
                (id,organization_id,entity_type,entity_id,model,dim,vector_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), organization_id, entity_type, entity_id,
                 settings.embeddings_model, len(vector), json.dumps(vector), now))
        if db.dialect == "postgres" and entity_type in ("candidate", "document"):
            table = "candidates" if entity_type == "candidate" else "documents"
            literal = "[" + ",".join(str(v) for v in vector) + "]"
            tx.execute(f"UPDATE {table} SET embedding=?::vector,embedded_at=? WHERE id=? AND organization_id=?",
                       (literal, now, entity_id, organization_id))


def search(db: Database, organization_id: str, entity_type: str, query: str,
           *, limit: int = 10, embedder: Embedder | None = None) -> list[dict]:
    """Return [{entity_id, score}] ranked by similarity to the query."""
    embedder = embedder or get_embedder()
    try:
        query_vector = embedder.embed_one(query or "")
    except Exception:
        # Hosted embeddings unavailable (bad key, network) — signal the caller to
        # use keyword fallback rather than raising into the agent/chat.
        return []

    if db.dialect == "postgres" and entity_type in ("candidate", "document"):
        table = "candidates" if entity_type == "candidate" else "documents"
        literal = "[" + ",".join(str(v) for v in query_vector) + "]"
        rows = db.rows(
            f"""SELECT id AS entity_id, 1 - (embedding <=> ?::vector) AS score
                FROM {table} WHERE organization_id=? AND embedding IS NOT NULL
                ORDER BY embedding <=> ?::vector LIMIT ?""",
            (literal, organization_id, literal, limit))
        return rows

    rows = db.rows("""SELECT entity_id,vector_json FROM embeddings
        WHERE organization_id=? AND entity_type=? AND model=?""",
        (organization_id, entity_type, settings.embeddings_model))
    scored = [{"entity_id": row["entity_id"],
               "score": cosine_similarity(query_vector, json.loads(row["vector_json"]))}
              for row in rows]
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def keyword_fallback(db: Database, organization_id: str, query: str,
                     limit: int = 10) -> list[dict]:
    """Plain LIKE search over candidates, for when embeddings are unavailable."""
    like = f"%{query.lower()}%"
    rows = db.rows("""SELECT id AS entity_id FROM candidates
        WHERE organization_id=? AND (lower(first_name||' '||last_name) LIKE ?
              OR lower(coalesce(headline,'')) LIKE ?)
        ORDER BY last_name LIMIT ?""", (organization_id, like, like, limit))
    return [{"entity_id": row["entity_id"], "score": 0.0} for row in rows]


def search_candidates(db: Database, organization_id: str, query: str,
                      *, limit: int = 10, embedder: Embedder | None = None) -> list[dict]:
    """Semantic candidate search with hydrated candidate rows; keyword fallback."""
    hits = search(db, organization_id, "candidate", query, limit=limit, embedder=embedder)
    if not hits:
        hits = keyword_fallback(db, organization_id, query, limit)
    results = []
    for hit in hits:
        candidate = db.one("SELECT * FROM candidates WHERE id=? AND organization_id=?",
                           (hit["entity_id"], organization_id))
        if candidate:
            candidate["score"] = round(hit["score"], 4)
            results.append(candidate)
    return results
