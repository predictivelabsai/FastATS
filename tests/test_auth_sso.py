from __future__ import annotations

from auth import google_identity, hash_password
from ats import new_id
from database import utcnow


def seed_org(db, slug="one"):
    org, now = new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
    return org


def test_google_identity_provisions_first_time_user(database):
    org = seed_org(database)
    identity = google_identity(database, "New.Person@example.com", "New Person")
    assert identity is not None
    assert identity["email"] == "new.person@example.com"
    assert identity["organization_id"] == org
    assert identity["role"] == "admin"
    # A second login links the same user rather than duplicating.
    again = google_identity(database, "new.person@example.com", "New Person")
    assert again["user_id"] == identity["user_id"]
    assert database.scalar("SELECT COUNT(*) FROM users WHERE email=?", ("new.person@example.com",)) == 1


def test_google_identity_links_existing_user(database):
    org = seed_org(database)
    user = new_id()
    with database.transaction() as tx:
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)",
                   (user, "maya@example.com", "Maya", hash_password("x"), utcnow()))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)",
                   (new_id(), org, user, "recruiter", utcnow()))
    identity = google_identity(database, "maya@example.com", "Maya Chen")
    assert identity["user_id"] == user
    assert identity["role"] == "recruiter"


def test_google_identity_without_org_returns_none(database):
    assert google_identity(database, "nobody@example.com", "Nobody") is None
