from __future__ import annotations

import pytest

from analytics import AnalyticsService
from ats import ATSService, new_id
from auth import hash_password
from crm import CRMService
from database import utcnow
from emailer import ConsoleEmailer
from interviews import InterviewService


def bootstrap(db, slug="one"):
    org, user, now = new_id(), new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)", (user, f"admin@{slug}.test", "Admin", hash_password("x"), now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (new_id(), org, user, "admin", now))
    return org, user


def make_candidate(db, org, user, email="ada@example.test"):
    service = ATSService(db)
    job = service.create_job(org, title="Engineer", description="Build", requirements="Python", created_by=user)
    candidate = service.add_candidate(org, first_name="Ada", last_name="Lovelace", email=email)
    application = service.apply(org, candidate, job)
    return service, job, candidate, application


def test_notes_are_scoped_and_ordered(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    service.add_note(org, "candidate", candidate, "First contact", user)
    service.add_note(org, "candidate", candidate, "Strong portfolio", user)
    notes = service.notes(org, "candidate", candidate)
    assert [n["body"] for n in notes] == ["Strong portfolio", "First contact"]
    org2, _ = bootstrap(database, "two")
    assert service.notes(org2, "candidate", candidate) == []
    with pytest.raises(ValueError):
        service.add_note(org, "candidate", candidate, "   ", user)


def test_tags_are_idempotent_and_removable(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    service.tag_entity(org, "candidate", candidate, "Referral")
    service.tag_entity(org, "candidate", candidate, "Referral")
    tags = service.tags_for(org, "candidate", candidate)
    assert len(tags) == 1 and tags[0]["name"] == "Referral"
    service.untag_entity(org, "candidate", candidate, tags[0]["id"])
    assert service.tags_for(org, "candidate", candidate) == []


def test_custom_fields_upsert(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    service.set_custom_field(org, "candidate", candidate, "salary_expectation", "90k")
    service.set_custom_field(org, "candidate", candidate, "salary_expectation", "95k")
    assert service.custom_fields(org, "candidate", candidate) == {"salary_expectation": "95k"}


def test_talent_pool_membership_is_deduped_and_scoped(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    crm = CRMService(database, emailer=ConsoleEmailer())
    pool = crm.create_pool(org, name="Backend bench", created_by=user)
    crm.add_to_pool(org, pool, candidate, added_by=user)
    crm.add_to_pool(org, pool, candidate, added_by=user)
    assert len(crm.pool_members(org, pool)) == 1
    org2, user2 = bootstrap(database, "two")
    with pytest.raises(ValueError):
        crm.add_to_pool(org2, pool, candidate, added_by=user2)


def test_email_sequence_runs_all_steps(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    crm = CRMService(database, emailer=ConsoleEmailer())
    sequence = crm.create_sequence(org, name="Nurture", created_by=user, steps=[
        {"subject": "Hello", "body": "Intro", "delay_hours": 0},
        {"subject": "Follow up", "body": "Checking in", "delay_hours": 0}])
    enrollment = crm.enroll(org, sequence, candidate, enrolled_by=user)
    assert crm.process_enrollment(org, enrollment) == "Active"
    assert crm.process_enrollment(org, enrollment) == "Completed"
    messages = crm.messages_for(org, candidate)
    assert [m["subject"] for m in messages] == ["Follow up", "Hello"]
    assert all(m["status"] == "logged" for m in messages)


def test_interview_and_scorecard_flow(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    interviews = InterviewService(database)
    interview = interviews.schedule(org, application_id=application, title="System design",
                                    interviewer_ids=[user], created_by=user)
    scorecard = interviews.submit_scorecard(org, application_id=application,
        interviewer_user_id=user, interview_id=interview, overall=4.5,
        recommendation="Advance", answers=[{"question": "Depth", "rating": 5, "comment": "Excellent"}])
    cards = interviews.scorecards_for(org, application)
    assert len(cards) == 1 and cards[0]["overall"] == 4.5
    assert cards[0]["answers"][0]["comment"] == "Excellent"
    updated = interviews.interviews_for(org, application)[0]
    assert updated["feedback_status"] == "Submitted"


def test_analytics_funnel_and_sources(database):
    org, user = bootstrap(database)
    service, job, candidate, application = make_candidate(database, org, user)
    analytics = AnalyticsService(database)
    funnel = analytics.funnel(org, job)
    assert funnel[0]["name"] == "Applied" and funnel[0]["count"] == 1
    sources = analytics.source_effectiveness(org)
    assert sources[0]["total"] == 1
    assert analytics.overview(org)["applications"] == 1
    assert "Applied" in analytics.time_in_stage(org)
