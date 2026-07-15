from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import AdminSession, InMemoryAdminAuthService, PostgresAdminAuthService
from tests.admin_fixtures import customer_admin_auth_fixture


def test_in_memory_admin_oidc_bound_sub_logs_in_without_creating_permissions() -> None:
    service = customer_admin_auth_fixture(Settings())
    service.users["admin-001"]["fcihome_account_sub"] = "acct-admin-001"

    response, token = service.login_oidc(
        {
            "sub": "acct-admin-001",
            "email": "different@example.test",
            "email_verified": True,
        }
    )

    assert token
    assert response["user"]["user_id"] == "admin-001"
    assert response["user"]["fcihome_account_sub"] == "acct-admin-001"
    assert list(service.users) == ["admin-001"]
    assert service.audit_logs[0]["action"] == "auth.oidc.login"


def test_in_memory_admin_oidc_autolinks_unique_active_email_and_writes_redacted_audit() -> None:
    service = customer_admin_auth_fixture(Settings())

    response, token = service.login_oidc(
        {
            "sub": "acct-admin-001",
            "email": "admin@example.test",
            "email_verified": True,
            "code": "oauth-code",
            "access_token": "access-token",
            "client_secret": "client-secret",
            "password": "admin-password",
            "Cookie": "agent_admin_session=secret",
        }
    )

    flattened_audit = str(service.audit_logs)
    assert token
    assert response["user"]["fcihome_account_sub"] == "acct-admin-001"
    assert service.users["admin-001"]["fcihome_account_sub"] == "acct-admin-001"
    assert [item["action"] for item in service.audit_logs[:2]] == ["auth.oidc.login", "auth.oidc.link"]
    for forbidden in ("oauth-code", "access-token", "client-secret", "admin-password", "agent_admin_session=secret"):
        assert forbidden not in flattened_audit
    for forbidden_key in ("code", "access_token", "client_secret", "password", "Cookie"):
        assert forbidden_key not in flattened_audit


def test_in_memory_admin_oidc_rejects_unknown_or_ambiguous_email_without_permissions() -> None:
    service = customer_admin_auth_fixture(Settings())

    with pytest.raises(HTTPException) as unknown:
        service.login_oidc({"sub": "acct-new-001", "email": "unknown@example.test", "email_verified": True})

    service.users["admin-002"] = {
        **service.users["admin-001"],
        "user_id": "admin-002",
        "email": "admin@example.test",
        "fcihome_account_sub": None,
    }
    with pytest.raises(HTTPException) as ambiguous:
        service.login_oidc({"sub": "acct-new-002", "email": "admin@example.test", "email_verified": True})

    assert unknown.value.status_code == 403
    assert unknown.value.detail["error"]["code"] == "oidc_unbound_account"
    assert ambiguous.value.status_code == 403
    assert ambiguous.value.detail["error"]["code"] == "oidc_unbound_account"
    assert all(user.get("fcihome_account_sub") is None for user in service.users.values())


def test_postgres_admin_oidc_autolinks_only_unique_active_email_and_audits_without_secrets() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            None,
            [
                (
                    "admin-uuid",
                    "org-uuid",
                    "store-uuid",
                    "admin@example.test",
                    "plain:admin-password",
                    "Customer Admin",
                    ["owner"],
                    None,
                    "org-001",
                    "store-001",
                )
            ],
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, token = service.login_oidc(
        {
            "sub": "acct-admin-001",
            "email": "admin@example.test",
            "email_verified": True,
            "code": "oauth-code",
            "access_token": "access-token",
            "client_secret": "client-secret",
            "password": "admin-password",
            "Cookie": "agent_admin_session=secret",
        }
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    audit_params = str([params for sql, params in connection.executed if "INSERT INTO admin_audit_log" in sql])
    assert token
    assert response["user"]["fcihome_account_sub"] == "acct-admin-001"
    assert "admin.fcihome_account_sub = %s" in executed_sql
    assert "admin.fcihome_account_sub IS NULL" in executed_sql
    assert "UPDATE admin_user" in executed_sql
    assert "INSERT INTO admin_session" in executed_sql
    assert executed_sql.count("INSERT INTO admin_audit_log") >= 2
    for forbidden in ("oauth-code", "access-token", "client-secret", "admin-password", "agent_admin_session=secret"):
        assert forbidden not in audit_params


def test_postgres_admin_oidc_rejects_ambiguous_active_email_before_session_creation() -> None:
    settings = Settings(database_url="postgresql://example")
    rows = [
        (
            "admin-uuid-1",
            "org-uuid",
            "store-uuid",
            "admin@example.test",
            "plain:admin-password",
            "Customer Admin",
            ["owner"],
            None,
            "org-001",
            "store-001",
        ),
        (
            "admin-uuid-2",
            "org-uuid",
            "store-uuid",
            "admin@example.test",
            "plain:admin-password",
            "Customer Admin",
            ["owner"],
            None,
            "org-001",
            "store-001",
        ),
    ]
    connection = _FakeConnection(fetch_rows=[None, rows])
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        service.login_oidc({"sub": "acct-admin-001", "email": "admin@example.test", "email_verified": True})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "oidc_unbound_account"
    assert "INSERT INTO admin_session" not in executed_sql
    assert "UPDATE admin_user" not in executed_sql


def test_postgres_admin_oidc_link_requires_current_user_email_match() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(fetch_rows=[("admin-uuid",)])
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    service.me = lambda _session: {"user": {"fcihome_account_sub": "acct-admin-001"}}  # type: ignore[method-assign]
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=datetime.now(timezone.utc),
    )

    service.link_oidc(session, {"sub": "acct-admin-001", "email": "admin@example.test"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "UPDATE admin_user" in executed_sql
    assert "lower(email) = lower(%s)" in executed_sql
    assert "INSERT INTO admin_audit_log" in executed_sql


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
