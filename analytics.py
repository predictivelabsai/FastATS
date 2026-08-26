"""Recruiting analytics: funnel, time-in-stage, and source effectiveness.

Pure SQL aggregation over the tenant's data. Portable across SQLite/Postgres by
pulling rows and finishing the arithmetic in Python where date math differs."""
from __future__ import annotations

from datetime import datetime

from database import Database


class AnalyticsService:
    def __init__(self, db: Database):
        self.db = db

    def funnel(self, organization_id: str, job_id: str) -> list[dict]:
        """Applications currently sitting in each stage, in pipeline order."""
        return self.db.rows("""SELECT s.name, s.position,
            (SELECT COUNT(*) FROM applications a
               WHERE a.organization_id=? AND a.job_id=? AND a.stage_id=s.id) count
            FROM pipeline_stages s WHERE s.organization_id=? AND s.job_id=?
            ORDER BY s.position""",
            (organization_id, job_id, organization_id, job_id))

    def source_effectiveness(self, organization_id: str) -> list[dict]:
        """Per source: total applications and how many reached a Hired status."""
        return self.db.rows("""SELECT source,
            COUNT(*) total,
            SUM(CASE WHEN status='Hired' THEN 1 ELSE 0 END) hired
            FROM applications WHERE organization_id=?
            GROUP BY source ORDER BY total DESC""", (organization_id,))

    def time_in_stage(self, organization_id: str) -> dict:
        """Average days applications have spent in their current stage."""
        rows = self.db.rows("""SELECT a.stage_entered_at, s.name stage_name
            FROM applications a JOIN pipeline_stages s ON s.id=a.stage_id
            WHERE a.organization_id=? AND a.status='Active'""", (organization_id,))
        now = datetime.now().astimezone()
        buckets: dict[str, list[float]] = {}
        for row in rows:
            entered = _parse(row["stage_entered_at"])
            if entered is None:
                continue
            days = max(0.0, (now - entered).total_seconds() / 86400.0)
            buckets.setdefault(row["stage_name"], []).append(days)
        return {stage: round(sum(values) / len(values), 1)
                for stage, values in buckets.items()}

    def overview(self, organization_id: str) -> dict:
        jobs = self.db.scalar("SELECT COUNT(*) FROM jobs WHERE organization_id=? AND status='Published'",
                              (organization_id,))
        candidates = self.db.scalar("SELECT COUNT(*) FROM candidates WHERE organization_id=?",
                                    (organization_id,))
        applications = self.db.scalar("SELECT COUNT(*) FROM applications WHERE organization_id=?",
                                      (organization_id,))
        hired = self.db.scalar("SELECT COUNT(*) FROM applications WHERE organization_id=? AND status='Hired'",
                               (organization_id,))
        return {"open_roles": jobs or 0, "candidates": candidates or 0,
                "applications": applications or 0, "hired": hired or 0}


def _parse(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed
    except (ValueError, TypeError):
        return None
