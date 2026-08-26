"""The recruiting agent that drives the whole app from one chat.

Read tools execute immediately and return an ``__ARTIFACT__`` payload the chat
renders in its canvas. Action tools that would change state never execute — they
return a *proposal* artifact with a confirm URL, so a human commits every stage
move, send, or job creation. Editable skills (see ``skills_service``) are composed
into the system prompt, so recruiters teach the agent new playbooks without code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from database import Database

ARTIFACT = "__ARTIFACT__"

BASE_SYSTEM = (
    "You are Ada, the recruiting agent inside FastATS. You drive the whole product "
    "from this chat: you can search and explain candidates, summarize pipelines, draft "
    "outreach, and propose actions. You are strictly assistive about state changes — you "
    "NEVER move a candidate between stages, reject, advance, offer, or send email yourself. "
    "For any such action, call the matching propose_* tool, which returns a confirmation for "
    "the recruiter to click. Always ground answers in tool results and cite the evidence. "
    "Be concise and practical."
)


def _artifact(kind: str, text: str, **payload: Any) -> str:
    envelope = {"kind": kind, **payload}
    return f"{ARTIFACT}{json.dumps(envelope)}\n\n{text}"


def extract_artifact(tool_output: str) -> tuple[dict | None, str]:
    """Split a tool result into (artifact_dict_or_None, human_text)."""
    if not isinstance(tool_output, str) or not tool_output.startswith(ARTIFACT):
        return None, tool_output or ""
    body = tool_output[len(ARTIFACT):]
    head, _, text = body.partition("\n\n")
    try:
        return json.loads(head), text
    except (ValueError, TypeError):
        return None, tool_output


@dataclass
class RecruiterContext:
    db: Database
    organization_id: str
    role: str = "recruiter"


def build_tools(ctx: RecruiterContext) -> list:
    from langchain_core.tools import tool
    from ats import ATSService
    from semantic import search_candidates as semantic_search
    service = ATSService(ctx.db)
    org = ctx.organization_id

    @tool
    def search_candidates(query: str) -> str:
        """Semantically search candidates in this organization by skills, role, or profile."""
        rows = semantic_search(ctx.db, org, query, limit=8)
        if not rows:
            return _artifact("candidates", "No matching candidates.", candidates=[])
        items = [{"id": r["id"], "name": f"{r['first_name']} {r['last_name']}",
                  "headline": r.get("headline") or r["email"], "score": r.get("score", 0)}
                 for r in rows]
        text = "Top matches:\n" + "\n".join(f"- {i['name']} — {i['headline']}" for i in items)
        return _artifact("candidates", text, title=f"Candidates for “{query}”", candidates=items)

    @tool
    def get_candidate(candidate_id: str) -> str:
        """Get a candidate's full profile: applications, stages, and latest screening."""
        candidate = service.candidate(org, candidate_id)
        if not candidate:
            return "Candidate not found in this organization."
        apps = [{"job": a["job_title"], "stage": a["stage_name"],
                 "screening": a.get("screening_recommendation"),
                 "score": a.get("screening_score")} for a in candidate.get("applications", [])]
        name = f"{candidate['first_name']} {candidate['last_name']}"
        text = f"{name} ({candidate['email']})\n" + "\n".join(
            f"- {a['job']} @ {a['stage']}; screening {a['screening'] or 'none'} ({a['score'] or '—'}/100)"
            for a in apps)
        return _artifact("candidate", text, title=name, candidate_id=candidate_id,
                         email=candidate["email"], applications=apps)

    @tool
    def list_jobs() -> str:
        """List this organization's jobs with application counts."""
        jobs = service.jobs(org)
        items = [{"id": j["id"], "title": j["title"], "status": j["status"],
                  "applications": j["applications"]} for j in jobs]
        text = "\n".join(f"- {j['title']} ({j['status']}) — {j['applications']} applications" for j in items)
        return _artifact("jobs", text or "No jobs yet.", title="Jobs", jobs=items)

    @tool
    def summarize_pipeline(job_id: str) -> str:
        """Summarize how many candidates sit in each stage of a job's pipeline."""
        stages = service.pipeline(org, job_id)
        if not stages:
            return "No pipeline found for that job."
        rows = [{"stage": s["name"], "count": len(s["applications"])} for s in stages]
        text = "\n".join(f"{r['stage']}: {r['count']}" for r in rows)
        return _artifact("pipeline", text, title="Pipeline", stages=rows)

    @tool
    def draft_outreach(candidate_id: str, purpose: str) -> str:
        """Draft (but do not send) a warm outreach email to a candidate."""
        candidate = service.candidate(org, candidate_id)
        if not candidate:
            return "Candidate not found."
        try:
            from agents.content import generate_outreach_email
            from agents.models import build_chat_model
            body = generate_outreach_email(build_chat_model(), candidate=candidate, purpose=purpose)
        except Exception:
            body = (f"Hi {candidate['first_name']},\n\nI came across your profile "
                    f"({candidate.get('headline') or 'your background'}) and thought you might be a "
                    f"great fit. {purpose}\n\nWould you be open to a short chat?\n\nBest regards")
        return _artifact("draft", "Drafted an outreach email for your review.",
                         title=f"Outreach — {candidate['first_name']}", candidate_id=candidate_id,
                         body=body)

    @tool
    def queue_screening(application_id: str) -> str:
        """Queue assistive AI screening for an application (records evidence only, never changes state)."""
        app = ctx.db.one("SELECT id FROM applications WHERE id=? AND organization_id=?",
                         (application_id, org))
        if not app:
            return "Application not found."
        service.enqueue_screening(org, application_id)
        return _artifact("info", "Queued AI screening. It records evidence only — no stage change.",
                         title="Screening queued")

    @tool
    def propose_stage_move(application_id: str, stage_name: str) -> str:
        """Propose moving an application to a stage. Returns a confirmation for the recruiter — does not move it."""
        app = ctx.db.one("""SELECT a.id,a.job_id,c.first_name,c.last_name,s.name stage
            FROM applications a JOIN candidates c ON c.id=a.candidate_id
            JOIN pipeline_stages s ON s.id=a.stage_id
            WHERE a.id=? AND a.organization_id=?""", (application_id, org))
        if not app:
            return "Application not found."
        target = ctx.db.one("""SELECT id,name FROM pipeline_stages
            WHERE organization_id=? AND job_id=? AND lower(name)=lower(?)""",
            (org, app["job_id"], stage_name))
        if not target:
            return f"No stage named {stage_name!r} on this job."
        text = (f"Proposed: move {app['first_name']} {app['last_name']} "
                f"from {app['stage']} to {target['name']}. Confirm to apply.")
        return _artifact("confirm", text, title="Confirm stage move",
                         action="move_stage", label=f"Move to {target['name']}",
                         url=f"/applications/{application_id}/stage",
                         fields={"stage_id": target["id"]})

    @tool
    def propose_create_job(title: str, description: str, requirements: str, location: str = "") -> str:
        """Propose creating a draft job. Returns a confirmation for the recruiter — does not create it."""
        text = f"Proposed new job: {title}. Confirm to create the draft."
        return _artifact("confirm", text, title="Confirm new job", action="create_job",
                         label="Create draft job", url="/jobs",
                         fields={"title": title, "description": description,
                                 "requirements": requirements, "location": location})

    return [search_candidates, get_candidate, list_jobs, summarize_pipeline,
            draft_outreach, queue_screening, propose_stage_move, propose_create_job]


def build_agent(model: Any, ctx: RecruiterContext, system_prompt: str, checkpointer: Any | None = None):
    from langgraph.prebuilt import create_react_agent
    return create_react_agent(model, build_tools(ctx), prompt=system_prompt, checkpointer=checkpointer)


def system_prompt_for(ctx: RecruiterContext, message: str = "") -> str:
    """Base prompt + active editable skills for this org."""
    from skills_service import SkillsService
    return SkillsService(ctx.db).compose_system_prompt(ctx.organization_id, BASE_SYSTEM, message)
