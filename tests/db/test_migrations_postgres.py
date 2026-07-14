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
                    version_number, status, configuration_hash, created_by_system_admin_user_id
                ) VALUES (3, 'running', 'invalid-unpublished-running', %s)
                """,
                (system_admin_user_id,),
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
    finally:
        connection.rollback()
        connection.close()
