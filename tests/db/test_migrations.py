from pathlib import Path

from ecommerce_cs_agent.db.migrations import load_migration_sql


def test_initial_migration_defines_extensions_and_core_tables() -> None:
    sql = load_migration_sql("001_initial.sql")

    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in sql
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_record" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_graph_checkpoint" in sql
    assert "CREATE TABLE IF NOT EXISTS audit_log" in sql


def test_initial_migration_file_is_packaged_in_repo() -> None:
    migration = Path("db/migrations/001_initial.sql")

    assert migration.exists()
