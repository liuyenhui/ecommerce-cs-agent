import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from ecommerce_cs_agent.db.migrations import load_migrations


DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set TEST_DATABASE_URL or DATABASE_URL to run PostgreSQL migration integration tests",
)


def assert_integrity_error(cursor: psycopg.Cursor[object], statement: str, parameters: tuple[object, ...]) -> None:
    cursor.execute("SAVEPOINT expected_integrity_error")
    with pytest.raises(psycopg.IntegrityError):
        cursor.execute(statement, parameters)
    cursor.execute("ROLLBACK TO SAVEPOINT expected_integrity_error")
    cursor.execute("RELEASE SAVEPOINT expected_integrity_error")


def set_test_search_path(cursor: psycopg.Cursor[object], schema_name: str) -> None:
    cursor.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema_name)))
    cursor.execute("SET LOCAL lock_timeout = '5s'")
    cursor.execute("SET LOCAL statement_timeout = '8s'")


def wait_for_backend_lock(application_name: str, timeout_seconds: float = 3.0) -> tuple[int, str]:
    deadline = time.monotonic() + timeout_seconds
    with psycopg.connect(DATABASE_URL, autocommit=True) as observer_connection:
        with observer_connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    """
                    SELECT pid, wait_event
                    FROM pg_stat_activity
                    WHERE application_name = %s
                      AND state = 'active'
                      AND wait_event_type = 'Lock'
                    """,
                    (application_name,),
                )
                observed_lock = cursor.fetchone()
                if observed_lock is not None:
                    return observed_lock
                time.sleep(0.02)
    raise AssertionError(f"backend {application_name!r} did not enter a lock wait")


def execute_concurrent_statement(
    schema_name: str,
    statement: str,
    parameters: tuple[object, ...],
    application_name: str,
) -> str:
    connection = psycopg.connect(DATABASE_URL, application_name=application_name)
    try:
        with connection.cursor() as cursor:
            set_test_search_path(cursor, schema_name)
            cursor.execute(statement, parameters)
        connection.commit()
        return "committed"
    except psycopg.IntegrityError as exc:
        connection.rollback()
        return exc.sqlstate or "integrity_error"
    finally:
        connection.close()


def test_migrations_execute_in_isolated_schema_and_enforce_llm_governance_constraints() -> None:
    schema_name = f"migration_test_{uuid.uuid4().hex}"
    connection = psycopg.connect(DATABASE_URL)

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            cursor.execute(
                sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema_name))
            )
            for migration in load_migrations(Path("migrations")):
                cursor.execute(migration.sql)

            cursor.execute(
                """
                SELECT count(*)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = %s
                  AND relation.relname IN (
                      'llm_provider_config',
                      'llm_config_version',
                      'llm_release_record',
                      'llm_scenario_route',
                      'llm_connection_test',
                      'llm_invocation_metric'
                  )
                  AND relation.relkind = 'r'
                """,
                (schema_name,),
            )
            assert cursor.fetchone() == (6,)

            cursor.execute(
                """
                INSERT INTO system_admin_user (email, password_hash, display_name, role)
                VALUES ('migration-test@example.invalid', 'not-a-real-password-hash', 'Migration Test', 'super_admin')
                RETURNING id
                """
            )
            system_admin_user_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO system_admin_user (email, password_hash, display_name, role)
                VALUES ('migration-reviewer@example.invalid', 'not-a-real-password-hash', 'Migration Reviewer', 'release_admin')
                RETURNING id
                """
            )
            other_system_admin_user_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO organization (name) VALUES ('Migration Test Organization') RETURNING id
                """
            )
            organization_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO organization (name) VALUES ('Other Migration Test Organization') RETURNING id
                """
            )
            other_organization_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO store (organization_id, name, platform, external_store_id)
                VALUES (%s, 'Migration Test Store', 'test', 'migration-test-store')
                RETURNING id
                """,
                (organization_id,),
            )
            store_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO store (organization_id, name, platform, external_store_id)
                VALUES (%s, 'Other Migration Test Store', 'test', 'other-migration-test-store')
                RETURNING id
                """,
                (other_organization_id,),
            )
            other_store_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_provider_config (
                    name, provider_type, base_url, secret_namespace, secret_name, secret_key
                ) VALUES ('test-provider', 'openai-compatible', 'https://example.invalid', 'test', 'llm', 'api-key')
                RETURNING id
                """
            )
            provider_id = cursor.fetchone()[0]
            assert_integrity_error(
                cursor,
                "UPDATE llm_provider_config SET base_url='https://other.invalid', revision=revision+1 WHERE id=%s",
                (provider_id,),
            )
            assert_integrity_error(
                cursor,
                "UPDATE llm_provider_config SET name='missing-revision' WHERE id=%s",
                (provider_id,),
            )
            cursor.execute(
                "UPDATE llm_provider_config SET name='test-provider-renamed', revision=revision+1 WHERE id=%s RETURNING revision",
                (provider_id,),
            )
            assert cursor.fetchone() == (2,)
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 1, 'draft', 'test-hash', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            config_version_id = cursor.fetchone()[0]
            cursor.execute(
                """
                UPDATE llm_config_version
                SET configuration_hash = 'edited-draft-hash',
                    description = 'edited while draft',
                    revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            cursor.execute(
                """
                SELECT configuration_hash, description
                FROM llm_config_version
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert cursor.fetchone() == ("edited-draft-hash", "edited while draft")
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET created_by_system_admin_user_id = %s, revision = revision + 1
                WHERE id = %s
                """,
                (other_system_admin_user_id, config_version_id),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET created_at = created_at + interval '1 second', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 10, 'draft', 'metadata-rewrite-target', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            metadata_rewrite_target_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 11, 'draft', 'deletable-draft', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            deletable_draft_id = cursor.fetchone()[0]
            cursor.execute("DELETE FROM llm_config_version WHERE id = %s", (deletable_draft_id,))

            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id, rollback_of_version_id
                ) VALUES (%s, 29, 'draft', 'invalid-draft-rollback', %s, %s)
                """,
                (organization_id, system_admin_user_id, metadata_rewrite_target_id),
            )
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 20, 'draft', 'validated-target', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            validated_target_id = cursor.fetchone()[0]
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'validated', revision = revision + 1
                WHERE id = %s
                """,
                (validated_target_id,),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id, rollback_of_version_id
                ) VALUES (%s, 30, 'draft', 'invalid-validated-rollback', %s, %s)
                """,
                (organization_id, system_admin_user_id, validated_target_id),
            )
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 21, 'draft', 'pending-target', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            pending_target_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE llm_config_version SET status = 'validated', revision = revision + 1 WHERE id = %s",
                (pending_target_id,),
            )
            cursor.execute(
                "UPDATE llm_config_version SET status = 'pending_publish', revision = revision + 1 WHERE id = %s",
                (pending_target_id,),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id, rollback_of_version_id
                ) VALUES (%s, 31, 'draft', 'invalid-pending-rollback', %s, %s)
                """,
                (organization_id, system_admin_user_id, pending_target_id),
            )
            self_target_id = uuid.uuid4()
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    id, organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id, rollback_of_version_id
                ) VALUES (%s, %s, 32, 'draft', 'invalid-self-rollback', %s, %s)
                """,
                (self_target_id, organization_id, system_admin_user_id, self_target_id),
            )
            cursor.execute(
                """
                INSERT INTO llm_scenario_route (
                    config_version_id, scenario, primary_provider_config_id, primary_model
                ) VALUES (%s, 'reply', %s, 'test-model')
                RETURNING id
                """,
                (config_version_id, provider_id),
            )
            scenario_route_id = cursor.fetchone()[0]

            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, organization_id, store_id,
                    latency_ms, status, currency
                ) VALUES (%s, 'primary', %s, %s, 10, 'succeeded', 'USD')
                """,
                (scenario_route_id, organization_id, store_id),
            )
            cursor.execute(
                "UPDATE llm_scenario_route SET primary_model = 'edited-draft-model' WHERE id = %s",
                (scenario_route_id,),
            )
            cursor.execute(
                """
                INSERT INTO llm_scenario_route (
                    config_version_id, scenario, primary_provider_config_id, primary_model
                ) VALUES (%s, 'draft-delete', %s, 'test-model')
                RETURNING id
                """,
                (config_version_id, provider_id),
            )
            draft_delete_route_id = cursor.fetchone()[0]
            cursor.execute("DELETE FROM llm_scenario_route WHERE id = %s", (draft_delete_route_id,))

            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id,
                    published_by_system_admin_user_id, published_at
                ) VALUES (%s, 2, 'draft', 'invalid-published-draft', %s, %s, now())
                """,
                (organization_id, system_admin_user_id, system_admin_user_id),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id,
                    published_by_system_admin_user_id, published_at
                ) VALUES (%s, 3, 'running', 'invalid-direct-running', %s, %s, now())
                """,
                (organization_id, system_admin_user_id, system_admin_user_id),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_scenario_route (
                    config_version_id, scenario, primary_provider_config_id, primary_model,
                    fallback_model
                ) VALUES (%s, 'invalid-fallback', %s, 'test-model', 'fallback-model')
                """,
                (config_version_id, provider_id),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'validated', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                "UPDATE llm_config_version SET id = gen_random_uuid(), revision = revision + 1 WHERE id = %s",
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'draft', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'running', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'pending_publish', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'draft', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'running', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'running', revision = revision + 1,
                    published_by_system_admin_user_id = %s,
                    published_at = now()
                WHERE id = %s
                """,
                (system_admin_user_id, config_version_id),
            )
            cursor.execute(
                """
                SELECT configuration_hash, description, published_by_system_admin_user_id,
                       published_at, rollback_of_version_id
                FROM llm_config_version
                WHERE id = %s
                """,
                (config_version_id,),
            )
            published_snapshot = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO llm_release_record (
                    organization_id, config_version_id, evaluation_run_id,
                    submitted_by_system_admin_user_id
                ) VALUES (%s, %s, 'migration-eval', %s)
                RETURNING id
                """,
                (organization_id, config_version_id, system_admin_user_id),
            )
            release_record_id = cursor.fetchone()[0]
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_release_record (
                    organization_id, config_version_id, evaluation_run_id,
                    submitted_by_system_admin_user_id
                ) VALUES (%s, %s, 'wrong-tenant', %s)
                """,
                (other_organization_id, config_version_id, system_admin_user_id),
            )
            cursor.execute(
                """
                UPDATE llm_release_record
                SET status='running', revision=revision+1,
                    published_by_system_admin_user_id=%s, published_at=now()
                WHERE id=%s
                """,
                (system_admin_user_id, release_record_id),
            )
            cursor.execute(
                "UPDATE llm_release_record SET status='superseded', revision=revision+1 WHERE id=%s",
                (release_record_id,),
            )
            assert_integrity_error(
                cursor,
                "UPDATE llm_release_record SET evaluation_run_id='rewritten', revision=revision+1 WHERE id=%s",
                (release_record_id,),
            )
            assert_integrity_error(cursor, "DELETE FROM llm_release_record WHERE id=%s", (release_record_id,))
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_config_version WHERE id = %s",
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id, rollback_of_version_id
                ) VALUES (%s, 33, 'draft', 'invalid-running-rollback', %s, %s)
                """,
                (organization_id, system_admin_user_id, config_version_id),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'draft', revision = revision + 1,
                    published_by_system_admin_user_id = NULL,
                    published_at = NULL
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_scenario_route (
                    config_version_id, scenario, primary_provider_config_id, primary_model
                ) VALUES (%s, 'running-insert', %s, 'test-model')
                """,
                (config_version_id, provider_id),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'superseded', revision = revision + 1,
                    configuration_hash = 'rewritten-history',
                    description = 'rewritten history',
                    published_by_system_admin_user_id = %s,
                    published_at = published_at + interval '1 second',
                    rollback_of_version_id = %s
                WHERE id = %s
                """,
                (other_system_admin_user_id, metadata_rewrite_target_id, config_version_id),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, organization_id, store_id,
                    latency_ms, status, currency
                ) VALUES (%s, 'fallback', %s, %s, 10, 'succeeded', 'USD')
                """,
                (scenario_route_id, organization_id, store_id),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, organization_id, store_id,
                    latency_ms, status, currency
                ) VALUES (%s, 'primary', %s, %s, 10, 'succeeded', 'USD')
                """,
                (scenario_route_id, other_organization_id, store_id),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, organization_id, store_id,
                    latency_ms, status, currency
                ) VALUES (%s, 'primary', %s, %s, 10, 'succeeded', 'USD')
                """,
                (scenario_route_id, other_organization_id, other_store_id),
            )
            assert_integrity_error(
                cursor,
                "UPDATE llm_scenario_route SET primary_model = 'mutated-published-model' WHERE id = %s",
                (scenario_route_id,),
            )
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_scenario_route WHERE id = %s",
                (scenario_route_id,),
            )
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 1, 'draft', 'other-org-terminal', %s)
                RETURNING id
                """,
                (other_organization_id, system_admin_user_id),
            )
            other_organization_terminal_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE llm_config_version SET status = 'validated', revision = revision + 1 WHERE id = %s",
                (other_organization_terminal_id,),
            )
            cursor.execute(
                "UPDATE llm_config_version SET status = 'pending_publish', revision = revision + 1 WHERE id = %s",
                (other_organization_terminal_id,),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'running', revision = revision + 1,
                    published_by_system_admin_user_id = %s,
                    published_at = now()
                WHERE id = %s
                """,
                (system_admin_user_id, other_organization_terminal_id),
            )
            cursor.execute(
                "UPDATE llm_config_version SET status = 'rolled_back', revision = revision + 1 WHERE id = %s",
                (other_organization_terminal_id,),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id, rollback_of_version_id
                ) VALUES (%s, 34, 'draft', 'invalid-cross-org-rollback', %s, %s)
                """,
                (organization_id, system_admin_user_id, other_organization_terminal_id),
            )
            cursor.execute(
                """
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, organization_id, store_id,
                    latency_ms, status, currency
                ) VALUES (%s, 'primary', %s, %s, 10, 'succeeded', 'USD')
                RETURNING id
                """,
                (scenario_route_id, organization_id, store_id),
            )
            metric_id = cursor.fetchone()[0]
            cursor.execute("SELECT * FROM llm_invocation_metric WHERE id = %s", (metric_id,))
            metric_snapshot = cursor.fetchone()
            assert metric_snapshot is not None
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_invocation_metric
                SET organization_id = %s, store_id = %s
                WHERE id = %s
                """,
                (other_organization_id, other_store_id, metric_id),
            )
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_invocation_metric
                SET input_tokens = input_tokens + 1,
                    output_tokens = output_tokens + 1,
                    estimated_cost_micros = estimated_cost_micros + 1
                WHERE id = %s
                """,
                (metric_id,),
            )
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_invocation_metric WHERE id = %s",
                (metric_id,),
            )
            cursor.execute("SELECT * FROM llm_invocation_metric WHERE id = %s", (metric_id,))
            assert cursor.fetchone() == metric_snapshot
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'superseded', revision = revision + 1
                WHERE id = %s
                """,
                (config_version_id,),
            )
            cursor.execute(
                """
                SELECT configuration_hash, description, published_by_system_admin_user_id,
                       published_at, rollback_of_version_id
                FROM llm_config_version
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert cursor.fetchone() == published_snapshot
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_config_version WHERE id = %s",
                (config_version_id,),
            )
            cursor.execute(
                "SELECT count(*) FROM llm_invocation_metric WHERE scenario_route_id = %s",
                (scenario_route_id,),
            )
            assert cursor.fetchone() == (1,)
            assert_integrity_error(
                cursor,
                """
                UPDATE llm_config_version
                SET status = 'draft', revision = revision + 1,
                    published_by_system_admin_user_id = NULL,
                    published_at = NULL
                WHERE id = %s
                """,
                (config_version_id,),
            )
            assert_integrity_error(
                cursor,
                "UPDATE llm_scenario_route SET primary_model = 'mutated-referenced-model' WHERE id = %s",
                (scenario_route_id,),
            )
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_scenario_route WHERE id = %s",
                (scenario_route_id,),
            )
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id,
                    rollback_of_version_id
                ) VALUES (%s, 12, 'draft', 'rollback-version', %s, %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id, config_version_id),
            )
            rollback_version_id = cursor.fetchone()[0]
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'validated', revision = revision + 1
                WHERE id = %s
                """,
                (rollback_version_id,),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'pending_publish', revision = revision + 1
                WHERE id = %s
                """,
                (rollback_version_id,),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'running', revision = revision + 1,
                    published_by_system_admin_user_id = %s,
                    published_at = now()
                WHERE id = %s
                """,
                (system_admin_user_id, rollback_version_id),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'rolled_back', revision = revision + 1
                WHERE id = %s
                """,
                (rollback_version_id,),
            )
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_config_version WHERE id = %s",
                (rollback_version_id,),
            )
    finally:
        connection.rollback()
        connection.close()


def test_llm_version_lock_serializes_route_and_metric_writes() -> None:
    schema_name = f"migration_concurrency_{uuid.uuid4().hex}"
    setup_connection = psycopg.connect(DATABASE_URL)
    transition_connection: psycopg.Connection[object] | None = None

    try:
        with setup_connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            set_test_search_path(cursor, schema_name)
            for migration in load_migrations(Path("migrations")):
                cursor.execute(migration.sql)
            cursor.execute(
                """
                INSERT INTO system_admin_user (email, password_hash, display_name, role)
                VALUES ('concurrency-test@example.invalid', 'not-a-real-password-hash',
                        'Concurrency Test', 'super_admin')
                RETURNING id
                """
            )
            system_admin_user_id = cursor.fetchone()[0]
            cursor.execute("INSERT INTO organization (name) VALUES ('Concurrency Test') RETURNING id")
            organization_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_provider_config (
                    name, provider_type, base_url, secret_namespace, secret_name, secret_key
                ) VALUES ('concurrency-provider', 'test', 'https://example.invalid',
                          'test', 'llm', 'key')
                RETURNING id
                """
            )
            provider_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 1, 'draft', 'route-race', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            route_race_version_id = cursor.fetchone()[0]
        setup_connection.commit()

        transition_connection = psycopg.connect(DATABASE_URL)
        with transition_connection.cursor() as cursor:
            set_test_search_path(cursor, schema_name)
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'validated', revision = revision + 1
                WHERE id = %s
                """,
                (route_race_version_id,),
            )

        route_worker_name = f"migration-route-lock-{uuid.uuid4().hex}"
        with ThreadPoolExecutor(max_workers=1) as executor:
            route_future = executor.submit(
                execute_concurrent_statement,
                schema_name,
                """
                INSERT INTO llm_scenario_route (
                    config_version_id, scenario, primary_provider_config_id, primary_model
                ) VALUES (%s, 'concurrent-route', %s, 'test-model')
                """,
                (route_race_version_id, provider_id),
                route_worker_name,
            )
            wait_for_backend_lock(route_worker_name)
            transition_connection.commit()
            assert route_future.result(timeout=8) == "23514"
        transition_connection.close()
        transition_connection = None

        with setup_connection.cursor() as cursor:
            set_test_search_path(cursor, schema_name)
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    organization_id, version_number, status, configuration_hash,
                    created_by_system_admin_user_id
                ) VALUES (%s, 2, 'draft', 'metric-race', %s)
                RETURNING id
                """,
                (organization_id, system_admin_user_id),
            )
            metric_race_version_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_scenario_route (
                    config_version_id, scenario, primary_provider_config_id, primary_model
                ) VALUES (%s, 'metric-race', %s, 'test-model')
                RETURNING id
                """,
                (metric_race_version_id, provider_id),
            )
            metric_race_route_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE llm_config_version SET status = 'validated', revision = revision + 1 WHERE id = %s",
                (metric_race_version_id,),
            )
            cursor.execute(
                "UPDATE llm_config_version SET status = 'pending_publish', revision = revision + 1 WHERE id = %s",
                (metric_race_version_id,),
            )
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'running', revision = revision + 1,
                    published_by_system_admin_user_id = %s,
                    published_at = now()
                WHERE id = %s
                """,
                (system_admin_user_id, metric_race_version_id),
            )
        setup_connection.commit()

        transition_connection = psycopg.connect(DATABASE_URL)
        with transition_connection.cursor() as cursor:
            set_test_search_path(cursor, schema_name)
            cursor.execute(
                """
                UPDATE llm_config_version
                SET status = 'superseded', revision = revision + 1
                WHERE id = %s
                """,
                (metric_race_version_id,),
            )

        metric_worker_name = f"migration-metric-lock-{uuid.uuid4().hex}"
        with ThreadPoolExecutor(max_workers=1) as executor:
            metric_future = executor.submit(
                execute_concurrent_statement,
                schema_name,
                """
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, latency_ms, status, currency
                ) VALUES (%s, 'primary', 10, 'succeeded', 'USD')
                """,
                (metric_race_route_id,),
                metric_worker_name,
            )
            wait_for_backend_lock(metric_worker_name)
            transition_connection.commit()
            assert metric_future.result(timeout=8) == "23514"
    finally:
        if transition_connection is not None:
            transition_connection.rollback()
            transition_connection.close()
        setup_connection.rollback()
        setup_connection.close()
        cleanup_connection = psycopg.connect(DATABASE_URL)
        try:
            with cleanup_connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
            cleanup_connection.commit()
        finally:
            cleanup_connection.close()
