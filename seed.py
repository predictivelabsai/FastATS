"""Idempotent synthetic FastATS seed data."""
from __future__ import annotations

import json

from ats import ATSService, new_id
from auth import hash_password
from config import settings
from database import Database, get_database, utcnow


def build(db: Database | None = None) -> dict:
    db = db or get_database()
    db.migrate()
    existing = db.one("SELECT * FROM organizations WHERE slug='northstar-labs'")
    if existing:
        return existing
    now = utcnow()
    organization_id, user_id = new_id(), new_id()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)",
                   (organization_id, "Northstar Labs", "northstar-labs", now))
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)",
                   (user_id, settings.admin_email, "Alex Recruiter", hash_password(settings.admin_password), now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)",
                   (new_id(), organization_id, user_id, "admin", now))
        tx.execute("INSERT INTO career_sites VALUES (?,?,?,?,?,?)",
                   (new_id(), organization_id, "Northstar Careers",
                    "Build dependable products with a thoughtful team.", "#5145cd", now))
    service = ATSService(db)
    roles = [
        ("Senior Backend Engineer", "Build reliable Python services for a growing product.",
         "Strong Python, PostgreSQL, API design, testing, and production operations experience.", "Tallinn / Hybrid"),
        ("Product Designer", "Shape calm, fast workflows for complex business software.",
         "Product design portfolio, research, systems thinking, and accessible interaction design.", "Remote Europe"),
    ]
    job_ids = []
    for title, description, requirements, location in roles:
        job_id = service.create_job(organization_id, title=title, description=description,
                                    requirements=requirements, location=location, created_by=user_id)
        service.publish_job(organization_id, job_id, user_id)
        job_ids.append(job_id)
    candidates = [
        ("Maya", "Chen", "maya.chen@example.test", "Backend engineer focused on dependable Python systems", "Referral"),
        ("Jonas", "Tamm", "jonas.tamm@example.test", "Platform engineer with PostgreSQL and observability experience", "Careers"),
        ("Leila", "Haddad", "leila.haddad@example.test", "Product designer for complex SaaS workflows", "Sourced"),
    ]
    for index, (first, last, email, headline, source) in enumerate(candidates):
        candidate_id = service.add_candidate(organization_id, first_name=first, last_name=last,
            email=email, location="Tallinn" if index < 2 else "Berlin", headline=headline,
            source=source, consent=True)
        application_id = service.apply(organization_id, candidate_id, job_ids[0 if index < 2 else 1], source=source)
        if index == 0:
            screen_stage = service.stages(organization_id, job_ids[0])[1]
            service.move_application(organization_id, application_id, screen_stage["id"], user_id, "admin")
            run_id = new_id()
            with db.transaction() as tx:
                tx.execute("""INSERT INTO screening_runs
                    (id,organization_id,application_id,model,status,score,explanation,strengths_json,gaps_json,
                     recommendation,raw_response,created_at,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, organization_id, application_id, settings.model_name, "Completed", 86,
                     "Strong direct evidence for the role's Python, database, and reliability requirements.",
                     json.dumps(["Production Python", "PostgreSQL", "Operational ownership"]),
                     json.dumps(["No evidence supplied for high-scale queue design"]), "Strong review", "{}", now, now))
                tx.execute("INSERT INTO screening_criteria VALUES (?,?,?,?,?,?)",
                    (new_id(), run_id, "Python delivery", 92, "Five years building Python APIs",
                     "Direct and recent production experience."))
    return db.one("SELECT * FROM organizations WHERE id=?", (organization_id,))


if __name__ == "__main__":
    org = build()
    print(f"Seeded {org['name']} ({org['slug']})")
