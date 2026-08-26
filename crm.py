"""Talent pools, email sequences, and outreach messaging (tenant-scoped)."""
from __future__ import annotations

import json

from ats import new_id
from database import Database, utcnow
from emailer import Emailer, get_emailer


class CRMService:
    def __init__(self, db: Database, emailer: Emailer | None = None):
        self.db = db
        self.emailer = emailer or get_emailer()

    # --- Talent pools --------------------------------------------------------
    def create_pool(self, organization_id: str, *, name: str, description: str = "",
                    created_by: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Pool name is required")
        existing = self.db.one("SELECT id FROM talent_pools WHERE organization_id=? AND name=?",
                               (organization_id, name))
        if existing:
            return existing["id"]
        pool_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO talent_pools
                (id,organization_id,name,description,created_by,created_at) VALUES (?,?,?,?,?,?)""",
                (pool_id, organization_id, name, description.strip(), created_by, utcnow()))
        return pool_id

    def pools(self, organization_id: str) -> list[dict]:
        return self.db.rows("""SELECT p.*,
            (SELECT COUNT(*) FROM pool_memberships m WHERE m.pool_id=p.id) members
            FROM talent_pools p WHERE p.organization_id=? ORDER BY p.name""", (organization_id,))

    def pool_members(self, organization_id: str, pool_id: str) -> list[dict]:
        return self.db.rows("""SELECT c.* FROM pool_memberships m
            JOIN candidates c ON c.id=m.candidate_id
            WHERE m.organization_id=? AND m.pool_id=? ORDER BY c.last_name""",
            (organization_id, pool_id))

    def add_to_pool(self, organization_id: str, pool_id: str, candidate_id: str,
                    added_by: str | None = None) -> str | None:
        pool = self.db.one("SELECT id FROM talent_pools WHERE id=? AND organization_id=?",
                           (pool_id, organization_id))
        candidate = self.db.one("SELECT id FROM candidates WHERE id=? AND organization_id=?",
                                (candidate_id, organization_id))
        if not pool or not candidate:
            raise ValueError("Pool and candidate must belong to this organization")
        existing = self.db.one("SELECT id FROM pool_memberships WHERE pool_id=? AND candidate_id=?",
                               (pool_id, candidate_id))
        if existing:
            return existing["id"]
        member_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO pool_memberships
                (id,organization_id,pool_id,candidate_id,added_by,created_at) VALUES (?,?,?,?,?,?)""",
                (member_id, organization_id, pool_id, candidate_id, added_by, utcnow()))
        return member_id

    # --- Email sequences -----------------------------------------------------
    def create_sequence(self, organization_id: str, *, name: str,
                        steps: list[dict], created_by: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Sequence name is required")
        if not steps:
            raise ValueError("A sequence needs at least one step")
        sequence_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO email_sequences
                (id,organization_id,name,status,created_by,created_at) VALUES (?,?,?,?,?,?)""",
                (sequence_id, organization_id, name, "Active", created_by, utcnow()))
            for order, step in enumerate(steps):
                tx.execute("""INSERT INTO sequence_steps
                    (id,organization_id,sequence_id,step_order,subject,body,delay_hours)
                    VALUES (?,?,?,?,?,?,?)""",
                    (new_id(), organization_id, sequence_id, order,
                     step["subject"], step["body"], int(step.get("delay_hours", 0))))
        return sequence_id

    def sequences(self, organization_id: str) -> list[dict]:
        return self.db.rows("""SELECT s.*,
            (SELECT COUNT(*) FROM sequence_steps st WHERE st.sequence_id=s.id) step_count,
            (SELECT COUNT(*) FROM sequence_enrollments e WHERE e.sequence_id=s.id) enrolled
            FROM email_sequences s WHERE s.organization_id=? ORDER BY s.created_at DESC""",
            (organization_id,))

    def steps(self, organization_id: str, sequence_id: str) -> list[dict]:
        return self.db.rows("""SELECT * FROM sequence_steps
            WHERE organization_id=? AND sequence_id=? ORDER BY step_order""",
            (organization_id, sequence_id))

    def enroll(self, organization_id: str, sequence_id: str, candidate_id: str,
               enrolled_by: str | None = None) -> str:
        sequence = self.db.one("SELECT id FROM email_sequences WHERE id=? AND organization_id=?",
                               (sequence_id, organization_id))
        candidate = self.db.one("SELECT id FROM candidates WHERE id=? AND organization_id=?",
                                (candidate_id, organization_id))
        if not sequence or not candidate:
            raise ValueError("Sequence and candidate must belong to this organization")
        existing = self.db.one("""SELECT id FROM sequence_enrollments
            WHERE sequence_id=? AND candidate_id=?""", (sequence_id, candidate_id))
        if existing:
            return existing["id"]
        enrollment_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO sequence_enrollments
                (id,organization_id,sequence_id,candidate_id,status,current_step,enrolled_by,enrolled_at,next_run_at)
                VALUES (?,?,?,?,'Active',0,?,?,?)""",
                (enrollment_id, organization_id, sequence_id, candidate_id, enrolled_by, now, now))
        return enrollment_id

    def due_enrollments(self, limit: int = 50) -> list[dict]:
        return self.db.rows("""SELECT * FROM sequence_enrollments
            WHERE status='Active' AND next_run_at IS NOT NULL AND next_run_at<=?
            ORDER BY next_run_at LIMIT ?""", (utcnow(), limit))

    def process_enrollment(self, organization_id: str, enrollment_id: str) -> str:
        """Send the current step's email, advance, and schedule the next step.

        Returns the enrollment status after processing.
        """
        enrollment = self.db.one("""SELECT * FROM sequence_enrollments
            WHERE id=? AND organization_id=?""", (enrollment_id, organization_id))
        if not enrollment or enrollment["status"] != "Active":
            return enrollment["status"] if enrollment else "Missing"
        step = self.db.one("""SELECT * FROM sequence_steps
            WHERE sequence_id=? AND step_order=?""",
            (enrollment["sequence_id"], enrollment["current_step"]))
        candidate = self.db.one("SELECT * FROM candidates WHERE id=?", (enrollment["candidate_id"],))
        if not step:
            with self.db.transaction() as tx:
                tx.execute("UPDATE sequence_enrollments SET status='Completed',next_run_at=NULL WHERE id=?",
                           (enrollment_id,))
            return "Completed"
        from config import settings
        result = self.emailer.send(to=candidate["email"], subject=step["subject"],
                                   body=step["body"], from_email=settings.from_email)
        next_step = self.db.one("""SELECT * FROM sequence_steps
            WHERE sequence_id=? AND step_order=?""",
            (enrollment["sequence_id"], enrollment["current_step"] + 1))
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO messages
                (id,organization_id,candidate_id,enrollment_id,direction,subject,body,provider,status,sent_at,created_at)
                VALUES (?,?,?,?,'outbound',?,?,?,?,?,?)""",
                (new_id(), organization_id, candidate["id"], enrollment_id, step["subject"],
                 step["body"], result.provider, result.status, utcnow(), utcnow()))
            if next_step:
                tx.execute("""UPDATE sequence_enrollments SET current_step=?,next_run_at=? WHERE id=?""",
                           (enrollment["current_step"] + 1, utcnow(), enrollment_id))
                status = "Active"
            else:
                tx.execute("UPDATE sequence_enrollments SET status='Completed',next_run_at=NULL WHERE id=?",
                           (enrollment_id,))
                status = "Completed"
        return status

    def messages_for(self, organization_id: str, candidate_id: str) -> list[dict]:
        return self.db.rows("""SELECT * FROM messages
            WHERE organization_id=? AND candidate_id=? ORDER BY created_at DESC""",
            (organization_id, candidate_id))
