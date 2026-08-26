"""Editable skills: recruiter-authored playbooks that shape the agent.

A skill is a named block of natural-language instructions (a mini system prompt)
plus optional trigger keywords and a tool allow-list. Enabled skills are composed
into the agent's system prompt at runtime; skills whose triggers match the user's
message are marked active so the agent applies them first. Recruiters create and
edit skills in the UI — no code change needed to teach the agent a new playbook.
"""
from __future__ import annotations

from ats import new_id
from database import Database, utcnow

BUILTIN_SKILLS = [
    {
        "name": "Shortlist builder",
        "description": "Rank and shortlist candidates for a role from the evidence.",
        "instructions": (
            "When asked to shortlist or rank candidates for a job, use semantic search "
            "and each candidate's screening evidence. Present a ranked list with a one-line "
            "justification per candidate citing concrete evidence. Never fabricate evidence, "
            "and never advance or reject anyone — propose next steps for the recruiter to confirm."),
        "triggers": "shortlist,rank,best candidates,top candidates,who should",
        "allowed_tools": "search_candidates,get_candidate_context,summarize_pipeline",
    },
    {
        "name": "Outreach writer",
        "description": "Draft warm, concise candidate outreach.",
        "instructions": (
            "When asked to write outreach, draft a personal, non-pushy email under 150 words "
            "referencing the candidate's headline and the role. Return the draft for the "
            "recruiter to review and send — do not send email yourself."),
        "triggers": "outreach,email,reach out,contact,message",
        "allowed_tools": "get_candidate_context,draft_outreach",
    },
    {
        "name": "Pipeline analyst",
        "description": "Summarize pipeline health and surface bottlenecks.",
        "instructions": (
            "When asked about pipeline health, summarize stage counts, flag stages where "
            "candidates are piling up, and suggest where the recruiter should focus. Base "
            "everything on the actual pipeline data."),
        "triggers": "pipeline,funnel,bottleneck,stuck,stage",
        "allowed_tools": "summarize_pipeline,list_jobs",
    },
]


class SkillsService:
    def __init__(self, db: Database):
        self.db = db

    def create_skill(self, organization_id: str, *, name: str, description: str,
                     instructions: str, triggers: str = "", allowed_tools: str = "",
                     enabled: bool = True, is_builtin: bool = False,
                     created_by: str | None = None) -> str:
        name = name.strip()
        if not name or not instructions.strip():
            raise ValueError("A skill needs a name and instructions")
        existing = self.db.one("SELECT id FROM skills WHERE organization_id=? AND name=?",
                               (organization_id, name))
        if existing:
            return existing["id"]
        skill_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO skills
                (id,organization_id,name,description,instructions,triggers,allowed_tools,
                 enabled,is_builtin,created_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (skill_id, organization_id, name, description.strip(), instructions.strip(),
                 triggers.strip(), allowed_tools.strip(), int(enabled), int(is_builtin),
                 created_by, now, now))
        return skill_id

    def update_skill(self, organization_id: str, skill_id: str, **fields) -> None:
        allowed = {"name", "description", "instructions", "triggers", "allowed_tools", "enabled"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key}=?")
            values.append(int(value) if key == "enabled" else value)
        if not sets:
            return
        sets.append("updated_at=?")
        values.extend([utcnow(), skill_id, organization_id])
        with self.db.transaction() as tx:
            tx.execute(f"UPDATE skills SET {','.join(sets)} WHERE id=? AND organization_id=?",
                       tuple(values))

    def toggle(self, organization_id: str, skill_id: str) -> None:
        skill = self.skill(organization_id, skill_id)
        if skill:
            self.update_skill(organization_id, skill_id, enabled=0 if skill["enabled"] else 1)

    def delete_skill(self, organization_id: str, skill_id: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM skills WHERE id=? AND organization_id=? AND is_builtin=0",
                       (skill_id, organization_id))

    def skill(self, organization_id: str, skill_id: str) -> dict | None:
        return self.db.one("SELECT * FROM skills WHERE id=? AND organization_id=?",
                          (skill_id, organization_id))

    def skills(self, organization_id: str, *, enabled_only: bool = False) -> list[dict]:
        query = "SELECT * FROM skills WHERE organization_id=?"
        if enabled_only:
            query += " AND enabled=1"
        return self.db.rows(query + " ORDER BY name", (organization_id,))

    def seed_builtins(self, organization_id: str, created_by: str | None = None) -> None:
        for spec in BUILTIN_SKILLS:
            self.create_skill(organization_id, is_builtin=True, created_by=created_by, **spec)

    def active_for(self, organization_id: str, message: str) -> list[dict]:
        """Enabled skills whose triggers appear in the message (all, if none match)."""
        enabled = self.skills(organization_id, enabled_only=True)
        text = (message or "").lower()
        matched = []
        for skill in enabled:
            triggers = [t.strip().lower() for t in (skill["triggers"] or "").split(",") if t.strip()]
            if any(trigger in text for trigger in triggers):
                matched.append(skill)
        return matched or enabled

    def compose_system_prompt(self, organization_id: str, base_prompt: str,
                              message: str = "") -> str:
        active = self.active_for(organization_id, message)
        if not active:
            return base_prompt
        blocks = [f"## Skill: {s['name']}\n{s['instructions']}" for s in active]
        return base_prompt + "\n\nActive skills (apply these playbooks):\n\n" + "\n\n".join(blocks)
