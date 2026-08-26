"""Interview scheduling and structured scorecard feedback (tenant-scoped)."""
from __future__ import annotations

import json

from ats import new_id
from database import Database, utcnow


class InterviewService:
    def __init__(self, db: Database):
        self.db = db

    # --- Scorecard templates -------------------------------------------------
    def create_template(self, organization_id: str, *, name: str,
                        questions: list[str]) -> str:
        template_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO scorecard_templates
                (id,organization_id,name,questions_json,created_at) VALUES (?,?,?,?,?)""",
                (template_id, organization_id, name.strip(), json.dumps(questions), utcnow()))
        return template_id

    def templates(self, organization_id: str) -> list[dict]:
        return self.db.rows("SELECT * FROM scorecard_templates WHERE organization_id=? ORDER BY name",
                            (organization_id,))

    # --- Interviews ----------------------------------------------------------
    def schedule(self, organization_id: str, *, application_id: str, title: str,
                 scheduled_at: str | None = None, duration_minutes: int = 45,
                 location: str = "", stage_id: str | None = None,
                 interviewer_ids: list[str] | None = None, created_by: str | None = None) -> str:
        application = self.db.one("SELECT id FROM applications WHERE id=? AND organization_id=?",
                                  (application_id, organization_id))
        if not application:
            raise ValueError("Application not found")
        interview_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO interviews
                (id,organization_id,application_id,stage_id,title,scheduled_at,duration_minutes,
                 location,status,feedback_status,created_by,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (interview_id, organization_id, application_id, stage_id, title.strip(),
                 scheduled_at, duration_minutes, location.strip(), "Scheduled", "Pending",
                 created_by, utcnow()))
            for user_id in (interviewer_ids or []):
                tx.execute("""INSERT INTO interview_participants
                    (id,organization_id,interview_id,user_id,role) VALUES (?,?,?,?,?)""",
                    (new_id(), organization_id, interview_id, user_id, "interviewer"))
        return interview_id

    def interviews_for(self, organization_id: str, application_id: str) -> list[dict]:
        return self.db.rows("""SELECT * FROM interviews
            WHERE organization_id=? AND application_id=? ORDER BY created_at DESC""",
            (organization_id, application_id))

    # --- Scorecards ----------------------------------------------------------
    def submit_scorecard(self, organization_id: str, *, application_id: str,
                         interviewer_user_id: str, answers: list[dict],
                         overall: float | None = None, recommendation: str = "",
                         summary: str = "", interview_id: str | None = None,
                         template_id: str | None = None) -> str:
        application = self.db.one("SELECT id FROM applications WHERE id=? AND organization_id=?",
                                  (application_id, organization_id))
        if not application:
            raise ValueError("Application not found")
        scorecard_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO scorecards
                (id,organization_id,application_id,interview_id,template_id,interviewer_user_id,
                 overall,recommendation,summary,status,submitted_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (scorecard_id, organization_id, application_id, interview_id, template_id,
                 interviewer_user_id, overall, recommendation, summary, "Submitted",
                 utcnow(), utcnow()))
            for answer in answers:
                tx.execute("""INSERT INTO scorecard_answers
                    (id,scorecard_id,question,rating,comment) VALUES (?,?,?,?,?)""",
                    (new_id(), scorecard_id, answer["question"],
                     answer.get("rating"), answer.get("comment", "")))
            if interview_id:
                tx.execute("""UPDATE interviews SET feedback_status='Submitted'
                    WHERE id=? AND organization_id=?""", (interview_id, organization_id))
        return scorecard_id

    def scorecards_for(self, organization_id: str, application_id: str) -> list[dict]:
        cards = self.db.rows("""SELECT s.*,u.name interviewer_name FROM scorecards s
            LEFT JOIN users u ON u.id=s.interviewer_user_id
            WHERE s.organization_id=? AND s.application_id=? ORDER BY s.created_at DESC""",
            (organization_id, application_id))
        for card in cards:
            card["answers"] = self.db.rows(
                "SELECT * FROM scorecard_answers WHERE scorecard_id=?", (card["id"],))
        return cards
