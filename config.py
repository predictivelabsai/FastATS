"""Environment-backed FastATS configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("FASTATS_DATABASE_URL", "").strip()
    database_path: str = os.getenv("FASTATS_DB", str(ROOT / "data" / "fastats.sqlite"))
    database_schema: str = os.getenv("FASTATS_DB_SCHEMA", "fast_ats")
    secret: str = os.getenv("FASTATS_SECRET", "dev-only-fastats-secret")
    port: int = int(os.getenv("FASTATS_PORT", "5020"))
    admin_email: str = os.getenv("FASTATS_ADMIN_EMAIL", "admin@fastats.example").lower()
    admin_password: str = os.getenv("FASTATS_ADMIN_PASSWORD", "FastATS2026$")
    upload_dir: str = os.getenv("FASTATS_UPLOAD_DIR", str(ROOT / "data" / "uploads"))

    # Language model — provider-agnostic via LangChain.
    # MODEL_PROVIDER: xai (default) | openai | anthropic | google_genai | ...
    model_provider: str = os.getenv("MODEL_PROVIDER", "xai").lower()
    model_name: str = os.getenv("MODEL_NAME", "grok-4-1-fast-reasoning")
    xai_api_key: str = os.getenv("XAI_API_KEY", "")
    xai_base_url: str = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")

    @property
    def llm_api_key(self) -> str:
        """The API key for the currently selected chat provider."""
        return {
            "xai": self.xai_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google_genai": self.google_api_key,
        }.get(self.model_provider, "")

    # Object storage: "local" (default, zero-config) or "r2" (S3-compatible)
    storage_backend: str = os.getenv("FASTATS_STORAGE_BACKEND", "local").lower()
    r2_account_id: str = os.getenv("R2_ACCOUNT_ID", "")
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret_access_key: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    r2_bucket: str = os.getenv("R2_BUCKET", "")
    r2_endpoint: str = os.getenv("R2_ENDPOINT", "")

    # Embeddings: "fake" (default, deterministic, offline) or "hosted"
    embeddings_backend: str = os.getenv("FASTATS_EMBEDDINGS_BACKEND", "fake").lower()
    embeddings_model: str = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-small")
    # Falls back to the OpenAI chat key so hosted embeddings need no separate secret.
    embeddings_api_key: str = os.getenv("EMBEDDINGS_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    embeddings_base_url: str = os.getenv("EMBEDDINGS_BASE_URL", "https://api.openai.com/v1")
    embeddings_dim: int = int(os.getenv("EMBEDDINGS_DIM", "1536"))

    # LangGraph checkpointer: "memory" (default), "sqlite", or "postgres"
    checkpointer_backend: str = os.getenv("FASTATS_CHECKPOINTER", "memory").lower()

    # Outbound email: "console" (default, logs only), "smtp", or "postmark"
    email_backend: str = os.getenv("FASTATS_EMAIL_BACKEND", "console").lower()
    postmark_api_token: str = os.getenv("POSTMARK_API_TOKEN", "")
    from_email: str = os.getenv("FROM_EMAIL", "jobs@example.com")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")

    @property
    def has_vector_support(self) -> bool:
        """pgvector-backed semantic search is only available on PostgreSQL."""
        return bool(self.database_url)


settings = Settings()
