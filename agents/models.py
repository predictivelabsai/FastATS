"""Model + checkpointer factories for the agent graphs."""
from __future__ import annotations

from typing import Any

from config import settings


def build_chat_model(*, temperature: float = 0, **kwargs: Any):
    """Provider-agnostic chat model via LangChain.

    Selected by ``MODEL_PROVIDER`` (xai default; openai/anthropic/google_genai
    supported). Raises when the selected provider has no key configured, so tests
    must inject a fake rather than reach the network.
    """
    provider = settings.model_provider
    api_key = settings.llm_api_key
    if not api_key:
        raise RuntimeError(f"No API key configured for MODEL_PROVIDER={provider!r}")

    if provider == "xai":
        # Keep ChatXAI directly so the custom base_url is honored.
        from langchain_xai import ChatXAI
        return ChatXAI(model=settings.model_name, temperature=temperature, timeout=90,
                       max_retries=2, api_key=api_key, base_url=settings.xai_base_url, **kwargs)

    from langchain.chat_models import init_chat_model
    return init_chat_model(settings.model_name, model_provider=provider,
                           temperature=temperature, api_key=api_key, **kwargs)


def build_checkpointer(backend: str | None = None):
    """LangGraph checkpointer. Memory by default; sqlite/postgres are opt-in.

    Returns None when LangGraph is not installed so graphs can still be compiled
    checkpointer-free in minimal environments.
    """
    backend = (backend or settings.checkpointer_backend).lower()
    try:
        if backend == "postgres" and settings.database_url:
            from langgraph.checkpoint.postgres import PostgresSaver
            saver = PostgresSaver.from_conn_string(settings.database_url)
            saver.setup()
            return saver
        if backend == "sqlite":
            from langgraph.checkpoint.sqlite import SqliteSaver
            return SqliteSaver.from_conn_string(settings.database_path)
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()
    except Exception:
        return None
