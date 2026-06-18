from __future__ import annotations

from typing import Any

import pytest

from fastapi import HTTPException

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import (
    AdminSession,
    PostgresAdminAuthService,
    PostgresSystemAdminAuthService,
    SystemAdminSession,
    admin_auth_service_for,
    system_admin_auth_service_for,
)
from ecommerce_cs_agent.services.system_admin import PostgresSystemAdminRepository


def test_admin_auth_service_uses_postgres_when_database_url_is_configured() -> None:
    settings = Settings(database_url="postgresql://example", environment="production")

    service = admin_auth_service_for(settings)

    assert isinstance(service, PostgresAdminAuthService)


def test_system_admin_auth_service_uses_postgres_when_database_url_is_configured() -> None:
    settings = Settings(database_url="postgresql://example", environment="production")

    service = system_admin_auth_service_for(settings)

    assert isinstance(service, PostgresSystemAdminAuthService)


def test_postgres_admin_auth_login_bootstraps_user_and_persists_hashed_session() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "admin-uuid",
                "org-uuid",
                "store-uuid",
                "admin@example.test",
                "plain:admin-password",
                "Customer Admin",
                ["owner"],
                "org-001",
                "store-001",
            )
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, token = service.login({"email": "admin@example.test", "password": "admin-password"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response["user"]["user_id"] == "admin-uuid"
    assert token
    assert token != settings.admin_session
    assert "INSERT INTO organization" in executed_sql
    assert "INSERT INTO admin_user" in executed_sql
    assert "INSERT INTO admin_membership" in executed_sql
    assert "INSERT INTO admin_session" in executed_sql
    session_insert = [item for item in connection.executed if "INSERT INTO admin_session" in item[0]][0]
    assert token not in str(session_insert[1])


def test_postgres_admin_auth_require_session_queries_hashed_active_session() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "admin-uuid",
                "org-uuid",
                "store-uuid",
                "admin@example.test",
                "Customer Admin",
                ["owner"],
                "org-001",
                "store-001",
            )
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    principal, session = service.require_session("agent_admin_session=session-token", None)

    assert principal.user_id == "admin-uuid"
    assert session.active_organization_id == "org-001"
    assert "FROM admin_session" in connection.executed[0][0]
    assert "session-token" not in str(connection.executed[0][1])


def test_postgres_admin_auth_store_invitation_roles_write_to_db_and_audit() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection()
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    settings_response = service.update_store_settings(
        session,
        "store-001",
        {"organization_id": "org-001", "settings": {"assist_enabled": True}, "reason": "enable"},
    )
    invitation = service.create_invitation(
        session,
        {
            "organization_id": "org-001",
            "email": "invitee@example.test",
            "roles": ["store_operator"],
            "store_ids": ["store-001"],
            "reason": "invite",
            "idempotency_key": "invite-001",
        },
    )
    role_update = service.update_roles(
        session,
        "admin-uuid",
        {"organization_id": "org-001", "roles": ["owner"], "store_ids": ["store-001"], "reason": "owner"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert settings_response["settings"]["assist_enabled"] is True
    assert invitation["status"] == "pending"
    assert role_update["user"]["user_id"] == "admin-uuid"
    assert "UPDATE store" in executed_sql
    assert "INSERT INTO admin_invitation" in executed_sql
    assert "INSERT INTO admin_membership" in executed_sql
    assert executed_sql.count("INSERT INTO admin_audit_log") >= 3


def test_postgres_admin_auth_me_reads_organizations_stores_and_users_from_db() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            [("org-001", "Acme", "active", {"tier": "dev"})],
            (1,),
            [("store-001", "org-001", "PDD Store", "pdd", "active", {"assist_enabled": True})],
            (1,),
            [("admin-uuid", "admin@example.test", "Customer Admin", "active", ["owner"], "org-001", ["store-001"])],
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    me = service.me(session)

    assert me["user"]["email"] == "admin@example.test"
    assert me["organizations"][0]["name"] == "Acme"
    assert me["stores"][0]["metadata"]["assist_enabled"] is True
    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "FROM admin_membership membership" in executed_sql
    assert "JOIN store st ON st.organization_id = org.id" in executed_sql
    assert "JOIN admin_membership membership ON membership.admin_user_id = admin.id" in executed_sql


def test_postgres_admin_auth_list_audit_logs_reads_db_and_enforces_org_access() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "audit-001",
                    "org-001",
                    "store-001",
                    "admin-uuid",
                    "store.settings.update",
                    "store",
                    "store-001",
                    {"reason": "test"},
                    False,
                    "2026-06-18T00:00:00Z",
                )
            ],
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    logs = service.list_audit_logs(session, "org-001")

    assert logs["items"][0]["id"] == "audit-001"
    assert logs["items"][0]["actor_id"] == "admin-uuid"
    assert "FROM admin_audit_log audit" in connection.executed[1][0]


def test_postgres_admin_auth_rejects_cross_org_db_list_access() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(fetch_rows=[None])
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    with pytest.raises(HTTPException) as exc:
        service.list_stores(session, "org-other")

    assert exc.value.status_code == 403


def test_postgres_system_admin_auth_login_persists_hashed_session_and_audit() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "sysadmin-uuid",
                "system-admin@example.test",
                "plain:system-admin-password",
                "System Admin",
                "super_admin",
            )
        ]
    )
    service = PostgresSystemAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, token = service.login(
        {"email": "system-admin@example.test", "password": "system-admin-password"}
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response["user"]["id"] == "sysadmin-uuid"
    assert token
    assert token != settings.system_admin_session
    assert "INSERT INTO system_admin_user" in executed_sql
    assert "INSERT INTO system_admin_session" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql
    session_insert = [item for item in connection.executed if "INSERT INTO system_admin_session" in item[0]][0]
    assert token not in str(session_insert[1])


def test_postgres_system_admin_auth_require_session_queries_hashed_active_session() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "sysadmin-uuid",
                "system-admin@example.test",
                "System Admin",
                "super_admin",
            )
        ]
    )
    service = PostgresSystemAdminAuthService(settings)
    service._connect = lambda _url: connection

    principal, session = service.require_session("agent_system_admin_session=session-token", None)

    assert principal.kind == "system_admin"
    assert principal.user_id == "sysadmin-uuid"
    assert principal.role == "super_admin"
    assert session.email == "system-admin@example.test"
    assert "FROM system_admin_session" in connection.executed[0][0]
    assert "session-token" not in str(connection.executed[0][1])


def test_postgres_system_admin_auth_logout_revokes_session_and_writes_audit() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(fetch_rows=[("sysadmin-uuid",)])
    service = PostgresSystemAdminAuthService(settings)
    service._connect = lambda _url: connection

    service.logout("session-token")

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "UPDATE system_admin_session" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql
    assert "session-token" not in str(connection.executed[0][1])


def test_postgres_system_admin_repository_lists_and_creates_org_store_with_audit() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [("org-001", "Acme", "active", {"contact": {"email": "ops@example.test"}}, "2026-06-18T00:00:00Z")],
            ("org-new", "New Tenant", "active", {"contact": {}, "external_ref": "org-new"}, "2026-06-18T00:00:01Z"),
            ("org-new-uuid",),
            ("org-new", "store-new", "New Store", "pdd", "active", {"reason": "onboard"}, "2026-06-18T00:00:02Z", False),
            (1,),
            [("org-new", "store-new", "New Store", "pdd", "active", {"reason": "onboard"}, "2026-06-18T00:00:02Z", False)],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    session = _system_session()

    orgs = repository.list_organizations(session, {"status": "active"})
    created_org = repository.create_organization(
        session,
        {"name": "New Tenant", "status": "active", "external_ref": "org-new", "reason": "onboard"},
    )
    created_store = repository.create_store(
        session,
        {
            "organization_id": "org-new",
            "name": "New Store",
            "platform": "pdd",
            "external_store_id": "store-new",
            "status": "active",
            "reason": "onboard",
        },
    )
    stores = repository.list_stores(session, {"organization_id": "org-new"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert orgs["items"][0]["id"] == "org-001"
    assert created_org["organization"]["id"] == "org-new"
    assert created_store["store"]["id"] == "store-new"
    assert stores["items"][0]["organization_id"] == "org-new"
    assert "FROM organization" in executed_sql
    assert "INSERT INTO organization" in executed_sql
    assert "INSERT INTO store" in executed_sql
    assert executed_sql.count("INSERT INTO system_admin_audit_log") >= 4


def test_postgres_system_admin_repository_creates_user_with_audit() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (
                "sysadmin-new",
                "new-system-admin@example.test",
                "New System Admin",
                "technical_support",
                "active",
                "2026-06-18T00:00:00Z",
            )
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    response = repository.create_user(
        _system_session(),
        {
            "email": "new-system-admin@example.test",
            "display_name": "New System Admin",
            "roles": ["technical_support"],
            "reason": "support coverage",
        },
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response["user"]["system_user_id"] == "sysadmin-new"
    assert response["user"]["roles"] == ["technical_support"]
    assert response["audit_log_id"]
    assert "INSERT INTO system_admin_user" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_system_admin_repository_rejects_user_creation_for_release_admin() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")

    with pytest.raises(HTTPException) as exc:
        repository.create_user(
            _system_session(role="release_admin"),
            {
                "email": "new-system-admin@example.test",
                "display_name": "New System Admin",
                "roles": ["technical_support"],
                "reason": "support coverage",
            },
        )

    assert exc.value.status_code == 403


def test_postgres_system_admin_repository_replays_create_organization_idempotently() -> None:
    organization_row = (
        "org-idem",
        "Idem Tenant",
        "active",
        {"contact": {}, "external_ref": "org-idem"},
        "2026-06-18T00:00:00Z",
    )
    connection = _FakeConnection(fetch_rows=[None, organization_row, ("audit-001", "org-idem"), organization_row])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    payload = {
        "name": "Idem Tenant",
        "status": "active",
        "external_ref": "org-idem",
        "reason": "onboard",
        "idempotency_key": "org-idem-key",
    }

    first = repository.create_organization(_system_session(), payload)
    second = repository.create_organization(_system_session(), payload)

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert first["organization"]["organization_id"] == "org-idem"
    assert second["organization"]["organization_id"] == "org-idem"
    assert second["audit_log_id"] == "audit-001"
    assert executed_sql.count("INSERT INTO organization") == 1


def test_postgres_system_admin_repository_lists_tasks_and_retries_failed_task() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "task-001",
                    "embedding",
                    "failed",
                    "org-001",
                    "store-001",
                    "asset-001",
                    None,
                    "provider timeout",
                    0,
                    None,
                    "2026-06-18T00:00:00Z",
                )
            ],
            None,
            ("failed", True, "org-001", "store-001"),
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    session = _system_session()

    tasks = repository.list_tasks(session, {"organization_id": "org-001", "status": "failed"})
    retry = repository.retry_task(
        session,
        "task-001",
        {"idempotency_key": "retry-001", "reason": "manual retry"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert tasks["items"][0]["task_id"] == "task-001"
    assert tasks["items"][0]["error_summary"] == "provider timeout"
    assert retry["task_id"] == "task-001"
    assert retry["status"] == "queued"
    assert retry["audit_log_id"]
    assert "FROM background_task task" in executed_sql
    assert "UPDATE background_task" in executed_sql
    assert "retry-001" in str(connection.executed)


def test_postgres_system_admin_repository_replays_task_retry_idempotently() -> None:
    connection = _FakeConnection(fetch_rows=[None, ("failed", True, "org-001", "store-001"), ("audit-001", "task-001")])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    payload = {"idempotency_key": "retry-001", "reason": "manual retry"}

    first = repository.retry_task(_system_session(), "task-001", payload)
    second = repository.retry_task(_system_session(), "task-001", payload)

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert first["status"] == "queued"
    assert second == {"task_id": "task-001", "status": "queued", "audit_log_id": "audit-001"}
    assert executed_sql.count("UPDATE background_task") == 1


def test_postgres_system_admin_repository_readiness_reads_db_and_returns_all_checks() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [("org-001", "store-001", True, False, True, True)],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    readiness = repository.store_readiness(_system_session(), {"organization_id": "org-001"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    item = readiness["items"][0]
    assert item["organization_id"] == "org-001"
    assert item["store_id"] == "store-001"
    assert item["status"] == "warning"
    assert {check["code"] for check in item["checks"]} == {
        "product_content",
        "price_snapshot",
        "knowledge_review",
        "rules",
        "action_capabilities",
        "api_integration",
    }
    assert "FROM store st" in executed_sql
    assert "platform_account" in executed_sql
    assert "external_api_token" in executed_sql


def test_postgres_system_admin_repository_rejects_non_failed_task_retry_with_409() -> None:
    connection = _FakeConnection(fetch_rows=[None, ("succeeded", True, "org-001", "store-001")])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        repository.retry_task(
            _system_session(),
            "task-001",
            {"idempotency_key": "retry-001", "reason": "manual retry"},
        )

    assert exc.value.status_code == 409


def test_postgres_system_admin_repository_lists_system_audit_logs() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "audit-001",
                    "sysadmin-uuid",
                    "org-001",
                    "store-001",
                    "system_admin.task.retry",
                    "background_task",
                    "task-001",
                    {"reason": "manual retry"},
                    "2026-06-18T00:00:00Z",
                )
            ]
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    logs = repository.list_audit_logs(_system_session(), {"organization_id": "org-001"})

    assert logs["items"][0]["audit_log_id"] == "audit-001"
    assert logs["items"][0]["actor_system_user_id"] == "sysadmin-uuid"
    assert "FROM system_admin_audit_log audit" in connection.executed[1][0]


def _system_session(role: str = "super_admin") -> Any:
    return SystemAdminSession(
        token="session-token",
        user_id="sysadmin-uuid",
        email="system-admin@example.test",
        display_name="System Admin",
        role=role,
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


class _FakeConnection:
    def __init__(self, fetch_rows: list[Any] | None = None) -> None:
        self.fetch_rows = fetch_rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.connection.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        if self.connection.fetch_rows:
            item = self.connection.fetch_rows.pop(0)
            if isinstance(item, list):
                return item[0] if item else None
            return item
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        if self.connection.fetch_rows:
            item = self.connection.fetch_rows.pop(0)
            if isinstance(item, list):
                return item
            return [item]
        return []
