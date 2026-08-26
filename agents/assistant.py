"""Recruiter assistant graph.

The assistant is READ-ONLY over recruiting data by design: it can search, read
context, summarize, and *draft* text, but it never moves stages, sends email, or
otherwise changes application state. Mutations are surfaced to the recruiter as
proposals to confirm in the UI. This keeps the project's safety model intact —
state transitions stay explicit human actions.

Tools are bound to an org-scoped context, and the chat model is injected so the
graph can be built with the real Grok model or a scripted fake in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from database import Database


@dataclass
class AssistantContext:
    db: Database
    organization_id: str


def build_tools(ctx: AssistantContext) -> list:
    from langchain_core.tools import tool
    from ats import ATSService
    service = ATSService(ctx.db)
    org = ctx.organization_id

    @tool
    def search_candidates(query: str) -> str:
        """Search candidates in this organization by name, email, or headline."""
        like = f"%{query.lower()}%"
        rows = ctx.db.rows(
            """SELECT id,first_name,last_name,email,headline FROM candidates
               WHERE organization_id=? AND (lower(first_name||' '||last_name) LIKE ?
                     OR lower(email) LIKE ? OR lower(coalesce(headline,'')) LIKE ?)
               ORDER BY last_name LIMIT 10""", (org, like, like, like))
        if not rows:
            return "No matching candidates."
        return "\n".join(f"{r['id']}: {r['first_name']} {r['last_name']} — "
                         f"{r['headline'] or r['email']}" for r in rows)

    @tool
    def get_candidate_context(candidate_id: str) -> str:
        """Get a candidate's full profile: applications, stages, and latest screening."""
        candidate = service.candidate(org, candidate_id)
        if not candidate:
            return "Candidate not found in this organization."
        parts = [f"{candidate['first_name']} {candidate['last_name']} ({candidate['email']})"]
        for app in candidate.get("applications", []):
            parts.append(f"- {app['job_title']} @ stage {app['stage_name']}; "
                         f"screening: {app.get('screening_recommendation') or 'none'} "
                         f"({app.get('screening_score') or '—'}/100)")
        return "\n".join(parts)

    @tool
    def summarize_pipeline(job_id: str) -> str:
        """Summarize how many candidates sit in each stage of a job's pipeline."""
        stages = service.pipeline(org, job_id)
        if not stages:
            return "No pipeline found for that job."
        return "\n".join(f"{s['name']}: {len(s['applications'])}" for s in stages)

    return [search_candidates, get_candidate_context, summarize_pipeline]


SYSTEM_PROMPT = (
    "You are FastATS's recruiting assistant. You help recruiters find and "
    "understand candidates and pipelines. You are strictly assistive: you never "
    "move a candidate between stages, reject, advance, offer, or send email. "
    "When a recruiter asks for such an action, explain what you would do and tell "
    "them to confirm it themselves in the app. Always cite the evidence you used."
)


def build_assistant_graph(model: Any, ctx: AssistantContext, checkpointer: Any | None = None):
    """Compile a ReAct assistant bound to org-scoped, read-only tools."""
    from langgraph.prebuilt import create_react_agent
    return create_react_agent(model, build_tools(ctx), prompt=SYSTEM_PROMPT,
                              checkpointer=checkpointer)
