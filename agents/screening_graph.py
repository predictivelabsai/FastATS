"""Screening as a compiled LangGraph StateGraph.

Topology: prepare -> score -> finalize. The scoring node calls an injected
`evaluator(job, candidate, resume_text) -> ScreeningDecision`, so the real graph
runs in tests with a scripted evaluator — no API key required. The default
evaluator is the Grok-backed one in `screening.py`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, TypedDict

from pydantic import BaseModel, Field


class CriterionScore(BaseModel):
    criterion: str
    score: float = Field(ge=0, le=100)
    evidence: str
    explanation: str


class ScreeningDecision(BaseModel):
    score: float = Field(ge=0, le=100)
    explanation: str
    strengths: list[str]
    gaps: list[str]
    recommendation: str = Field(description="One of Strong review, Review, Hold, or Insufficient evidence")
    criteria: list[CriterionScore]


Evaluator = Callable[[dict, dict, str], ScreeningDecision]


class ScreeningState(TypedDict, total=False):
    job: dict[str, Any]
    candidate: dict[str, Any]
    resume_text: str
    decision: ScreeningDecision
    error: str


def build_screening_graph(evaluator: Evaluator, checkpointer: Optional[Any] = None):
    """Compile the screening graph around an injected evaluator."""
    from langgraph.graph import StateGraph, START, END

    def prepare(state: ScreeningState) -> ScreeningState:
        text = (state.get("resume_text") or "").strip()
        if not text:
            text = "No readable resume text was supplied."
        return {"resume_text": text[:30000]}

    def score(state: ScreeningState) -> ScreeningState:
        decision = evaluator(state["job"], state["candidate"], state["resume_text"])
        return {"decision": decision}

    graph = StateGraph(ScreeningState)
    graph.add_node("prepare", prepare)
    graph.add_node("score", score)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "score")
    graph.add_edge("score", END)
    return graph.compile(checkpointer=checkpointer)


def run_screening(evaluator: Evaluator, *, job: dict, candidate: dict,
                  resume_text: str) -> ScreeningDecision:
    graph = build_screening_graph(evaluator)
    result = graph.invoke({"job": job, "candidate": candidate, "resume_text": resume_text})
    return result["decision"]
