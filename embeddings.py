"""Embedding boundary. A deterministic fake is the offline default so semantic
search and its tests run without a key; a hosted provider is opt-in."""
from __future__ import annotations

import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Hash-seeded unit vectors: deterministic, offline, and stable across runs.

    Not semantically meaningful, but identical text yields identical vectors, so
    similarity ordering is testable without any network call or API key.
    """

    def __init__(self, dim: int = 1536):
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in (text or "").lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            for i in range(0, len(digest), 4):
                bucket = int.from_bytes(digest[i:i + 4], "big") % self.dim
                vector[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]


class HostedEmbedder:
    """OpenAI-compatible embeddings endpoint (OpenAI, or any drop-in like xAI)."""

    def __init__(self, *, api_key: str, base_url: str, model: str, dim: int):
        from openai import OpenAI  # lazy import; optional dependency
        self.dim = dim
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


def get_embedder(settings=None) -> Embedder:
    if settings is None:
        from config import settings as _settings
        settings = _settings
    if settings.embeddings_backend == "hosted" and settings.embeddings_api_key:
        return HostedEmbedder(
            api_key=settings.embeddings_api_key,
            base_url=settings.embeddings_base_url,
            model=settings.embeddings_model,
            dim=settings.embeddings_dim)
    return FakeEmbedder(dim=settings.embeddings_dim)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
