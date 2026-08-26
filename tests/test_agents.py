from __future__ import annotations

from types import SimpleNamespace

from agents import content
from agents.assistant import AssistantContext, build_tools
from agents.screening_graph import ScreeningDecision, build_screening_graph
from ats import ATSService, new_id
from auth import hash_password
from database import utcnow


class FakeModel:
    """Minimal chat model: echoes a canned reply, records the last prompt."""

    def __init__(self, reply: str = "GENERATED"):
        self.reply = reply
        self.last_prompt = None

    def invoke(self, prompt):
        self.last_prompt = prompt
        return SimpleNamespace(content=self.reply)


def bootstrap(db, slug="one"):
    org, user, now = new_id(), new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
        tx.execute("INSERT INTO users VALUES (?,?,?,?,1,?)", (user, f"a@{slug}.test", "Admin", hash_password("x"), now))
        tx.execute("INSERT INTO memberships VALUES (?,?,?,?,?)", (new_id(), org, user, "admin", now))
    return org, user


def test_screening_graph_is_compiled_and_runs():
    def evaluator(job, candidate, text):
        assert text  # prepare node guarantees non-empty text
        return ScreeningDecision(score=70, explanation="ok", strengths=["Python"], gaps=[],
                                 recommendation="Review", criteria=[])
    graph = build_screening_graph(evaluator)
    result = graph.invoke({"job": {"title": "Eng", "description": "d", "requirements": "r"},
                           "candidate": {"first_name": "Ada"}, "resume_text": ""})
    assert result["decision"].score == 70


def test_content_helpers_use_injected_model():
    model = FakeModel("A great JD")
    jd = content.generate_job_description(model, title="Backend Engineer", notes="Python, Postgres")
    assert jd == "A great JD"
    assert "Backend Engineer" in model.last_prompt
    assert content.summarize_feedback(model, scorecards=[]) == \
        "No interview feedback has been submitted yet."


def test_assistant_tools_are_org_scoped_and_readonly(database):
    org, user = bootstrap(database)
    service = ATSService(database)
    job = service.create_job(org, title="Engineer", description="Build", requirements="Python", created_by=user)
    candidate = service.add_candidate(org, first_name="Ada", last_name="Lovelace",
                                      email="ada@x.test", headline="Python engineer")
    service.apply(org, candidate, job)
    tools = {t.name: t for t in build_tools(AssistantContext(database, org))}
    assert set(tools) == {"search_candidates", "get_candidate_context", "summarize_pipeline"}
    found = tools["search_candidates"].invoke({"query": "python"})
    assert "Ada Lovelace" in found

    # A different org sees nothing — tenant scoping holds inside tools.
    org2, _ = bootstrap(database, "two")
    tools2 = {t.name: t for t in build_tools(AssistantContext(database, org2))}
    assert tools2["search_candidates"].invoke({"query": "python"}) == "No matching candidates."
