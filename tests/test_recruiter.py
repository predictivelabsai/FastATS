from __future__ import annotations

from agents.recruiter import RecruiterContext, build_tools, extract_artifact, system_prompt_for
from ats import ATSService, new_id
from auth import hash_password
from database import utcnow
from skills_service import SkillsService


def bootstrap(db, slug="one"):
    org, user, now = new_id(), new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)", (user, f"a@{slug}.test", "Admin", hash_password("x"), now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (new_id(), org, user, "admin", now))
    return org, user


def scenario(db):
    org, user = bootstrap(db)
    service = ATSService(db)
    job = service.create_job(org, title="Engineer", description="Build", requirements="Python", created_by=user)
    cand = service.add_candidate(org, first_name="Ada", last_name="Lovelace", email="ada@x.test",
                                 headline="python backend")
    app = service.apply(org, cand, job)
    return org, user, service, job, cand, app


def tools_by_name(db, org):
    return {t.name: t for t in build_tools(RecruiterContext(db, org))}


def test_tool_set_and_artifact_roundtrip(database):
    org, user, service, job, cand, app = scenario(database)
    tools = tools_by_name(database, org)
    assert {"search_candidates", "get_candidate", "list_jobs", "summarize_pipeline",
            "draft_outreach", "queue_screening", "propose_stage_move",
            "propose_create_job"} <= set(tools)
    out = tools["list_jobs"].invoke({})
    art, text = extract_artifact(out)
    assert art["kind"] == "jobs" and any(j["title"] == "Engineer" for j in art["jobs"])
    assert "Engineer" in text


def test_propose_stage_move_does_not_move(database):
    org, user, service, job, cand, app = scenario(database)
    before = database.one("SELECT stage_id FROM applications WHERE id=?", (app,))
    tools = tools_by_name(database, org)
    out = tools["propose_stage_move"].invoke({"application_id": app, "stage_name": "Screen"})
    art, _ = extract_artifact(out)
    # It only proposes — a confirm artifact pointing at the human-gated route.
    assert art["kind"] == "confirm" and art["url"] == f"/applications/{app}/stage"
    after = database.one("SELECT stage_id FROM applications WHERE id=?", (app,))
    assert after == before


def test_skills_shape_the_system_prompt(database):
    org, user, service, job, cand, app = scenario(database)
    SkillsService(database).seed_builtins(org)
    prompt = system_prompt_for(RecruiterContext(database, org), "please shortlist candidates")
    assert "Ada" in prompt and "Shortlist builder" in prompt
