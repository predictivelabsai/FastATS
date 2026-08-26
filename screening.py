"""Evidence-backed screening that cannot mutate applications.

Scoring runs through a compiled LangGraph graph (see ``agents.screening_graph``)
against a provider-agnostic chat model (``MODEL_PROVIDER``); this module owns the
DB context load, the evaluator, and persistence of the run. The evaluator stays
injectable so the suite drives the real graph with a scripted decision and no key.
"""
from __future__ import annotations

import json
from typing import Callable

from agents.screening_graph import CriterionScore, ScreeningDecision, run_screening
from ats import new_id
from config import settings
from database import Database, utcnow

__all__ = ["CriterionScore", "ScreeningDecision", "llm_evaluator", "screen_application"]


def llm_evaluator(job: dict, candidate: dict, resume_text: str) -> ScreeningDecision:
    from agents.models import build_chat_model
    model = build_chat_model()
    structured = model.with_structured_output(ScreeningDecision)
    prompt = f"""You are an assistive recruiter screening agent. Score only job-related evidence.
Never make a hiring decision and never recommend rejection or an offer. Missing evidence is not negative evidence.

JOB TITLE: {job['title']}
DESCRIPTION: {job['description']}
REQUIREMENTS: {job['requirements']}

CANDIDATE HEADLINE: {candidate.get('headline') or ''}
RESUME TEXT:
{resume_text[:30000]}

Return an evidence-backed score and one of: Strong review, Review, Hold, Insufficient evidence."""
    return structured.invoke(prompt)


def screen_application(db: Database, organization_id: str, application_id: str,
                       document_id: str | None = None,
                       evaluator: Callable[[dict, dict, str], ScreeningDecision] = llm_evaluator) -> str:
    context = db.one("""SELECT a.*,j.title,j.description,j.requirements,
        c.first_name,c.last_name,c.headline,c.email FROM applications a
        JOIN jobs j ON j.id=a.job_id JOIN candidates c ON c.id=a.candidate_id
        WHERE a.id=? AND a.organization_id=?""", (application_id, organization_id))
    if not context:
        raise ValueError("Application not found")
    if document_id:
        document = db.one("""SELECT * FROM documents WHERE organization_id=?
            AND application_id=? AND id=?""", (organization_id, application_id, document_id))
    else:
        document = db.one("""SELECT * FROM documents WHERE organization_id=? AND application_id=?
            ORDER BY created_at DESC LIMIT 1""", (organization_id, application_id))
    run_id, now = new_id(), utcnow()
    with db.transaction() as tx:
        tx.execute("""INSERT INTO screening_runs
            (id,organization_id,application_id,document_id,model,status,created_at)
            VALUES (?,?,?,?,?,'Running',?)""",
            (run_id, organization_id, application_id, document["id"] if document else None,
             settings.model_name, now))
    try:
        result = run_screening(
            evaluator,
            job={"title": context["title"], "description": context["description"],
                 "requirements": context["requirements"]},
            candidate={"first_name": context["first_name"], "last_name": context["last_name"],
                       "headline": context["headline"]},
            resume_text=(document or {}).get("extracted_text") or "No readable resume text was supplied.")
        raw = result.model_dump_json()
        with db.transaction() as tx:
            tx.execute("""UPDATE screening_runs SET status='Completed',score=?,explanation=?,
                strengths_json=?,gaps_json=?,recommendation=?,raw_response=?,completed_at=? WHERE id=?""",
                (result.score, result.explanation, json.dumps(result.strengths), json.dumps(result.gaps),
                 result.recommendation, raw, utcnow(), run_id))
            for criterion in result.criteria:
                tx.execute("""INSERT INTO screening_criteria
                    (id,screening_run_id,criterion,score,evidence,explanation) VALUES (?,?,?,?,?,?)""",
                    (new_id(), run_id, criterion.criterion, criterion.score,
                     criterion.evidence, criterion.explanation))
            tx.execute("""INSERT INTO activity_events
                (id,organization_id,entity_type,entity_id,event_type,actor_user_id,payload_json,created_at)
                VALUES (?,?,?,?,?,NULL,?,?)""", (new_id(), organization_id, "application",
                application_id, "screening.completed", json.dumps({"run_id": run_id,
                "score": result.score, "recommendation": result.recommendation}), utcnow()))
    except Exception as exc:
        with db.transaction() as tx:
            tx.execute("UPDATE screening_runs SET status='Error',error=?,completed_at=? WHERE id=?",
                       (str(exc), utcnow(), run_id))
            tx.execute("""INSERT INTO activity_events
                (id,organization_id,entity_type,entity_id,event_type,actor_user_id,payload_json,created_at)
                VALUES (?,?,?,?,?,NULL,?,?)""", (new_id(), organization_id, "application",
                application_id, "screening.failed", json.dumps({"run_id": run_id, "error": str(exc)}), utcnow()))
        raise
    return run_id
