"""Portable SQLite/PostgreSQL connections and numbered migrations."""
from __future__ import annotations

import atexit
import os
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"
SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_pools: dict[str, Any] = {}
_pool_lock = threading.Lock()


def _postgres_pool(url: str):
    pool = _pools.get(url)
    if pool is not None:
        return pool
    with _pool_lock:
        pool = _pools.get(url)
        if pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            pool = ConnectionPool(
                conninfo=url, min_size=0, max_size=int(os.getenv("DB_POOL_MAX_SIZE", "3")),
                timeout=10, kwargs={"row_factory": dict_row,
                                    "application_name": "fastats"}, open=True)
            _pools[url] = pool
    return pool


def close_pools() -> None:
    with _pool_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()


atexit.register(close_pools)


class Transaction:
    def __init__(self, connection, dialect: str):
        self.connection = connection
        self.dialect = dialect

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if self.dialect == "postgres" else query

    def execute(self, query: str, params: Sequence[Any] = ()):
        return self.connection.execute(self._sql(query), tuple(params))

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        row = self.execute(query, params).fetchone()
        return dict(row) if row else None

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.execute(query, params).fetchall()]

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        row = self.execute(query, params).fetchone()
        if not row:
            return None
        if isinstance(row, sqlite3.Row):
            return row[0]
        return next(iter(row.values()))


class Database:
    def __init__(self, *, url: str = "", path: str = "", schema: str = "fast_ats"):
        self.url = url.strip()
        self.path = path or str(ROOT / "data" / "fastats.sqlite")
        self.schema = schema.strip() or "fast_ats"
        self.dialect = "postgres" if self.url else "sqlite"
        if not SCHEMA_PATTERN.fullmatch(self.schema):
            raise ValueError("FASTATS_DB_SCHEMA contains an unsafe identifier")

    @classmethod
    def from_env(cls) -> "Database":
        return cls(url=os.getenv("FASTATS_DATABASE_URL", ""),
                   path=os.getenv("FASTATS_DB", str(ROOT / "data" / "fastats.sqlite")),
                   schema=os.getenv("FASTATS_DB_SCHEMA", "fast_ats"))

    def connect(self):
        if self.dialect == "sqlite":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            return connection
        pool = _postgres_pool(self.url)
        connection = pool.getconn()
        try:
            connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            connection.execute(f'SET search_path TO "{self.schema}", public')
        except Exception:
            pool.putconn(connection, close=True)
            raise
        return connection

    def _release(self, connection) -> None:
        if self.dialect == "postgres":
            _postgres_pool(self.url).putconn(connection)
        else:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        connection = self.connect()
        try:
            yield Transaction(connection, self.dialect)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)

    def one(self, query: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.transaction() as tx:
            return tx.one(query, params)

    def rows(self, query: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.rows(query, params)

    def scalar(self, query: str, params: Sequence[Any] = ()) -> Any:
        with self.transaction() as tx:
            return tx.scalar(query, params)

    def _migration_files(self) -> list[Path]:
        """Ordered migrations for this dialect.

        A bare ``NNNN_name.sql`` runs on both engines. A dialect-tagged
        ``NNNN_name.postgres.sql`` / ``NNNN_name.sqlite.sql`` runs only on the
        matching engine, letting pgvector/GIN DDL live beside portable SQL while
        keeping one forward-only version sequence.
        """
        chosen: dict[str, Path] = {}
        for path in MIGRATIONS.glob("*.sql"):
            parts = path.name[: -len(".sql")].split(".")
            version = parts[0]
            tag = parts[1] if len(parts) > 1 else ""
            if tag and tag != self.dialect:
                continue
            chosen[version] = path
        return [chosen[version] for version in sorted(chosen)]

    def migrate(self) -> list[str]:
        applied: list[str] = []
        if self.dialect == "sqlite":
            connection = self.connect()
            try:
                connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                                   "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
                done = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
                for path in self._migration_files():
                    version = path.name.split(".")[0]
                    if version in done:
                        continue
                    connection.executescript(path.read_text(encoding="utf-8"))
                    connection.execute("INSERT INTO schema_migrations VALUES (?,datetime('now'))",
                                       (version,))
                    applied.append(version)
                connection.commit()
            finally:
                connection.close()
            return applied

        connection = self.connect()
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                               "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
            for path in self._migration_files():
                version = path.name.split(".")[0]
                if version in done:
                    continue
                connection.execute(path.read_text(encoding="utf-8"))
                connection.execute("INSERT INTO schema_migrations VALUES (%s,%s)",
                                   (version, utcnow()))
                applied.append(version)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection)
        return applied


def utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_database: Database | None = None


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database.from_env()
    return _database


def set_database(database: Database | None) -> None:
    global _database
    _database = database

