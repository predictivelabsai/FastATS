from database import Database


def test_migrations_are_idempotent(tmp_path):
    db = Database(path=str(tmp_path / "db.sqlite"))
    # Postgres-only migrations (e.g. 0003_semantic) are skipped on SQLite.
    applied = db.migrate()
    assert applied[0] == "0001_core"
    assert "0002_platform" in applied
    assert "0003_semantic" not in applied
    assert db.migrate() == []
    assert db.scalar("SELECT COUNT(*) FROM schema_migrations") == len(applied)


def test_schema_identifier_is_validated(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        Database(path=str(tmp_path / "db.sqlite"), schema="fast_ats;drop schema public")

