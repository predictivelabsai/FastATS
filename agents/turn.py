"""Run one agent turn and stream it as Server-Sent Events.

Maps LangGraph ``astream_events`` to the SSE contract the chat client consumes:
  token        incremental assistant text
  tool_start   {"name": ...}   a tool began
  artifact     {...}           a canvas payload from a tool
  done         {"text": ...}   final assistant text (for persistence)
  error        {"message": ...}
Without a model key it degrades to a single helpful message so the chat still loads.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from agents.recruiter import RecruiterContext, build_agent, extract_artifact, system_prompt_for
from config import settings


def sse(event: str, data) -> str:
    return f"data: {json.dumps({'event': event, 'data': data})}\n\n"


NO_KEY_MESSAGE = (
    "I need a model API key to think — set MODEL_PROVIDER and the matching key "
    "(e.g. XAI_API_KEY) and I'll come online. Meanwhile, semantic search, the skills "
    "editor, and every workspace page work without it."
)


async def stream_turn(ctx: RecruiterContext, message: str,
                      history: list[dict]) -> AsyncIterator[str]:
    if not settings.llm_api_key:
        yield sse("token", NO_KEY_MESSAGE)
        yield sse("done", {"text": NO_KEY_MESSAGE, "artifacts": []})
        return

    try:
        from agents.models import build_chat_model
        model = build_chat_model()
        agent = build_agent(model, ctx, system_prompt_for(ctx, message))
    except Exception as exc:  # pragma: no cover - config/runtime
        msg = f"Agent unavailable: {exc}"
        yield sse("error", {"message": msg})
        yield sse("done", {"text": msg, "artifacts": []})
        return

    convo = [{"role": m["role"], "content": m["content"]} for m in history
             if m["role"] in ("user", "assistant")]
    convo.append({"role": "user", "content": message})

    collected: list[str] = []
    artifacts: list[dict] = []
    try:
        async for event in agent.astream_events({"messages": convo}, version="v2"):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                text = getattr(chunk, "content", "") or ""
                if isinstance(text, list):  # some providers stream content parts
                    text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
                if text:
                    collected.append(text)
                    yield sse("token", text)
            elif kind == "on_tool_start":
                yield sse("tool_start", {"name": event.get("name", "tool")})
            elif kind == "on_tool_end":
                output = event["data"].get("output")
                content = getattr(output, "content", output)
                if not isinstance(content, str):
                    content = str(content)
                artifact, _ = extract_artifact(content)
                if artifact:
                    artifacts.append(artifact)
                    yield sse("artifact", artifact)
    except Exception as exc:  # pragma: no cover - network/runtime
        yield sse("error", {"message": str(exc)})

    final = "".join(collected).strip() or "(no response)"
    yield sse("done", {"text": final, "artifacts": artifacts})
