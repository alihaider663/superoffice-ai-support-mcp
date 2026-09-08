"""Unit tests for Knowledge Alembic migration infrastructure and invariants."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_migration_files_exist() -> None:
    """Verify essential migration files exist at expected repository paths."""
    base_dir = Path(__file__).resolve().parents[3] / "src" / "servers" / "knowledge"
    alembic_ini = base_dir / "alembic.ini"
    env_py = base_dir / "migrations" / "env.py"
    script_mako = base_dir / "migrations" / "script.py.mako"
    rev_file = base_dir / "migrations" / "versions" / "0001_knowledge_schema.py"

    assert alembic_ini.is_file(), f"Missing {alembic_ini}"
    assert env_py.is_file(), f"Missing {env_py}"
    assert script_mako.is_file(), f"Missing {script_mako}"
    assert rev_file.is_file(), f"Missing {rev_file}"


@pytest.mark.unit
def test_alembic_ini_contains_no_secrets() -> None:
    """Ensure alembic.ini contains no plaintext database credentials or passwords."""
    base_dir = Path(__file__).resolve().parents[3] / "src" / "servers" / "knowledge"
    alembic_ini = base_dir / "alembic.ini"
    content = alembic_ini.read_text(encoding="utf-8")

    assert "sqlalchemy.url" not in content
    assert "password" not in content.lower()
    assert "postgres:" not in content


@pytest.mark.unit
def test_env_database_url_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_database_url handles missing env var and driver normalization."""
    base_dir = Path(__file__).resolve().parents[3] / "src" / "servers" / "knowledge"
    env_path = base_dir / "migrations" / "env.py"

    spec = importlib.util.spec_from_file_location("knowledge_env", env_path)
    assert spec is not None
    assert spec.loader is not None
    env_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env_module)

    # 1. Missing env var raises RuntimeError
    monkeypatch.delenv("KNOWLEDGE_DATABASE_URL", raising=False)
    with pytest.raises(
        RuntimeError, match="KNOWLEDGE_DATABASE_URL environment variable is not set"
    ):
        env_module.get_database_url()

    # 2. postgresql:// is normalized to postgresql+asyncpg://
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    assert env_module.get_database_url() == "postgresql+asyncpg://user:pass@localhost:5432/testdb"

    # 3. postgres:// is normalized to postgresql+asyncpg://
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "postgres://user:pass@localhost:5432/testdb")
    assert env_module.get_database_url() == "postgresql+asyncpg://user:pass@localhost:5432/testdb"

    # 4. postgresql+asyncpg:// is preserved
    monkeypatch.setenv(
        "KNOWLEDGE_DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    )
    assert env_module.get_database_url() == "postgresql+asyncpg://user:pass@localhost:5432/testdb"


@pytest.mark.unit
def test_migration_revision_invariants() -> None:
    """Verify revision 0001_knowledge_schema metadata and extension preflight."""
    base_dir = Path(__file__).resolve().parents[3] / "src" / "servers" / "knowledge"
    rev_path = base_dir / "migrations" / "versions" / "0001_knowledge_schema.py"

    spec = importlib.util.spec_from_file_location("rev_0001", rev_path)
    assert spec is not None
    assert spec.loader is not None
    rev_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rev_module)

    assert rev_module.revision == "0001_knowledge_schema"
    assert rev_module.down_revision is None
    assert rev_module.branch_labels is None
    assert rev_module.depends_on is None

    mock_conn = MagicMock()

    # Case A: both extensions present and valid
    mock_conn.execute.return_value.fetchall.return_value = [
        ("vector", "0.8.6"),
        ("pg_trgm", "1.6"),
    ]
    rev_module.preflight_extensions(mock_conn)

    # Case B: vector missing
    mock_conn.execute.return_value.fetchall.return_value = [
        ("pg_trgm", "1.6"),
    ]
    with pytest.raises(RuntimeError, match="Prerequisite extension 'vector'"):
        rev_module.preflight_extensions(mock_conn)

    # Case C: vector wrong version
    mock_conn.execute.return_value.fetchall.return_value = [
        ("vector", "0.7.0"),
        ("pg_trgm", "1.6"),
    ]
    with pytest.raises(RuntimeError, match="Prerequisite extension 'vector'"):
        rev_module.preflight_extensions(mock_conn)

    # Case D: pg_trgm missing
    mock_conn.execute.return_value.fetchall.return_value = [
        ("vector", "0.8.6"),
    ]
    with pytest.raises(RuntimeError, match="Prerequisite extension 'pg_trgm'"):
        rev_module.preflight_extensions(mock_conn)


@pytest.mark.unit
def test_migration_schema_invariants() -> None:
    """Inspect migration source code to verify structural DDL invariants."""
    base_dir = Path(__file__).resolve().parents[3] / "src" / "servers" / "knowledge"
    rev_path = base_dir / "migrations" / "versions" / "0001_knowledge_schema.py"
    content = rev_path.read_text(encoding="utf-8")

    # Invariants for schema and tables
    assert "CREATE SCHEMA IF NOT EXISTS knowledge;" in content
    assert '"documents"' in content
    assert '"chunks"' in content
    assert '"runbooks"' in content
    assert '"known_issues"' in content

    # Vector dimensions and index invariants
    assert "Vector(384)" in content
    assert "CREATE INDEX idx_chunks_embedding_hnsw" in content
    assert "vector_cosine_ops" in content
    assert "m = 16, ef_construction = 64" in content

    # Trigram index invariant
    assert "CREATE INDEX idx_known_issues_title_trgm" in content
    assert "gin_trgm_ops" in content

    # Foreign key cascade invariant
    assert 'ondelete="CASCADE"' in content
    assert '"uq_chunks_document_chunk_index"' in content
