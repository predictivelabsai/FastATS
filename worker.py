"""Lightweight database-backed FastATS worker.

Dispatches queued jobs by kind: resume screening, entity embedding, and email
sequence steps. Handlers accept injected collaborators (evaluator, embedder,
emailer) so the queue can be exercised end-to-end in tests without any key.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from database import Database, get_database, utcnow


def claim_one(db: Database) -> dict | None:
    with db.transaction() as tx:
        if db.dialect == "sqlite":
            tx.execute("BEGIN IMMEDIATE")
        suffix = " FOR UPDATE SKIP LOCKED" if db.dialect == "postgres" else ""
        item = tx.one("""SELECT * FROM job_queue WHERE status='Pending' AND available_at<=?
            ORDER BY created_at LIMIT 1""" + suffix, (utcnow(),))
        if not item:
            return None
        tx.execute("""UPDATE job_queue SET status='Running',locked_at=?,attempts=attempts+1
            WHERE id=? AND status='Pending'""", (utcnow(), item["id"]))
        return item


def _handle_screen(db, item, payload, *, evaluator=None):
    from screening import screen_application
    kwargs = {"evaluator": evaluator} if evaluator else {}
    screen_application(db, item["organization_id"], payload["application_id"],
                       payload.get("document_id"), **kwargs)


def _handle_embed(db, item, payload, *, embedder=None):
    from semantic import index_entity
    index_entity(db, item["organization_id"], payload["entity_type"],
                 payload["entity_id"], payload.get("text", ""), embedder=embedder)


def _handle_sequence(db, item, payload, *, emailer=None):
    from crm import CRMService
    CRMService(db, emailer=emailer).process_enrollment(
        item["organization_id"], payload["enrollment_id"])


def process_one(db: Database | None = None, *, evaluator: Callable | None = None,
                embedder=None, emailer=None) -> bool:
    db = db or get_database()
    item = claim_one(db)
    if not item:
        return False
    try:
        payload = json.loads(item["payload_json"])
        kind = item["kind"]
        if kind == "screen_application":
            _handle_screen(db, item, payload, evaluator=evaluator)
        elif kind == "embed_entity":
            _handle_embed(db, item, payload, embedder=embedder)
        elif kind == "send_sequence_step":
            _handle_sequence(db, item, payload, emailer=emailer)
        else:
            raise ValueError(f"Unsupported job kind: {kind}")
        with db.transaction() as tx:
            tx.execute("UPDATE job_queue SET status='Completed',completed_at=? WHERE id=?",
                       (utcnow(), item["id"]))
    except Exception as exc:
        with db.transaction() as tx:
            tx.execute("UPDATE job_queue SET status='Error',error=?,completed_at=? WHERE id=?",
                       (str(exc), utcnow(), item["id"]))
    return True


def run_forever(poll_seconds: float = 2.0) -> None:
    db = get_database()
    db.migrate()
    while True:
        if not process_one(db):
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_forever()
