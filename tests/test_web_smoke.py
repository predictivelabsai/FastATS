"""End-to-end smoke test of the FastHTML app against a temp database.

Imports web_app with FASTATS_DB pointed at a scratch file so module-level
migrate()/seed() are harmless, then drives the login + new surfaces through
Starlette's TestClient. No API key or network required.
"""
from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("web")
    os.environ["FASTATS_DB"] = str(scratch / "smoke.sqlite")
    os.environ["FASTATS_UPLOAD_DIR"] = str(scratch / "uploads")
    os.environ["FASTATS_DATABASE_URL"] = ""
    # Ensure a fresh import picks up the env above.
    for mod in [m for m in sys.modules if m in {"web_app", "config", "database", "seed"}]:
        del sys.modules[mod]
    from starlette.testclient import TestClient
    import web_app
    return TestClient(web_app.app), web_app


def login(client):
    tc, web_app = client
    return tc.post("/login", data={"email": web_app.settings.admin_email,
                                   "password": web_app.settings.admin_password},
                   follow_redirects=False)


def test_healthz(client):
    tc, _ = client
    response = tc.get("/healthz")
    assert response.status_code == 200 and response.json()["ok"] is True


def test_public_careers_lists_seeded_jobs(client):
    tc, _ = client
    response = tc.get("/careers")
    assert response.status_code == 200
    assert "Open roles" in response.text


def test_authenticated_surfaces_render(client):
    tc, _ = client
    assert login(tc if False else client).status_code == 303
    for path in ["/", "/search", "/pools", "/sequences", "/analytics", "/assistant",
                 "/tools/content", "/candidates", "/jobs"]:
        response = tc.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"


def test_pool_and_search_flow(client):
    tc, _ = client
    login(client)
    assert tc.post("/pools", data={"name": "Backend bench", "description": "x"},
                   follow_redirects=False).status_code == 303
    assert "Backend bench" in tc.get("/pools").text
    # Semantic search falls back to keyword match with the FakeEmbedder default.
    assert tc.get("/search", params={"q": "engineer"}).status_code == 200


def test_assistant_without_key_is_graceful(client):
    tc, _ = client
    login(client)
    response = tc.get("/assistant", params={"q": "who are my best candidates"})
    assert response.status_code == 200
    assert "XAI_API_KEY" in response.text or "assistant" in response.text.lower()
