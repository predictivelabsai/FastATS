"""Small password and membership service for the independent FastATS app."""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid

from database import Database


def _utcnow() -> str:
    from database import utcnow
    return utcnow()


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def authenticate(db: Database, email: str, password: str) -> dict | None:
    user = db.one("SELECT * FROM users WHERE lower(email)=lower(?) AND active=1", (email.strip(),))
    if not user or not verify_password(password, user["password_hash"]):
        return None
    membership = db.one(
        """SELECT m.*,o.name organization_name,o.slug organization_slug
             FROM memberships m JOIN organizations o ON o.id=m.organization_id
            WHERE m.user_id=? ORDER BY m.created_at LIMIT 1""", (user["id"],))
    if not membership:
        return None
    return _identity(user, membership)


def _identity(user: dict, membership: dict) -> dict:
    return {"user_id": user["id"], "email": user["email"], "name": user["name"],
            "organization_id": membership["organization_id"], "role": membership["role"],
            "organization_name": membership["organization_name"]}


def _membership(db: Database, user_id: str) -> dict | None:
    return db.one(
        """SELECT m.*,o.name organization_name,o.slug organization_slug
             FROM memberships m JOIN organizations o ON o.id=m.organization_id
            WHERE m.user_id=? ORDER BY m.created_at LIMIT 1""", (user_id,))


def google_identity(db: Database, email: str, name: str) -> dict | None:
    """Resolve a verified Google email to a FastATS identity.

    Access is already gated at the OIDC layer (GOOGLE_ALLOWED_EMAILS/DOMAINS).
    Existing users are linked by email; a first-time SSO user is provisioned as
    an admin of the first organization so the fastsme login works out of the box.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return None
    user = db.one("SELECT * FROM users WHERE lower(email)=lower(?) AND active=1", (email,))
    if user:
        membership = _membership(db, user["id"])
        return _identity(user, membership) if membership else None

    org = db.one("SELECT id FROM organizations ORDER BY created_at LIMIT 1")
    if not org:
        return None
    user_id = str(uuid.uuid4())
    now = _utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)",
                   (user_id, email, name or email, "google-sso", now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()), org["id"], user_id, "admin", now))
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    membership = _membership(db, user_id)
    return _identity(user, membership) if membership else None

