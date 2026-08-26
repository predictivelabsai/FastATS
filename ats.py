"""Tenant-scoped ATS domain services."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from database import Database, utcnow

DEFAULT_STAGES = ("Applied", "Screen", "Interview", "Offer", "Hired", "Rejected")
HUMAN_ROLES = {"admin", "recruiter", "hiring_manager"}


def new_id() -> str:
    return str(uuid.uuid4())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "role"


class ATSService:
    def __init__(self, db: Database):
        self.db = db

    def create_job(self, organization_id: str, *, title: str, description: str,
                   requirements: str, location: str = "", employment_type: str = "Permanent",
                   created_by: str | None = None, stages: tuple[str, ...] = DEFAULT_STAGES) -> str:
        base = slugify(title)
        slug, suffix = base, 2
        while self.db.one("SELECT id FROM jobs WHERE organization_id=? AND slug=?",
                          (organization_id, slug)):
            slug, suffix = f"{base}-{suffix}", suffix + 1
        job_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO jobs
                (id,organization_id,title,slug,description,requirements,location,employment_type,status,created_by,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, organization_id, title.strip(), slug, description.strip(), requirements.strip(),
                 location.strip(), employment_type, "Draft", created_by, now))
            for position, name in enumerate(stages):
                tx.execute("""INSERT INTO pipeline_stages
                    (id,organization_id,job_id,name,position,terminal) VALUES (?,?,?,?,?,?)""",
                    (new_id(), organization_id, job_id, name, position,
                     int(name in {"Hired", "Rejected"})))
        self.log(organization_id, "job", job_id, "job.created", created_by,
                 {"title": title, "status": "Draft"})
        return job_id

    def publish_job(self, organization_id: str, job_id: str, actor_user_id: str) -> None:
        job = self.job(organization_id, job_id)
        if not job or not job["description"] or not job["requirements"]:
            raise ValueError("A publishable job needs a description and requirements")
        with self.db.transaction() as tx:
            tx.execute("UPDATE jobs SET status='Published' WHERE id=? AND organization_id=?",
                       (job_id, organization_id))
        self.log(organization_id, "job", job_id, "job.published", actor_user_id, {})

    def jobs(self, organization_id: str) -> list[dict]:
        return self.db.rows("""SELECT j.*,
            (SELECT COUNT(*) FROM applications a WHERE a.job_id=j.id AND a.organization_id=j.organization_id) applications
            FROM jobs j WHERE j.organization_id=? ORDER BY j.created_at DESC""", (organization_id,))

    def job(self, organization_id: str, job_id: str) -> dict | None:
        return self.db.one("SELECT * FROM jobs WHERE id=? AND organization_id=?", (job_id, organization_id))

    def stages(self, organization_id: str, job_id: str) -> list[dict]:
        return self.db.rows("""SELECT * FROM pipeline_stages
            WHERE organization_id=? AND job_id=? ORDER BY position""", (organization_id, job_id))

    def pipeline(self, organization_id: str, job_id: str) -> list[dict]:
        stages = self.stages(organization_id, job_id)
        applications = self.db.rows("""SELECT a.*,c.first_name,c.last_name,c.email,c.headline,
                   s.name stage_name
              FROM applications a JOIN candidates c ON c.id=a.candidate_id
              JOIN pipeline_stages s ON s.id=a.stage_id
             WHERE a.organization_id=? AND a.job_id=? ORDER BY a.applied_at DESC""",
            (organization_id, job_id))
        by_stage = {stage["id"]: [] for stage in stages}
        for application in applications:
            by_stage.setdefault(application["stage_id"], []).append(application)
        return [{**stage, "applications": by_stage.get(stage["id"], [])} for stage in stages]

    def add_candidate(self, organization_id: str, *, first_name: str, last_name: str,
                      email: str, phone: str = "", location: str = "", headline: str = "",
                      source: str = "Direct", consent: bool = False) -> str:
        canonical = email.strip().lower()
        if not first_name.strip() or not last_name.strip() or "@" not in canonical:
            raise ValueError("First name, last name, and a valid email are required")
        existing = self.db.one("SELECT id FROM candidates WHERE organization_id=? AND email=?",
                               (organization_id, canonical))
        if existing:
            return existing["id"]
        candidate_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO candidates
                (id,organization_id,first_name,last_name,email,phone,location,headline,source,consent_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (candidate_id, organization_id, first_name.strip(), last_name.strip(), canonical,
                 phone.strip(), location.strip(), headline.strip(), source, now if consent else None, now))
        return candidate_id

    def apply(self, organization_id: str, candidate_id: str, job_id: str,
              *, source: str = "Direct", actor_user_id: str | None = None) -> str:
        existing = self.db.one("""SELECT id FROM applications
            WHERE organization_id=? AND candidate_id=? AND job_id=?""",
            (organization_id, candidate_id, job_id))
        if existing:
            return existing["id"]
        stage = self.db.one("""SELECT id FROM pipeline_stages
            WHERE organization_id=? AND job_id=? ORDER BY position LIMIT 1""", (organization_id, job_id))
        if not stage:
            raise ValueError("Job has no pipeline")
        application_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO applications
                (id,organization_id,candidate_id,job_id,stage_id,status,source,applied_at,stage_entered_at)
                VALUES (?,?,?,?,?,'Active',?,?,?)""",
                (application_id, organization_id, candidate_id, job_id, stage["id"], source, now, now))
        self.log(organization_id, "application", application_id, "application.created",
                 actor_user_id, {"job_id": job_id, "candidate_id": candidate_id})
        return application_id

    def public_jobs(self) -> list[dict]:
        return self.db.rows("""SELECT j.*,o.name organization_name,o.slug organization_slug,
            cs.headline site_headline,cs.brand_color FROM jobs j
            JOIN organizations o ON o.id=j.organization_id
            LEFT JOIN career_sites cs ON cs.organization_id=j.organization_id
            WHERE j.status='Published' ORDER BY j.created_at DESC""")

    def public_job(self, organization_slug: str, job_slug: str) -> dict | None:
        return self.db.one("""SELECT j.*,o.name organization_name,o.slug organization_slug,
            cs.headline site_headline,cs.brand_color FROM jobs j
            JOIN organizations o ON o.id=j.organization_id
            LEFT JOIN career_sites cs ON cs.organization_id=j.organization_id
            WHERE o.slug=? AND j.slug=? AND j.status='Published'""", (organization_slug, job_slug))

    def public_apply(self, organization_slug: str, job_slug: str, values: dict[str, str]) -> dict:
        job = self.public_job(organization_slug, job_slug)
        if not job:
            raise ValueError("Published job not found")
        if values.get("consent") != "yes":
            raise ValueError("Consent is required")
        candidate_id = self.add_candidate(job["organization_id"], first_name=values.get("first_name", ""),
            last_name=values.get("last_name", ""), email=values.get("email", ""),
            phone=values.get("phone", ""), location=values.get("location", ""),
            source="Careers", consent=True)
        application_id = self.apply(job["organization_id"], candidate_id, job["id"], source="Careers")
        self.log(job["organization_id"], "candidate", candidate_id, "candidate.consent_recorded", None,
                 {"purpose": "Recruitment", "job_id": job["id"]})
        return {"organization_id": job["organization_id"], "candidate_id": candidate_id,
                "application_id": application_id, "job": job}

    def move_application(self, organization_id: str, application_id: str, stage_id: str,
                         actor_user_id: str, role: str) -> None:
        if role not in HUMAN_ROLES:
            raise PermissionError("This role cannot move applications")
        application = self.db.one("SELECT * FROM applications WHERE id=? AND organization_id=?",
                                  (application_id, organization_id))
        if not application:
            raise ValueError("Application not found")
        stage = self.db.one("""SELECT * FROM pipeline_stages
            WHERE id=? AND organization_id=? AND job_id=?""",
            (stage_id, organization_id, application["job_id"]))
        if not stage:
            raise ValueError("Stage is not part of this job")
        old = self.db.one("SELECT name FROM pipeline_stages WHERE id=?", (application["stage_id"],))
        status = "Hired" if stage["name"] == "Hired" else "Rejected" if stage["name"] == "Rejected" else "Active"
        with self.db.transaction() as tx:
            tx.execute("""UPDATE applications SET stage_id=?,status=?,stage_entered_at=?
                WHERE id=? AND organization_id=?""", (stage_id, status, utcnow(), application_id, organization_id))
        self.log(organization_id, "application", application_id, "application.stage_changed",
                 actor_user_id, {"from": old["name"] if old else "", "to": stage["name"]})

    def candidate(self, organization_id: str, candidate_id: str) -> dict | None:
        candidate = self.db.one("SELECT * FROM candidates WHERE id=? AND organization_id=?",
                                (candidate_id, organization_id))
        if not candidate:
            return None
        candidate["applications"] = self.db.rows("""SELECT a.*,j.title job_title,s.name stage_name,
            sr.status screening_status,sr.score screening_score,sr.explanation screening_explanation,
            sr.strengths_json screening_strengths,sr.gaps_json screening_gaps,
            sr.recommendation screening_recommendation
            FROM applications a JOIN jobs j ON j.id=a.job_id JOIN pipeline_stages s ON s.id=a.stage_id
            LEFT JOIN screening_runs sr ON sr.id=(SELECT id FROM screening_runs latest
                WHERE latest.organization_id=a.organization_id AND latest.application_id=a.id
                ORDER BY latest.created_at DESC LIMIT 1)
            WHERE a.organization_id=? AND a.candidate_id=? ORDER BY a.applied_at DESC""",
            (organization_id, candidate_id))
        candidate["activity"] = self.db.rows("""SELECT * FROM activity_events
            WHERE organization_id=? AND ((entity_type='candidate' AND entity_id=?) OR
            (entity_type='application' AND entity_id IN
              (SELECT id FROM applications WHERE organization_id=? AND candidate_id=?)))
            ORDER BY created_at DESC LIMIT 50""", (organization_id, candidate_id, organization_id, candidate_id))
        return candidate

    def candidates(self, organization_id: str) -> list[dict]:
        return self.db.rows("""SELECT c.*,(SELECT COUNT(*) FROM applications a
            WHERE a.organization_id=c.organization_id AND a.candidate_id=c.id) applications
            FROM candidates c WHERE c.organization_id=? ORDER BY c.created_at DESC""", (organization_id,))

    def add_document(self, organization_id: str, candidate_id: str, application_id: str,
                     *, file_name: str, content_type: str, object_key: str,
                     extracted_text: str = "") -> str:
        document_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO documents
                (id,organization_id,candidate_id,application_id,kind,file_name,content_type,object_key,extracted_text,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (document_id, organization_id, candidate_id, application_id, "Resume", file_name,
                 content_type, object_key, extracted_text, utcnow()))
        return document_id

    def enqueue_screening(self, organization_id: str, application_id: str,
                          document_id: str | None = None) -> str:
        job_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO job_queue
                (id,organization_id,kind,payload_json,status,attempts,available_at,created_at)
                VALUES (?,?,? ,?,'Pending',0,?,?)""",
                (job_id, organization_id, "screen_application",
                 json.dumps({"application_id": application_id, "document_id": document_id}), utcnow(), utcnow()))
        return job_id

    def enqueue_embedding(self, organization_id: str, entity_type: str, entity_id: str,
                          text: str) -> str:
        job_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO job_queue
                (id,organization_id,kind,payload_json,status,attempts,available_at,created_at)
                VALUES (?,?,?,?,'Pending',0,?,?)""",
                (job_id, organization_id, "embed_entity",
                 json.dumps({"entity_type": entity_type, "entity_id": entity_id, "text": text}),
                 utcnow(), utcnow()))
        return job_id

    def enqueue_sequence_step(self, organization_id: str, enrollment_id: str) -> str:
        job_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO job_queue
                (id,organization_id,kind,payload_json,status,attempts,available_at,created_at)
                VALUES (?,?,?,?,'Pending',0,?,?)""",
                (job_id, organization_id, "send_sequence_step",
                 json.dumps({"enrollment_id": enrollment_id}), utcnow(), utcnow()))
        return job_id

    def screening_runs(self, organization_id: str, application_id: str) -> list[dict]:
        return self.db.rows("""SELECT * FROM screening_runs
            WHERE organization_id=? AND application_id=? ORDER BY created_at DESC""",
            (organization_id, application_id))

    # --- Notes ---------------------------------------------------------------
    def add_note(self, organization_id: str, entity_type: str, entity_id: str,
                 body: str, author_user_id: str | None) -> str:
        if not body.strip():
            raise ValueError("A note cannot be empty")
        note_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO notes
                (id,organization_id,entity_type,entity_id,author_user_id,body,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (note_id, organization_id, entity_type, entity_id, author_user_id,
                 body.strip(), utcnow()))
        self.log(organization_id, entity_type, entity_id, "note.added", author_user_id, {})
        return note_id

    def notes(self, organization_id: str, entity_type: str, entity_id: str) -> list[dict]:
        return self.db.rows("""SELECT n.*,u.name author_name FROM notes n
            LEFT JOIN users u ON u.id=n.author_user_id
            WHERE n.organization_id=? AND n.entity_type=? AND n.entity_id=?
            ORDER BY n.created_at DESC""", (organization_id, entity_type, entity_id))

    # --- Tags ----------------------------------------------------------------
    def ensure_tag(self, organization_id: str, name: str, color: str = "#5145cd") -> str:
        name = name.strip()
        if not name:
            raise ValueError("Tag name is required")
        existing = self.db.one("SELECT id FROM tags WHERE organization_id=? AND name=?",
                               (organization_id, name))
        if existing:
            return existing["id"]
        tag_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("INSERT INTO tags (id,organization_id,name,color,created_at) VALUES (?,?,?,?,?)",
                       (tag_id, organization_id, name, color, utcnow()))
        return tag_id

    def tag_entity(self, organization_id: str, entity_type: str, entity_id: str,
                   name: str, color: str = "#5145cd") -> str:
        tag_id = self.ensure_tag(organization_id, name, color)
        existing = self.db.one("""SELECT id FROM taggables
            WHERE tag_id=? AND entity_type=? AND entity_id=?""", (tag_id, entity_type, entity_id))
        if existing:
            return existing["id"]
        link_id = new_id()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO taggables
                (id,organization_id,tag_id,entity_type,entity_id,created_at) VALUES (?,?,?,?,?,?)""",
                (link_id, organization_id, tag_id, entity_type, entity_id, utcnow()))
        return link_id

    def untag_entity(self, organization_id: str, entity_type: str, entity_id: str, tag_id: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("""DELETE FROM taggables WHERE organization_id=? AND tag_id=?
                AND entity_type=? AND entity_id=?""",
                (organization_id, tag_id, entity_type, entity_id))

    def tags_for(self, organization_id: str, entity_type: str, entity_id: str) -> list[dict]:
        return self.db.rows("""SELECT t.id,t.name,t.color FROM taggables tg
            JOIN tags t ON t.id=tg.tag_id
            WHERE tg.organization_id=? AND tg.entity_type=? AND tg.entity_id=?
            ORDER BY t.name""", (organization_id, entity_type, entity_id))

    # --- Custom fields (simple per-entity key/value) -------------------------
    def set_custom_field(self, organization_id: str, entity_type: str, entity_id: str,
                         field_key: str, value: str) -> None:
        field_key = field_key.strip()
        if not field_key:
            raise ValueError("Custom field key is required")
        existing = self.db.one("""SELECT id FROM custom_field_values
            WHERE organization_id=? AND entity_type=? AND entity_id=? AND field_key=?""",
            (organization_id, entity_type, entity_id, field_key))
        with self.db.transaction() as tx:
            if existing:
                tx.execute("UPDATE custom_field_values SET value=? WHERE id=?", (value, existing["id"]))
            else:
                tx.execute("""INSERT INTO custom_field_values
                    (id,organization_id,entity_type,entity_id,field_key,value,created_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (new_id(), organization_id, entity_type, entity_id, field_key, value, utcnow()))

    def custom_fields(self, organization_id: str, entity_type: str, entity_id: str) -> dict[str, str]:
        rows = self.db.rows("""SELECT field_key,value FROM custom_field_values
            WHERE organization_id=? AND entity_type=? AND entity_id=? ORDER BY field_key""",
            (organization_id, entity_type, entity_id))
        return {row["field_key"]: row["value"] for row in rows}

    # --- Bulk actions --------------------------------------------------------
    def bulk_move(self, organization_id: str, application_ids: list[str], stage_id: str,
                  actor_user_id: str, role: str) -> int:
        moved = 0
        for application_id in application_ids:
            try:
                self.move_application(organization_id, application_id, stage_id, actor_user_id, role)
                moved += 1
            except (ValueError, PermissionError):
                continue
        return moved

    def bulk_add_to_pool(self, organization_id: str, pool_id: str,
                         candidate_ids: list[str], actor_user_id: str) -> int:
        added = 0
        for candidate_id in candidate_ids:
            existing = self.db.one("""SELECT id FROM pool_memberships
                WHERE pool_id=? AND candidate_id=?""", (pool_id, candidate_id))
            if existing:
                continue
            with self.db.transaction() as tx:
                tx.execute("""INSERT INTO pool_memberships
                    (id,organization_id,pool_id,candidate_id,added_by,created_at) VALUES (?,?,?,?,?,?)""",
                    (new_id(), organization_id, pool_id, candidate_id, actor_user_id, utcnow()))
            added += 1
        return added

    def log(self, organization_id: str, entity_type: str, entity_id: str,
            event_type: str, actor_user_id: str | None, payload: dict[str, Any]) -> None:
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO activity_events
                (id,organization_id,entity_type,entity_id,event_type,actor_user_id,payload_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)""", (new_id(), organization_id, entity_type, entity_id,
                event_type, actor_user_id, json.dumps(payload), utcnow()))
