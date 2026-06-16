from __future__ import annotations

import os
from pathlib import Path

import psycopg


DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def load_migration_sql(name: str, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> str:
    path = migrations_dir / name
    return path.read_text(encoding="utf-8")


def apply_migrations(
    *,
    database_url: str | None = None,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    dsn = database_url or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required to run migrations")

    applied: list[str] = []
    migration_paths = sorted(migrations_dir.glob("*.sql"))
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migration (
                  version text PRIMARY KEY,
                  applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            for migration_path in migration_paths:
                version = migration_path.name
                cursor.execute(
                    "SELECT 1 FROM schema_migration WHERE version = %s",
                    (version,),
                )
                if cursor.fetchone():
                    continue
                cursor.execute(migration_path.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migration (version) VALUES (%s)",
                    (version,),
                )
                applied.append(version)
        connection.commit()
    return applied
