from __future__ import annotations

from ats import new_id
from chat import ChatService
from database import utcnow
from skills_service import SkillsService


def seed_org(db, slug="one"):
    org, now = new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("INSERT INTO organizations VALUES (?,?,?,?)", (org, slug.title(), slug, now))
    return org


def test_chat_thread_and_messages(database):
    org = seed_org(database)
    chat = ChatService(database)
    thread = chat.create_thread(org, None)
    chat.add_message(org, thread, "user", "Who are my best backend candidates?")
    chat.rename_from_first_message(org, thread, "Who are my best backend candidates?")
    chat.add_message(org, thread, "assistant", "Here is a shortlist...")
    loaded = chat.thread(org, thread)
    assert len(loaded["messages"]) == 2
    assert loaded["title"].startswith("Who are my best")
    # tenant scoping
    org2 = seed_org(database, "two")
    assert chat.thread(org2, thread) is None


def test_skills_crud_and_toggle(database):
    org = seed_org(database)
    skills = SkillsService(database)
    sid = skills.create_skill(org, name="Diversity lens", description="Check for bias",
                              instructions="Flag biased language in job posts.",
                              triggers="bias,diversity,inclusive")
    assert len(skills.skills(org)) == 1
    skills.toggle(org, sid)
    assert skills.skills(org, enabled_only=True) == []
    skills.toggle(org, sid)
    assert len(skills.skills(org, enabled_only=True)) == 1
    skills.update_skill(org, sid, instructions="Updated guidance")
    assert skills.skill(org, sid)["instructions"] == "Updated guidance"


def test_skill_composition_and_triggers(database):
    org = seed_org(database)
    skills = SkillsService(database)
    skills.seed_builtins(org)
    assert len(skills.skills(org)) == len(__import__("skills_service").BUILTIN_SKILLS)
    # A message about shortlisting activates the shortlist skill by trigger.
    active = skills.active_for(org, "please shortlist the top candidates")
    assert any(s["name"] == "Shortlist builder" for s in active)
    prompt = skills.compose_system_prompt(org, "BASE", "please shortlist the top candidates")
    assert "BASE" in prompt and "Shortlist builder" in prompt


def test_builtin_skills_cannot_be_deleted(database):
    org = seed_org(database)
    skills = SkillsService(database)
    skills.seed_builtins(org)
    builtin = skills.skills(org)[0]
    skills.delete_skill(org, builtin["id"])
    assert skills.skill(org, builtin["id"]) is not None  # still there
