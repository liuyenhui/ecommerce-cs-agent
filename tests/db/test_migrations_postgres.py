import os
import uuid
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
                      'llm_scenario_route',
                      'llm_connection_test',
                      'llm_invocation_metric'
                  )
                  AND relation.relkind = 'r'
                """,
                (schema_name,),
            )
            assert cursor.fetchone() == (5,)

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
                VALUES ('migration-reviewer@example.invalid', 'not-a-real-password-hash', 'Migration Reviewer', 'release_manager')
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
                INSERT INTO llm_provider_config (
                    name, provider_type, base_url, secret_namespace, secret_name, secret_key
                ) VALUES ('test-provider', 'openai-compatible', 'https://example.invalid', 'test', 'llm', 'api-key')
                RETURNING id
                """
            )
            provider_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    version_number, status, configuration_hash, created_by_system_admin_user_id
                ) VALUES (1, 'draft', 'test-hash', %s)
                RETURNING id
                """,
                (system_admin_user_id,),
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
                INSERT INTO llm_config_version (
                    version_number, status, configuration_hash, created_by_system_admin_user_id
                ) VALUES (10, 'draft', 'metadata-rewrite-target', %s)
                RETURNING id
                """,
                (system_admin_user_id,),
            )
            metadata_rewrite_target_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO llm_config_version (
                    version_number, status, configuration_hash, created_by_system_admin_user_id
                ) VALUES (11, 'draft', 'deletable-draft', %s)
                RETURNING id
                """,
                (system_admin_user_id,),
            )
            deletable_draft_id = cursor.fetchone()[0]
            cursor.execute("DELETE FROM llm_config_version WHERE id = %s", (deletable_draft_id,))
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
                    version_number, status, configuration_hash, created_by_system_admin_user_id,
                    published_by_system_admin_user_id, published_at
                ) VALUES (2, 'draft', 'invalid-published-draft', %s, %s, now())
                """,
                (system_admin_user_id, system_admin_user_id),
            )
            assert_integrity_error(
                cursor,
                """
                INSERT INTO llm_config_version (
                    version_number, status, configuration_hash, created_by_system_admin_user_id,
                    published_by_system_admin_user_id, published_at
                ) VALUES (3, 'running', 'invalid-direct-running', %s, %s, now())
                """,
                (system_admin_user_id, system_admin_user_id),
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
            assert_integrity_error(
                cursor,
                "DELETE FROM llm_config_version WHERE id = %s",
                (config_version_id,),
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
                INSERT INTO llm_invocation_metric (
                    scenario_route_id, route_role, organization_id, store_id,
                    latency_ms, status, currency
                ) VALUES (%s, 'primary', %s, %s, 10, 'succeeded', 'USD')
                RETURNING id
                """,
                (scenario_route_id, organization_id, store_id),
            )
            assert cursor.fetchone()[0] is not None
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
                    version_number, status, configuration_hash, created_by_system_admin_user_id,
                    rollback_of_version_id
                ) VALUES (12, 'draft', 'rollback-version', %s, %s)
                RETURNING id
                """,
                (system_admin_user_id, config_version_id),
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
