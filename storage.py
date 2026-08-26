"""File storage boundary; local storage is the zero-config development backend."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Protocol


def _safe_key(organization_id: str, file_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name)
    return f"{organization_id}/{uuid.uuid4()}-{safe}"


class Storage(Protocol):
    def put(self, organization_id: str, file_name: str, data: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...
    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str | None: ...
    def presigned_put_url(self, organization_id: str, file_name: str,
                          content_type: str, expires_in: int = 3600) -> tuple[str, str] | None: ...


class LocalStorage:
    """Disk-backed storage; the default, needs no credentials."""

    def __init__(self, root: str):
        self.root = Path(root)

    def put(self, organization_id: str, file_name: str, data: bytes) -> str:
        key = _safe_key(organization_id, file_name)
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str | None:
        # Local disk has no signed URLs; the app streams these via a route.
        return None

    def presigned_put_url(self, organization_id: str, file_name: str,
                          content_type: str, expires_in: int = 3600) -> tuple[str, str] | None:
        return None


class R2Storage:
    """Cloudflare R2 (S3-compatible) storage via boto3."""

    def __init__(self, *, account_id: str, access_key_id: str, secret_access_key: str,
                 bucket: str, endpoint: str = ""):
        import boto3  # imported lazily so the base install stays free of boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

    def put(self, organization_id: str, file_name: str, data: bytes) -> str:
        key = _safe_key(organization_id, file_name)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def read(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str | None:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)

    def presigned_put_url(self, organization_id: str, file_name: str,
                          content_type: str, expires_in: int = 3600) -> tuple[str, str] | None:
        key = _safe_key(organization_id, file_name)
        url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in)
        return url, key


def get_storage(settings=None) -> Storage:
    """Build the configured storage backend (local by default)."""
    if settings is None:
        from config import settings as _settings
        settings = _settings
    if settings.storage_backend == "r2":
        return R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
            endpoint=settings.r2_endpoint)
    return LocalStorage(settings.upload_dir)
