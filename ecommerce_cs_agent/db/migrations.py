from __future__ import annotations

import argparse
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class MigrationError(RuntimeError):
    """Base class for migration failures."""


class ChecksumMismatchError(MigrationError):
    """Raised when an already-applied migration file has changed."""


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationPlanItem:
    version: str
    name: str
    checksum: str
    status: str
    path: Path


class MigrationConnection(Protocol):
    def ensure_schema_migration(self) -> None:
        pass

    def get_applied_migrations(self) -> Mapping[str, str]:
        pass

    def execute_migration(self, migration: MigrationFile) -> None:
        pass

    def record_migration(self, migration: MigrationFile) -> None:
        pass


class InMemoryMigrationConnection:
    """Small test connection that exercises planning and idempotency logic."""

    def __init__(self) -> None:
        self._records: dict[str, str | None] = {}
        self._record_writes: dict[str, int] = {}
        self.executed_sql: list[str] = []

    @property
    def executed_sql_count(self) -> int:
        return len(self.executed_sql)

    def record_count(self, version: str) -> int:
        return self._record_writes.get(version, 0)

    def ensure_schema_migration(self) -> None:
        return None

    def get_applied_migrations(self) -> Mapping[str, str | None]:
        return dict(self._records)

    def execute_migration(self, migration: MigrationFile) -> None:
        self.executed_sql.append(migration.sql)

    def record_migration(self, migration: MigrationFile) -> None:
        if migration.version in self._records:
            return
        self._records[migration.version] = migration.checksum
        self._record_writes[migration.version] = self._record_writes.get(migration.version, 0) + 1


class PsycopgMigrationConnection:
    MAX_CONNECT_ATTEMPTS = 8

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._driver = None
        self._connect = None
        try:
            import psycopg

            self._driver = "psycopg"
            self._connect = psycopg.connect
        except ImportError:
            try:
                import psycopg2

                self._driver = "psycopg2"
                self._connect = psycopg2.connect
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL migration requires psycopg or psycopg2 to be installed."
                ) from exc

    def ensure_schema_migration(self) -> None:
        with self._connect_with_retry() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_MIGRATION_SQL)
                cur.execute("ALTER TABLE schema_migration ADD COLUMN IF NOT EXISTS checksum text")

    def get_applied_migrations(self) -> Mapping[str, str | None]:
        with self._connect_with_retry() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version, checksum FROM schema_migration")
                records = {row[0]: row[1] for row in cur.fetchall()}
                if any(checksum is None for checksum in records.values()):
                    records = normalize_legacy_records(records, self._core_schema_exists(cur))
                return records

    def _core_schema_exists(self, cur: object) -> bool:
        cur.execute(
            """
            SELECT to_regclass('public.organization') IS NOT NULL
               AND to_regclass('public.store') IS NOT NULL
               AND to_regclass('public.decision_record') IS NOT NULL
            """
        )
        row = cur.fetchone()
        return bool(row and row[0])

    def execute_migration(self, migration: MigrationFile) -> None:
        with self._connect_with_retry() as conn:
            with conn.cursor() as cur:
                cur.execute(migration.sql)

    def record_migration(self, migration: MigrationFile) -> None:
        with self._connect_with_retry() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO schema_migration (version, checksum)
                    VALUES (%s, %s)
                    ON CONFLICT (version) DO UPDATE
                    SET checksum = COALESCE(schema_migration.checksum, EXCLUDED.checksum)
                    """,
                    (migration.version, migration.checksum),
                )

    def _connect_with_retry(self) -> object:
        if self._connect is None:
            raise RuntimeError("PostgreSQL driver is not configured.")
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_CONNECT_ATTEMPTS + 1):
            try:
                return self._connect(self._database_url)
            except Exception as exc:  # pragma: no cover - driver-specific exception hierarchy.
                last_error = exc
                if attempt == self.MAX_CONNECT_ATTEMPTS:
                    break
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 5.0))
        assert last_error is not None
        raise last_error


SCHEMA_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version text PRIMARY KEY,
    checksum text,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


def load_migrations(migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR) -> list[MigrationFile]:
    directory = Path(migrations_dir)
    if not directory.exists():
        raise FileNotFoundError(f"Migration directory does not exist: {directory}")

    migrations: list[MigrationFile] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        sql = path.read_text(encoding="utf-8")
        version = path.name
        migrations.append(
            MigrationFile(
                version=version,
                name=path.name,
                path=path,
                sql=sql,
                checksum=checksum_sql(sql),
            )
        )
    return migrations


def checksum_sql(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def plan_migrations(
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    applied: Mapping[str, str | None] | None = None,
) -> list[MigrationPlanItem]:
    applied = applied or {}
    plan: list[MigrationPlanItem] = []
    for migration in load_migrations(migrations_dir):
        recorded_checksum = applied.get(migration.version)
        if migration.version not in applied:
            status = "pending"
        elif not recorded_checksum:
            status = "skipped"
        elif recorded_checksum == migration.checksum:
            status = "skipped"
        else:
            raise ChecksumMismatchError(
                f"Migration {migration.version} checksum mismatch; stop and inspect the file."
            )
        plan.append(
            MigrationPlanItem(
                version=migration.version,
                name=migration.name,
                checksum=migration.checksum,
                status=status,
                path=migration.path,
            )
        )
    return plan


def normalize_legacy_records(
    records: Mapping[str, str | None],
    core_schema_exists: bool,
) -> dict[str, str | None]:
    if core_schema_exists:
        return dict(records)
    return {
        version: checksum
        for version, checksum in records.items()
        if checksum is not None
    }


def apply_migrations(
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    connection: MigrationConnection | None = None,
) -> list[MigrationPlanItem]:
    if connection is None:
        raise RuntimeError("A migration connection is required for applying migrations.")

    connection.ensure_schema_migration()
    applied = connection.get_applied_migrations()
    migrations_by_version = {migration.version: migration for migration in load_migrations(migrations_dir)}
    planned = plan_migrations(migrations_dir, applied)
    results: list[MigrationPlanItem] = []

    for item in planned:
        if item.status == "skipped":
            results.append(item)
            continue
        migration = migrations_by_version[item.version]
        connection.execute_migration(migration)
        connection.record_migration(migration)
        results.append(
            MigrationPlanItem(
                version=item.version,
                name=item.name,
                checksum=item.checksum,
                status="applied",
                path=item.path,
            )
        )
    return results


def _print_plan(items: list[MigrationPlanItem]) -> None:
    for item in items:
        print(f"{item.version} {item.status} {item.name} {item.checksum}")


def connection_from_environment(database_url: str | None = None) -> PsycopgMigrationConnection:
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for applying migrations.")
    return PsycopgMigrationConnection(database_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ecommerce_cs_agent database migrations.")
    parser.add_argument("command", nargs="?", choices=["up"], default="up")
    parser.add_argument("--database-url")
    parser.add_argument("--migrations-dir", default=str(DEFAULT_MIGRATIONS_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        _print_plan(plan_migrations(args.migrations_dir, {}))
        return 0

    _print_plan(
        apply_migrations(
            args.migrations_dir,
            connection_from_environment(args.database_url),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
