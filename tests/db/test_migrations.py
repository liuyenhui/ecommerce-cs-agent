import re
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


def test_db_cli_migrate_dry_run_accepts_database_url_and_migrations_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from ecommerce_cs_agent.db import cli

    write_migration(tmp_path, "001_initial.sql", "create table example(id uuid primary key);")

    exit_code = cli.main(
        [
            "migrate",
            "--database-url",
            "postgresql://example.local/cs_agent",
            "--migrations-dir",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert '"version": "001_initial.sql"' in capsys.readouterr().out


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


def test_decision_idempotency_scope_migration_replaces_organization_only_uniqueness() -> None:
    sql = Path("migrations/011_decision_idempotency_store_scope.sql").read_text(encoding="utf-8").lower()

    assert "drop constraint if exists decision_record_organization_id_request_id_key" in sql
    assert "drop index if exists idx_decision_record_organization_request_id" in sql
    assert "create unique index if not exists idx_decision_record_organization_store_request_id" in sql
    assert "on decision_record (organization_id, store_id, request_id)" in sql


def test_llm_governance_migration_contains_versioned_secure_tables() -> None:
    sql = Path("migrations/012_system_admin_llm_governance.sql").read_text(encoding="utf-8").lower()
    compact_sql = " ".join(sql.split())

    def section(start: str, end: str | None = None) -> str:
        scoped_sql = compact_sql.split(start, maxsplit=1)[1]
        return scoped_sql if end is None else scoped_sql.split(end, maxsplit=1)[0]

    provider_sql = section(
        "create table if not exists llm_provider_config",
        "create table if not exists llm_config_version",
    )
    version_sql = section(
        "create table if not exists llm_config_version",
        "create table if not exists llm_scenario_route",
    )
    route_sql = section(
        "create table if not exists llm_scenario_route",
        "create table if not exists llm_connection_test",
    )
    connection_test_sql = section(
        "create table if not exists llm_connection_test",
        "create table if not exists llm_invocation_metric",
    )
    release_sql = section(
        "create table if not exists llm_release_record",
        "create table if not exists llm_scenario_route",
    )
    invocation_sql = section("create table if not exists llm_invocation_metric")
    eval_sql = section(
        "create table if not exists llm_eval_run",
        "create table if not exists llm_release_record",
    )

    required_by_section = [
        (provider_sql, [
            "secret_namespace text not null",
            "secret_name text not null",
            "secret_key text not null",
            "check ((enabled and status <> 'disabled') or (not enabled and status = 'disabled'))",
        ]),
        (version_sql, [
            "organization_id uuid not null references organization(id) on delete restrict",
            "unique (organization_id, version_number)",
            "check (status in ('draft', 'validated', 'pending_publish', 'running', 'superseded', 'rolled_back'))",
            "revision integer not null default 1 check (revision > 0)",
            "created_by_system_admin_user_id uuid not null references system_admin_user(id) on delete restrict",
            "created_at timestamptz not null default now()",
            "published_by_system_admin_user_id uuid references system_admin_user(id) on delete restrict",
            "published_at timestamptz",
            "rollback_of_version_id uuid references llm_config_version(id) on delete restrict",
            "status in ('draft', 'validated', 'pending_publish') and published_at is null and published_by_system_admin_user_id is null",
            "status in ('running', 'superseded', 'rolled_back') and published_at is not null and published_by_system_admin_user_id is not null",
            "rollback_of_version_id is null or rollback_of_version_id <> id",
            "create unique index if not exists idx_llm_config_version_one_running on llm_config_version (organization_id) where status = 'running'",
        ]),
        (route_sql, [
            "unique (config_version_id, scenario)",
            "check (temperature >= 0 and temperature <= 2)",
            "max_output_tokens integer not null default 1024 check (max_output_tokens > 0)",
            "timeout_seconds integer not null default 30 check (timeout_seconds > 0)",
            "max_retries integer not null default 1 check (max_retries >= 0)",
            "circuit_breaker_threshold integer not null default 5 check (circuit_breaker_threshold > 0)",
            "recovery_probe_seconds integer not null default 60 check (recovery_probe_seconds > 0)",
            "create index if not exists idx_llm_scenario_route_primary_provider_model on llm_scenario_route (primary_provider_config_id, primary_model)",
            "create index if not exists idx_llm_scenario_route_scenario on llm_scenario_route (scenario, config_version_id)",
        ]),
        (connection_test_sql, [
            "provider_config_id uuid not null references llm_provider_config(id) on delete restrict",
            "config_version_id uuid references llm_config_version(id) on delete restrict",
            "provider_revision integer not null",
            "checked_by_system_admin_user_id uuid not null references system_admin_user(id) on delete restrict",
            "status text not null check (status in ('passed', 'failed'))",
            "latency_ms integer check (latency_ms is null or latency_ms >= 0)",
            "checked_at timestamptz not null default now()",
            "error_code text",
            "redacted_error_message text",
            "create index if not exists idx_llm_connection_test_version_checked on llm_connection_test (config_version_id, checked_at desc)",
        ]),
        (release_sql, [
            "evaluation_run_id varchar(128) not null",
            "evaluation_config_version_id uuid not null",
            "length(evaluation_run_id) <= 128",
            "evaluation_run_id ~ '[^[:space:]]'",
            "unique (config_version_id)",
            "foreign key (config_version_id, organization_id)",
            "foreign key (evaluation_run_id, organization_id, evaluation_config_version_id)",
            "check (status in ('pending', 'running', 'superseded', 'rolled_back'))",
            "rollback_of_release_id is null and rollback_of_version_id is null",
            "rollback_of_release_id is not null and rollback_of_version_id is not null",
            "create unique index if not exists idx_llm_release_record_one_running",
        ]),
        (eval_sql, [
            "id varchar(128) primary key",
            "config_revision integer not null check (config_revision > 0)",
            "configuration_hash char(64) not null",
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            "foreign key (config_version_id, organization_id)",
            "red_line_failures integer not null default 0 check (red_line_failures >= 0)",
            "gate_status <> 'passed' or (status = 'completed' and red_line_failures = 0)",
            "report_ref text check",
            "completed_at is null or completed_at >= created_at",
        ]),
        (invocation_sql, [
            "scenario_route_id uuid not null references llm_scenario_route(id) on delete restrict",
            "route_role text not null check (route_role in ('primary', 'fallback'))",
            "organization_id uuid not null references organization(id) on delete restrict",
            "input_tokens integer not null default 0 check (input_tokens >= 0)",
            "output_tokens integer not null default 0 check (output_tokens >= 0)",
            "latency_ms integer not null check (latency_ms >= 0)",
            "status text not null check (status in ('succeeded', 'failed', 'timed_out', 'rejected'))",
            "error_code text",
            "estimated_cost_micros bigint not null default 0 check (estimated_cost_micros >= 0)",
            "currency char(3) not null default 'usd' check (currency in ('cny', 'usd'))",
            "create index if not exists idx_llm_invocation_metric_route_occurred on llm_invocation_metric (scenario_route_id, occurred_at desc)",
            "create index if not exists idx_llm_invocation_metric_organization_store_occurred on llm_invocation_metric (organization_id, store_id, occurred_at desc)",
            "create index if not exists idx_llm_invocation_metric_store_occurred on llm_invocation_metric (store_id, occurred_at desc)",
            "create index if not exists idx_llm_invocation_metric_occurred on llm_invocation_metric (occurred_at desc)",
            "conrelid = 'llm_invocation_metric'::regclass",
            "create or replace function validate_llm_invocation_metric_route_role()",
            "new.route_role = 'fallback'",
            "join llm_config_version as route_version",
            "route_version.status = 'running'",
            "route_version.organization_id = new.organization_id",
            "route.fallback_provider_config_id is not null",
            "route.fallback_model is not null",
            "create trigger trg_validate_llm_invocation_metric_route_role",
            "before insert on llm_invocation_metric",
            "create or replace function protect_llm_invocation_metric_history()",
            "invocation metrics are append-only",
            "create trigger trg_protect_llm_invocation_metric_history",
            "before update or delete on llm_invocation_metric",
            "create or replace function protect_llm_scenario_route_history()",
            "metric.scenario_route_id = old.id",
            "route_version.status = 'draft'",
            "route_version.status <> 'draft'",
            "create trigger trg_protect_llm_scenario_route_history",
            "before insert or update or delete on llm_scenario_route",
            "create or replace function validate_llm_config_version_transition()",
            "create or replace function lock_llm_config_versions",
            "version rows in uuid order, then version advisory locks",
            "order by route_version.id::text for key share",
            "perform lock_llm_config_versions",
            "new.id is distinct from old.id",
            "rollback_target.organization_id = new.organization_id",
            "rollback_target.status in ('superseded', 'rolled_back')",
            "for key share",
            "old.status = 'draft' and new.status = 'validated'",
            "old.status = 'validated' and new.status = 'pending_publish'",
            "old.status = 'pending_publish' and new.status = 'running'",
            "old.status = 'running' and new.status in ('superseded', 'rolled_back')",
            "new.status = old.status and old.status in ('draft', 'validated', 'pending_publish')",
            "new.revision <> old.revision + 1",
            "new.status <> 'draft' or new.revision <> 1",
            "if tg_op = 'delete'",
            "old.status <> 'draft'",
            "old.status = 'draft' and new.status = 'draft'",
            "new.configuration_hash is distinct from old.configuration_hash",
            "new.description is distinct from old.description",
            "new.created_by_system_admin_user_id is distinct from old.created_by_system_admin_user_id",
            "new.created_at is distinct from old.created_at",
            "config version creation metadata is immutable",
            "new.rollback_of_version_id is distinct from old.rollback_of_version_id",
            "old.status = 'pending_publish' and new.status = 'running'",
            "new.published_by_system_admin_user_id is null or new.published_at is null",
            "new.published_by_system_admin_user_id is distinct from old.published_by_system_admin_user_id",
            "new.published_at is distinct from old.published_at",
            "create trigger trg_validate_llm_config_version_transition",
            "before insert or update or delete on llm_config_version",
        ]),
    ]
    for scoped_sql, required_snippets in required_by_section:
        for snippet in required_snippets:
            assert snippet in scoped_sql

    assert invocation_sql.count("perform lock_llm_config_versions") >= 3
    assert "create or replace function protect_llm_release_record_history()" in compact_sql
    assert "create or replace function protect_llm_eval_run_history()" in compact_sql
    assert "evaluation run history is immutable" in compact_sql
    assert "evaluation runs require a validated config version snapshot" in compact_sql
    assert "new.config_revision <> version_revision" in compact_sql
    assert "new.configuration_hash is distinct from version_configuration_hash" in compact_sql
    assert "new.config_revision is distinct from old.config_revision" in compact_sql
    assert "new.configuration_hash is distinct from old.configuration_hash" in compact_sql
    assert "new.evaluation_config_version_id is distinct from old.evaluation_config_version_id" in compact_sql
    assert "new.evaluation_config_version_id <> new.config_version_id" in compact_sql
    assert "new.evaluation_config_version_id <> new.rollback_of_version_id" in compact_sql
    assert "release records require a completed passing evaluation snapshot" in compact_sql
    assert "terminal release records are immutable" in compact_sql
    assert "source.config_version_id = new.rollback_of_version_id" in compact_sql
    assert "source.status in ('superseded', 'rolled_back')" in compact_sql
    assert "for key share of source, source_version" not in compact_sql
    assert "target_version.rollback_of_version_id is not distinct from new.rollback_of_version_id" in compact_sql
    assert "perform lock_llm_config_versions(new.config_version_id)" in compact_sql
    assert "perform lock_llm_config_versions(old.config_version_id)" in compact_sql
    assert "create or replace function validate_llm_release_version_consistency()" in compact_sql
    assert "draft and validated config versions must not have release records" in compact_sql
    assert "pending_publish config versions require exactly one pending release record" in compact_sql
    assert "terminal config version and release record statuses must match" in compact_sql
    assert "create constraint trigger trg_llm_release_version_consistency" in compact_sql
    assert "deferrable initially deferred" in compact_sql
    assert compact_sql.count("create constraint trigger trg_llm_release_version_consistency") == 2
    assert "create or replace function protect_llm_connection_test_history()" in compact_sql
    assert "new.provider_revision <> provider_revision_snapshot" in compact_sql
    assert "connection test history is immutable" in compact_sql
    assert "create trigger trg_protect_llm_connection_test_history" in compact_sql
    assert "before insert or update or delete on llm_connection_test" in compact_sql
    assert "create or replace function protect_llm_provider_endpoint()" in compact_sql
    assert "provider endpoint and secret reference are immutable" in compact_sql
    provider_history_sql = compact_sql.split(
        "create or replace function protect_llm_provider_endpoint()",
        maxsplit=1,
    )[1]
    assert "new.id is distinct from old.id" in provider_history_sql
    assert "new.created_at is distinct from old.created_at" in provider_history_sql
    assert "provider identity and creation metadata are immutable" in provider_history_sql

    postgres_test_source = Path("tests/db/test_migrations_postgres.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("TEST_DATABASE_URL")' in postgres_test_source
    assert 'os.environ.get("DATABASE_URL")' not in postgres_test_source
    assert "set TEST_DATABASE_URL to run PostgreSQL migration integration tests" in postgres_test_source

    for redundant_attribution_column in [
        "provider_config_id uuid",
        "config_version_id uuid",
        "model text",
        "scenario text",
        "estimated_cost_minor",
    ]:
        assert redundant_attribution_column not in invocation_sql

    column_names = {
        match.group(1)
        for line in sql.splitlines()
        if (match := re.match(
            r"\s*([a-z_][a-z0-9_]*)\s+(?:uuid|text|varchar|jsonb|bytea|boolean|integer|bigint|numeric|timestamptz|char)\b",
            line,
        ))
    }
    forbidden_column_patterns = [
        r"(^|_)secret_value($|_)",
        r"(^|_)prompt($|_)",
        r"(^|_)customer_message($|_)",
        r"(^|_)model_(?:response|output)($|_)",
        r"^(?:request|response)$",
        r"(^|_)(?:request|response)_(?:body|payload|content|text|data|raw)($|_)",
        r"(^|_)raw_payload($|_)",
        r"^(?:content|body)$",
    ]
    for column_name in column_names:
        assert not any(re.search(pattern, column_name) for pattern in forbidden_column_patterns), column_name


def test_llm_governance_postgres_concurrency_tests_observe_real_lock_waits() -> None:
    postgres_test_sql = Path("tests/db/test_migrations_postgres.py").read_text(encoding="utf-8").lower()

    assert "application_name" in postgres_test_sql
    assert "def wait_for_backend_lock" in postgres_test_sql
    assert "from pg_stat_activity" in postgres_test_sql
    assert "wait_event_type = 'lock'" in postgres_test_sql
    assert postgres_test_sql.count("wait_for_backend_lock(") >= 3


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


def test_system_admin_ops_migration_contains_background_task_and_audit_indexes() -> None:
    sql = Path("migrations/006_system_admin_ops.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table system_admin_user add column if not exists roles",
        "set roles = array[role]",
        "alter table system_admin_audit_log add column if not exists idempotency_key",
        "idx_system_admin_audit_action_idempotency",
        "idx_store_id_organization_id",
        "create table if not exists background_task",
        "task_id text not null unique",
        "retryable boolean not null default true",
        "idx_background_task_idempotency_key",
        "fk_background_task_store_tenant",
        "idx_background_task_tenant_status_created",
        "idx_background_task_type_status_created",
        "idx_system_admin_audit_tenant_created",
        "idx_system_admin_audit_actor_created",
    ]:
        assert snippet in sql


def test_product_knowledge_storage_migration_contains_asset_metadata_indexes() -> None:
    sql = Path("migrations/007_product_knowledge_storage.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table product_asset add column if not exists object_hash",
        "alter table product_asset add column if not exists mime_type",
        "alter table product_asset add column if not exists size_bytes",
        "alter table product_asset add column if not exists storage_status",
        "idx_product_asset_storage_status_created",
        "idx_product_knowledge_candidate_review_status",
    ]:
        assert snippet in sql
    assert "idx_knowledge_embedding_entry_chunk" not in sql


def test_admin_auth_schema_repair_migration_contains_idempotent_admin_user_alignment() -> None:
    sql = Path("migrations/008_admin_auth_schema_repair.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table admin_user add column if not exists organization_id",
        "references organization(id)",
        "idx_admin_user_organization_email",
        "alter table admin_session add column if not exists organization_id",
        "alter table admin_session add column if not exists admin_user_id",
        "alter table system_admin_user add column if not exists roles",
        "set roles = array[role]",
    ]:
        assert snippet in sql


def test_admin_user_fcihome_account_sub_migration_is_customer_admin_only() -> None:
    sql = Path("migrations/010_admin_user_fcihome_account_sub.sql").read_text(encoding="utf-8").lower()

    for snippet in [
        "alter table admin_user add column if not exists fcihome_account_sub",
        "idx_admin_user_fcihome_account_sub",
        "where fcihome_account_sub is not null",
    ]:
        assert snippet in sql
    assert "system_admin_user" not in sql
    assert "agent_system_admin_session" not in sql


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
