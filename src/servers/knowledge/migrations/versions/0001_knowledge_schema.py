"""create knowledge schema

Revision ID: 0001_knowledge_schema
Revises: None
Create Date: 2026-09-08 11:00:00.000000

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_knowledge_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def preflight_extensions(connection: sa.engine.Connection) -> None:
    """Verify required PostgreSQL extensions are active in the target database."""
    result = connection.execute(
        sa.text(
            "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');"
        )
    )
    installed = {row[0]: row[1] for row in result.fetchall()}

    if "vector" not in installed or installed["vector"] != "0.8.6":
        found = installed.get("vector", "none")
        raise RuntimeError(
            f"Prerequisite extension 'vector' (version 0.8.6) is not activated in database. "
            f"Found: {found}. Run Gate 7D.3B2A bootstrap before running migrations."
        )

    if "pg_trgm" not in installed or not installed["pg_trgm"]:
        raise RuntimeError(
            "Prerequisite extension 'pg_trgm' is not activated in database. "
            "Run Gate 7D.3B2A bootstrap before running migrations."
        )


def upgrade() -> None:
    # 1. Preflight required extensions
    connection = op.get_bind()
    preflight_extensions(connection)

    # 2. Create schema 'knowledge'
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge;")

    # 3. Create table 'knowledge.documents'
    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("source_reference", sa.String(length=128), nullable=False),
        sa.Column("canonical_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_documents"),
        schema="knowledge",
    )
    op.create_index(
        "idx_documents_type",
        "documents",
        ["document_type"],
        schema="knowledge",
    )
    op.create_index(
        "idx_documents_source_ref",
        "documents",
        ["source_reference"],
        schema="knowledge",
    )

    # 4. Create table 'knowledge.chunks'
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.PrimaryKeyConstraint("chunk_id", name="pk_chunks"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge.documents.document_id"],
            name="fk_chunks_document_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
        schema="knowledge",
    )
    op.create_index(
        "idx_chunks_document_id",
        "chunks",
        ["document_id"],
        schema="knowledge",
    )
    # HNSW vector index with vector_cosine_ops, m = 16, ef_construction = 64
    op.execute(
        """
        CREATE INDEX idx_chunks_embedding_hnsw
        ON knowledge.chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )

    # 5. Create table 'knowledge.runbooks'
    op.create_table(
        "runbooks",
        sa.Column("runbook_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("problem_description", sa.Text(), nullable=False),
        sa.Column(
            "diagnostic_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "remediation_steps",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("product", sa.String(length=100), nullable=True),
        sa.Column("verified_version", sa.String(length=50), nullable=True),
        sa.Column("last_reviewed", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source_reference", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("runbook_id", name="pk_runbooks"),
        schema="knowledge",
    )
    op.create_index(
        "idx_runbooks_product",
        "runbooks",
        ["product"],
        schema="knowledge",
    )

    # 6. Create table 'knowledge.known_issues'
    op.create_table(
        "known_issues",
        sa.Column("issue_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("symptom_summary", sa.Text(), nullable=False),
        sa.Column("root_cause_summary", sa.Text(), nullable=False),
        sa.Column("workaround", sa.Text(), nullable=True),
        sa.Column("permanent_fix_reference", sa.String(length=128), nullable=True),
        sa.Column(
            "affected_products",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "affected_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.String(length=50),
            server_default=sa.text("'general'"),
            nullable=False,
        ),
        sa.Column("source_reference", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("issue_id", name="pk_known_issues"),
        schema="knowledge",
    )
    op.create_index(
        "idx_known_issues_category",
        "known_issues",
        ["category"],
        schema="knowledge",
    )
    # Trigram index on title using gin_trgm_ops
    op.execute(
        """
        CREATE INDEX idx_known_issues_title_trgm
        ON knowledge.known_issues
        USING gin (title gin_trgm_ops);
        """
    )


def downgrade() -> None:
    # Drop known_issues (and its indexes)
    op.execute("DROP INDEX IF EXISTS knowledge.idx_known_issues_title_trgm;")
    op.drop_index(
        "idx_known_issues_category",
        table_name="known_issues",
        schema="knowledge",
    )
    op.drop_table("known_issues", schema="knowledge")

    # Drop runbooks (and its index)
    op.drop_index(
        "idx_runbooks_product",
        table_name="runbooks",
        schema="knowledge",
    )
    op.drop_table("runbooks", schema="knowledge")

    # Drop chunks (and its indexes)
    op.execute("DROP INDEX IF EXISTS knowledge.idx_chunks_embedding_hnsw;")
    op.drop_index(
        "idx_chunks_document_id",
        table_name="chunks",
        schema="knowledge",
    )
    op.drop_table("chunks", schema="knowledge")

    # Drop documents (and its indexes)
    op.drop_index(
        "idx_documents_source_ref",
        table_name="documents",
        schema="knowledge",
    )
    op.drop_index(
        "idx_documents_type",
        table_name="documents",
        schema="knowledge",
    )
    op.drop_table("documents", schema="knowledge")

    # Drop schema 'knowledge'
    op.execute("DROP SCHEMA IF EXISTS knowledge CASCADE;")
