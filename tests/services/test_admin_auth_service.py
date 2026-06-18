from __future__ import annotations

from typing import Any

import pytest

from fastapi import HTTPException

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import (
    AdminSession,
    PostgresAdminAuthService,
    PostgresSystemAdminAuthService,
    admin_auth_service_for,
    system_admin_auth_service_for,
)


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
