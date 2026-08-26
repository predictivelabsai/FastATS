"""Observability: persist every agent graph run with inputs, outputs, status."""
from __future__ import annotations

import json
from typing import Any

from ats import new_id
from database import Database, utcnow


def start_run(db: Database, organization_id: str, *, graph: str,
              entity_type: str, entity_id: str, actor_user_id: str | None,
              inputs: dict[str, Any]) -> str:
    run_id = new_id()
    with db.transaction() as tx:
        tx.execute(
            """INSERT INTO agent_runs
               (id,organization_id,graph,entity_type,entity_id,actor_user_id,status,inputs_json,created_at)
               VALUES (?,?,?,?,?,?,'Running',?,?)""",
            (run_id, organization_id, graph, entity_type, entity_id, actor_user_id,
             json.dumps(inputs), utcnow()))
    return run_id


def finish_run(db: Database, run_id: str, *, status: str = "Completed",
               outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
    with db.transaction() as tx:
        tx.execute(
            """UPDATE agent_runs SET status=?,outputs_json=?,error=?,completed_at=? WHERE id=?""",
            (status, json.dumps(outputs) if outputs is not None else None, error,
             utcnow(), run_id))
