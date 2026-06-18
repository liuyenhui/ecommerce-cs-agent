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

    assert [item.version for item in plan] == ["001_initial.sql"]
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
    assert "001_initial.sql pending 001_initial.sql" in capsys.readouterr().out


def test_apply_migrations_is_idempotent_for_matching_checksums(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")
    connection = migrations.InMemoryMigrationConnection()

    first = migrations.apply_migrations(tmp_path, connection)
    second = migrations.apply_migrations(tmp_path, connection)

    assert [item.version for item in first] == ["001_initial.sql"]
    assert first[0].status == "applied"
    assert second[0].status == "skipped"
    assert connection.record_count("001_initial.sql") == 1
    assert connection.executed_sql_count == 1


def test_checksum_mismatch_stops_before_running_sql(tmp_path: Path) -> None:
    file_path = write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")
    connection = migrations.InMemoryMigrationConnection()
    migrations.apply_migrations(tmp_path, connection)
    file_path.write_text("create table changed(id uuid primary key);", encoding="utf-8")

    with pytest.raises(migrations.ChecksumMismatchError, match="001_initial.sql"):
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


def test_legacy_schema_migration_record_with_missing_checksum_is_skipped(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")

    plan = migrations.plan_migrations(tmp_path, {"001_initial.sql": None})

    assert plan[0].status == "skipped"


def test_legacy_schema_record_without_core_tables_is_treated_as_pending(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")

    normalized = migrations.normalize_legacy_records({"001_initial.sql": None}, core_schema_exists=False)
    plan = migrations.plan_migrations(tmp_path, normalized)

    assert plan[0].status == "pending"


def test_legacy_schema_record_with_core_tables_remains_skipped(tmp_path: Path) -> None:
    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")

    normalized = migrations.normalize_legacy_records({"001_initial.sql": None}, core_schema_exists=True)
    plan = migrations.plan_migrations(tmp_path, normalized)

    assert plan[0].status == "skipped"


def test_runtime_alignment_migration_contains_v1_state_tables() -> None:
    sql = Path("migrations/002_v1_runtime_alignment.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table schema_migration add column if not exists checksum",
        "create table if not exists app_decision_state",
        "unique (organization_id, store_id, request_id)",
        "create table if not exists app_product",
        "create table if not exists app_knowledge_candidate",
        "create table if not exists app_audit_log",
    ]:
        assert snippet in sql


def test_canonical_runtime_alignment_migration_contains_external_mapping_and_indexes() -> None:
    sql = Path("migrations/003_canonical_runtime_alignment.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table organization add column if not exists external_organization_id",
        "idx_organization_external_organization_id",
        "idx_store_external_lookup",
        "alter table conversation add column if not exists organization_id",
        "idx_conversation_tenant_external",
        "alter table message add column if not exists organization_id",
        "idx_message_tenant_external",
        "alter table decision_record add column if not exists status",
        "alter table decision_record add column if not exists decision_type",
        "alter table decision_record add column if not exists message_id",
        "idx_decision_record_organization_request_id",
        "idx_decision_record_tenant_status_created",
        "idx_decision_trace_step_decision_step_order",
        "idx_decision_trace_step_decision_created",
        "idx_context_snapshot_decision_context_request",
        "idx_context_snapshot_decision_type",
        "alter table decision_graph_checkpoint add column if not exists checkpoint_key",
        "alter table decision_graph_checkpoint add column if not exists state",
        "idx_decision_graph_checkpoint_decision_key",
        "idx_action_request_decision_action",
        "idx_action_result_decision_action_idempotency",
        "idx_action_result_decision_action",
        "alter table human_reply add column if not exists decision_id",
        "idx_human_reply_decision_id",
        "alter table product add column if not exists public_product_id",
        "alter table product_knowledge_candidate add column if not exists public_candidate_id",
        "alter table product_asset add column if not exists public_asset_id",
        "alter table product_price_snapshot add column if not exists public_price_snapshot_id",
        "create table if not exists knowledge_entry",
        "alter table knowledge_entry add column if not exists organization_id",
        "alter table knowledge_entry add column if not exists content",
        "alter table knowledge_entry add column if not exists source_type",
        "alter table knowledge_entry add column if not exists status",
        "create table if not exists knowledge_embedding",
        "idx_knowledge_entry_store_status_created",
    ]:
        assert snippet in sql


def test_legacy_runtime_defaults_migration_contains_not_null_defaults() -> None:
    sql = Path("migrations/005_legacy_runtime_defaults.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table message add column if not exists sender_type",
        "alter table message alter column sender_type set default",
        "alter table decision_record add column if not exists action",
        "alter table decision_record alter column action set default",
        "alter table decision_graph_checkpoint add column if not exists thread_id",
        "alter table decision_graph_checkpoint alter column thread_id set default",
        "alter table human_reply add column if not exists human_reply",
        "alter table human_reply alter column human_reply set default",
    ]:
        assert snippet in sql


def test_admin_auth_runtime_migration_contains_membership_invitation_and_session_extensions() -> None:
    sql = Path("migrations/004_admin_auth_runtime.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "create table if not exists admin_membership",
        "create table if not exists admin_invitation",
        "alter table admin_session add column if not exists active_store_id",
        "alter table admin_session add column if not exists last_seen_at",
        "alter table admin_session add column if not exists request_metadata",
        "idx_admin_session_hash_active",
        "idx_admin_membership_user_org",
        "idx_admin_invitation_org_status_created",
    ]:
        assert snippet in sql


def test_psycopg_connection_retries_transient_connect_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = migrations.PsycopgMigrationConnection.__new__(migrations.PsycopgMigrationConnection)
    connection._database_url = "postgresql://example"
    connection._connect_attempts = 0
    connection.MAX_CONNECT_ATTEMPTS = 3

    def flaky_connect(_database_url: str) -> object:
        connection._connect_attempts += 1
        if connection._connect_attempts < 3:
            raise OSError("temporary connection reset")
        return object()

    connection._connect = flaky_connect
    monkeypatch.setattr(migrations.time, "sleep", lambda _seconds: None)

    assert connection._connect_with_retry() is not None
    assert connection._connect_attempts == 3
