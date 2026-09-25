"""Alembic environment configuration for Knowledge Base database migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

# Access Alembic Config object when running inside Alembic runner
try:
    config = context.config
    if config is not None and config.config_file_name is not None:
        fileConfig(config.config_file_name)
except AttributeError:
    config = None  # type: ignore[assignment]

target_metadata = None


def get_database_url() -> str:
    """Retrieve the Knowledge database URL from environment or discrete settings.

    Never commits or hardcodes credentials.
    """
    url = os.getenv("KNOWLEDGE_DATABASE_URL")
    if not url:
        host = os.getenv("KNOWLEDGE_DATABASE_HOST")
        name = os.getenv("KNOWLEDGE_DATABASE_NAME")
        user = os.getenv("KNOWLEDGE_DATABASE_USER")
        if host and name and user:
            password = os.getenv("KNOWLEDGE_DATABASE_PASSWORD", "")
            port = os.getenv("KNOWLEDGE_DATABASE_PORT", "5432")
            auth = (
                f"{quote_plus(user)}:{quote_plus(password)}@"
                if password
                else f"{quote_plus(user)}@"
            )
            port_str = f":{port}" if port else ""
            return f"postgresql+asyncpg://{auth}{host}{port_str}/{name}"

        raise RuntimeError(
            "KNOWLEDGE_DATABASE_URL environment variable is not set. "
            "Migration execution requires a valid connection string to 'superoffice_ai_knowledge'."
        )
    # Ensure asyncpg driver is specified for async SQLAlchemy engine
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations synchronously on an existing connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    configuration = (config.get_section(config.config_ini_section) if config else {}) or {}
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if __name__ != "__main__" and config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
