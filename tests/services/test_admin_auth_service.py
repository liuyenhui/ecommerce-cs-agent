from __future__ import annotations

from typing import Any

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import AdminSession, PostgresAdminAuthService, admin_auth_service_for


def test_admin_auth_service_uses_postgres_when_database_url_is_configured() -> None:
    settings = Settings(database_url="postgresql://example", environment="production")

    service = admin_auth_service_for(settings)

    assert isinstance(service, PostgresAdminAuthService)


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


class _FakeConnection:
    def __init__(self, fetch_rows: list[tuple[Any, ...]] | None = None) -> None:
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
            return self.connection.fetch_rows.pop(0)
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []
