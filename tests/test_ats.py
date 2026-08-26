from __future__ import annotations

import json

import pytest

from ats import ATSService, new_id
from auth import hash_password
from database import utcnow
from documents import extract_text
from screening import CriterionScore, ScreeningDecision, screen_application
from worker import process_one


def bootstrap(db, slug="one"):
    org, user, now = new_id(), new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)", (user, f"admin@{slug}.test", "Admin", hash_password("x"), now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (new_id(), org, user, "admin", now))
    return org, user


def test_public_application_is_idempotent(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    job = service.create_job(org, title="Engineer", description="Build it", requirements="Python", created_by=user)
    service.publish_job(org, job, user)
    first = service.public_apply("one", "engineer", {"first_name": "Ada", "last_name": "Lovelace",
        "email": "ADA@example.test", "consent": "yes"})
    second = service.public_apply("one", "engineer", {"first_name": "Ada", "last_name": "Lovelace",
        "email": "ada@example.test", "consent": "yes"})
    assert first["application_id"] == second["application_id"]
    assert database.scalar("SELECT COUNT(*) FROM candidates") == 1
    assert database.scalar("SELECT COUNT(*) FROM applications") == 1


def test_tenant_scoping_blocks_cross_org_reads_and_moves(database):
    org1, user1 = bootstrap(database, "one")
    org2, user2 = bootstrap(database, "two")
    service = ATSService(database)
    job = service.create_job(org1, title="Engineer", description="Build", requirements="Python", created_by=user1)
    candidate = service.add_candidate(org1, first_name="Ada", last_name="Lovelace", email="ada@example.test")
    application = service.apply(org1, candidate, job)
    assert service.candidate(org2, candidate) is None
    foreign_stage = service.create_job(org2, title="Designer", description="Design", requirements="Portfolio", created_by=user2)
    with pytest.raises(ValueError):
        service.move_application(org1, application, service.stages(org2, foreign_stage)[0]["id"], user1, "admin")


def test_screening_records_evidence_but_never_moves_application(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    job = service.create_job(org, title="Engineer", description="Build", requirements="Python", created_by=user)
    candidate = service.add_candidate(org, first_name="Ada", last_name="Lovelace", email="ada@example.test")
    application = service.apply(org, candidate, job)
    original = database.one("SELECT stage_id,status FROM applications WHERE id=?", (application,))

    def evaluator(job, candidate, text):
        return ScreeningDecision(score=88, explanation="Relevant evidence", strengths=["Python"], gaps=[],
            recommendation="Strong review", criteria=[CriterionScore(criterion="Python", score=90,
                evidence="Built Python APIs", explanation="Direct evidence")])

    screen_application(database, org, application, evaluator=evaluator)
    assert database.one("SELECT stage_id,status FROM applications WHERE id=?", (application,)) == original
    run = database.one("SELECT * FROM screening_runs WHERE application_id=?", (application,))
    assert run["score"] == 88 and run["recommendation"] == "Strong review"
    assert database.scalar("SELECT COUNT(*) FROM screening_criteria WHERE screening_run_id=?", (run["id"],)) == 1


def test_only_humans_can_move_applications(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    job = service.create_job(org, title="Engineer", description="Build", requirements="Python", created_by=user)
    candidate = service.add_candidate(org, first_name="Ada", last_name="Lovelace", email="ada@example.test")
    application = service.apply(org, candidate, job)
    with pytest.raises(PermissionError):
        service.move_application(org, application, service.stages(org, job)[1]["id"], user, "agent")


def test_plain_resume_extraction():
    assert extract_text("resume.txt", b"Ada Lovelace\nPython engineer") == "Ada Lovelace\nPython engineer"
    with pytest.raises(ValueError):
        extract_text("resume.exe", b"not a resume")


def test_database_queue_processes_screening_job(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    job = service.create_job(org, title="Engineer", description="Build", requirements="Python", created_by=user)
    candidate = service.add_candidate(org, first_name="Ada", last_name="Lovelace", email="ada@example.test")
    application = service.apply(org, candidate, job)
    service.enqueue_screening(org, application)

    def evaluator(job, candidate, text):
        return ScreeningDecision(score=75, explanation="Review", strengths=["Python"], gaps=[],
            recommendation="Review", criteria=[])

    assert process_one(database, evaluator=evaluator)
    assert database.one("SELECT status FROM job_queue")["status"] == "Completed"
    assert database.one("SELECT status FROM screening_runs")["status"] == "Completed"
