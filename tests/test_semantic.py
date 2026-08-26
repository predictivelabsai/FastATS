from __future__ import annotations

from ats import ATSService, new_id
from auth import hash_password
from database import utcnow
from embeddings import FakeEmbedder
from semantic import index_entity, search_candidates
from worker import process_one


def bootstrap(db, slug="one"):
    org, user, now = new_id(), new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)", (user, f"a@{slug}.test", "Admin", hash_password("x"), now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (new_id(), org, user, "admin", now))
    return org, user


def test_semantic_search_ranks_and_scopes(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    embedder = FakeEmbedder(dim=256)
    maya = service.add_candidate(org, first_name="Maya", last_name="Chen", email="maya@x.test",
                                 headline="python postgresql backend reliability engineer")
    leila = service.add_candidate(org, first_name="Leila", last_name="Haddad", email="leila@x.test",
                                  headline="product designer figma research systems")
    index_entity(database, org, "candidate", maya, "python postgresql backend reliability", embedder=embedder)
    index_entity(database, org, "candidate", leila, "product designer figma research", embedder=embedder)

    ranked = search_candidates(database, org, "backend python postgres", embedder=embedder)
    assert ranked[0]["id"] == maya

    org2, _ = bootstrap(database, "two")
    assert search_candidates(database, org2, "backend python", embedder=embedder) == []


def test_worker_processes_embed_job(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    candidate = service.add_candidate(org, first_name="Maya", last_name="Chen", email="m@x.test")
    service.enqueue_embedding(org, "candidate", candidate, "python backend")
    assert process_one(database, embedder=FakeEmbedder(dim=64))
    assert database.one("SELECT status FROM job_queue")["status"] == "Completed"
    assert database.scalar("SELECT COUNT(*) FROM embeddings WHERE entity_id=?", (candidate,)) == 1


def test_worker_processes_sequence_step(database):
    from crm import CRMService
    from emailer import ConsoleEmailer
    org, user = bootstrap(database)
    service = ATSService(database)
    candidate = service.add_candidate(org, first_name="Maya", last_name="Chen", email="m@x.test")
    crm = CRMService(database, emailer=ConsoleEmailer())
    seq = crm.create_sequence(org, name="Nurture", created_by=user,
                              steps=[{"subject": "Hi", "body": "hello", "delay_hours": 0}])
    enrollment = crm.enroll(org, seq, candidate, enrolled_by=user)
    service.enqueue_sequence_step(org, enrollment)
    assert process_one(database, emailer=ConsoleEmailer())
    assert database.one("SELECT status FROM job_queue")["status"] == "Completed"
    assert database.scalar("SELECT COUNT(*) FROM messages WHERE candidate_id=?", (candidate,)) == 1
