from pathlib import Path

import pytest

from ecommerce_cs_agent.db import migrations


def write_migration(path: Path, name: str, sql: str) -> Path:
    file_path = path / name
    file_path.write_text(sql, encoding="utf-8")
    return file_path


def test_dry_run_plans_pending_migrations_without_applying(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")

    records: dict[str, str] = {}
    plan = migrations.plan_migrations(tmp_path, records)

    assert [item.version for item in plan] == ["001"]
    assert plan[0].status == "pending"
    assert records == {}


def test_cli_dry_run_uses_local_plan_without_postgres_driver(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")

    exit_code = migrations.main(
        [
            "--database-url",
            "postgresql://example.local/cs_agent",
            "--migrations-dir",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "001 pending 001_initial.sql" in capsys.readouterr().out


def test_apply_migrations_is_idempotent_for_matching_checksums(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")
    connection = migrations.InMemoryMigrationConnection()

    first = migrations.apply_migrations(tmp_path, connection)
    second = migrations.apply_migrations(tmp_path, connection)

    assert [item.version for item in first] == ["001"]
    assert first[0].status == "applied"
    assert second[0].status == "skipped"
    assert connection.record_count("001") == 1
    assert connection.executed_sql_count == 1


def test_checksum_mismatch_stops_before_running_sql(tmp_path: Path) -> None:
    file_path = write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")
    connection = migrations.InMemoryMigrationConnection()
    migrations.apply_migrations(tmp_path, connection)
    file_path.write_text("create table changed(id uuid primary key);", encoding="utf-8")

    with pytest.raises(migrations.ChecksumMismatchError, match="001"):
        migrations.apply_migrations(tmp_path, connection)

    assert connection.executed_sql_count == 1


def test_initial_migration_contains_required_extensions_tables_and_constraints() -> None:
    sql = Path("migrations/001_initial.sql").read_text(encoding="utf-8").lower()

    required_snippets = [
        "create table if not exists schema_migration",
        "create extension if not exists pgcrypto",
        "create extension if not exists vector",
        "organization",
        "store",
        "platform_account",
        "external_api_token",
        "admin_user",
        "admin_session",
        "system_admin_user",
        "system_admin_session",
        "conversation",
        "message",
        "decision_record",
        "decision_trace_step",
        "context_snapshot",
        "decision_graph_checkpoint",
        "action_request",
        "action_result",
        "human_reply",
        "product",
        "product_asset",
        "product_asset_markdown",
        "product_knowledge_candidate",
        "product_price_snapshot",
        "admin_audit_log",
        "system_admin_audit_log",
        "unique (organization_id, request_id)",
        "unique (organization_id, store_id, platform, external_message_id)",
        "unique (decision_id, context_request_id)",
        "unique (decision_id, action_id)",
        "unique (action_request_id, idempotency_key)",
    ]

    for snippet in required_snippets:
        assert snippet in sql
