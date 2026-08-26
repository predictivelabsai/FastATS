"""Content-generation helpers: JD writer, outreach, and feedback summaries.

Each takes an injected chat model (anything with ``.invoke(prompt).content``),
so tests pass a scripted fake and no key is needed. Production passes the Grok
model from ``agents.models.build_chat_model``.
"""
from __future__ import annotations

from typing import Any


def _text(model: Any, prompt: str) -> str:
    result = model.invoke(prompt)
    return getattr(result, "content", str(result)).strip()


def generate_job_description(model: Any, *, title: str, notes: str = "",
                             tone: str = "clear and inclusive") -> str:
    prompt = f"""Write a job description for the role "{title}".
Tone: {tone}. Include a short summary, key responsibilities, and requirements.
Avoid biased or exclusionary language. Do not invent salary or benefits.

Context / notes from the hiring team:
{notes or '(none)'}"""
    return _text(model, prompt)


def generate_outreach_email(model: Any, *, candidate: dict, purpose: str,
                            role_title: str = "") -> str:
    name = f"{candidate.get('first_name', '')}".strip() or "there"
    prompt = f"""Write a concise, warm recruiting outreach email.
Recipient first name: {name}
Their headline: {candidate.get('headline') or '(unknown)'}
Role of interest: {role_title or '(general)'}
Purpose: {purpose}

Keep it under 150 words, personal, and non-pushy. Return only the email body."""
    return _text(model, prompt)


def summarize_feedback(model: Any, *, scorecards: list[dict]) -> str:
    if not scorecards:
        return "No interview feedback has been submitted yet."
    lines = []
    for card in scorecards:
        lines.append(f"- {card.get('interviewer_name') or 'Interviewer'}: "
                     f"overall {card.get('overall')}, {card.get('recommendation') or ''}. "
                     f"{card.get('summary') or ''}")
    joined = "\n".join(lines)
    prompt = f"""Summarize the interview debrief below into a balanced recommendation.
Note agreements, disagreements, and open risks. Be evidence-based and neutral;
do not make the final hiring decision.

Feedback:
{joined}"""
    return _text(model, prompt)


def generate_interview_questions(model: Any, *, role_title: str, focus: str = "") -> str:
    prompt = f"""Generate 6 structured interview questions for a "{role_title}" interview.
Focus area: {focus or 'general competency'}. Mix behavioral and technical.
Return a numbered list only."""
    return _text(model, prompt)
