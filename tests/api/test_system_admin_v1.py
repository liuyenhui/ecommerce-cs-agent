from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import ecommerce_cs_agent.api.app as app_module
from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import InMemorySystemAdminAuthService
from ecommerce_cs_agent.services.system_admin import (
    InMemorySystemAdminRepository,
    PostgresSystemAdminRepository,
    system_admin_repository_for,
)
from tests.api.test_v1_api import auth_headers, minimal_reply_request


def _test_app():
    return create_app(Settings(environment="test", database_url=None))


def test_system_admin_repository_allows_in_memory_only_in_test() -> None:
    repository = system_admin_repository_for(Settings(environment="test", database_url=None))

    assert isinstance(repository, InMemorySystemAdminRepository)


def test_system_admin_repository_requires_database_outside_test() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL is required for System Admin"):
        system_admin_repository_for(Settings(environment="development", database_url=None))


def test_system_admin_message_traces_require_scope_and_use_repository_policy() -> None:
    client = TestClient(_test_app())
    client.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-system-trace", "什么时候发货？"),
    )

    unscoped = client.get(
        "/v1/system-admin/message-traces",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )
    scoped = client.get(
        "/v1/system-admin/message-traces?organization_id=org-001&store_id=store-001",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    assert unscoped.status_code == 422
    assert unscoped.json()["error"]["code"] == "tenant_scope_required"
    assert scoped.status_code == 200
    assert scoped.json()["items"] == []


def test_system_admin_task_retry_rejects_unknown_or_non_retryable_task() -> None:
    client = TestClient(_test_app())

    response = client.post(
        "/v1/system-admin/tasks/task-missing/retry",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
        json={"idempotency_key": "retry-missing-001", "reason": "manual retry"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_system_admin_organization_store_and_audit_are_repository_backed() -> None:
    client = TestClient(_test_app())
    headers = {"Cookie": "agent_system_admin_session=test-system-session"}

    organization = client.post(
        "/v1/system-admin/organizations",
        headers=headers,
        json={
            "name": "Tenant A",
            "status": "active",
            "external_ref": "org-system-api",
            "reason": "onboard tenant",
        },
    )
    store = client.post(
        "/v1/system-admin/stores",
        headers=headers,
        json={
            "organization_id": "org-system-api",
            "name": "Tenant A PDD",
            "platform": "pdd",
            "external_store_id": "store-system-api",
            "status": "active",
            "reason": "onboard store",
        },
    )
    organizations = client.get("/v1/system-admin/organizations?status=active", headers=headers)
    stores = client.get("/v1/system-admin/stores?organization_id=org-system-api", headers=headers)
    tasks = client.get("/v1/system-admin/tasks", headers=headers)
    audit = client.get("/v1/system-admin/audit-logs", headers=headers)

    assert organization.status_code == 201
    assert organization.json()["organization"]["id"] == "org-system-api"
    assert organization.json()["organization"]["organization_id"] == "org-system-api"
    assert organization.json()["audit_log_id"].startswith("audit-")
    assert store.status_code == 201
    assert store.json()["store"]["id"] == "store-system-api"
    assert store.json()["store"]["store_id"] == "store-system-api"
    assert stores.status_code == 200
    assert stores.json()["items"][0]["organization_id"] == "org-system-api"
    assert organizations.json()["page_info"]["total"] >= 1
    assert tasks.status_code == 200
    assert "page_info" in tasks.json()
    assert audit.status_code == 200
    assert audit.json()["items"][0]["action"].startswith("system_admin.")


def test_system_admin_api_uses_postgres_repository_when_database_url_is_configured(monkeypatch) -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "org-db",
                    "Database Tenant",
                    "active",
                    {"contact": {"email": "ops@example.test"}},
                    "2026-06-18T00:00:00Z",
                )
            ]
        ]
    )

    def fake_repo_init(self: PostgresSystemAdminRepository, database_url: str) -> None:
        self._database_url = database_url
        self._connect = lambda _url: connection

    monkeypatch.setattr(app_module, "system_admin_auth_service_for", lambda settings: InMemorySystemAdminAuthService(settings))
    monkeypatch.setattr(PostgresSystemAdminRepository, "__init__", fake_repo_init)

    client = TestClient(create_app(Settings(database_url="postgresql://example", environment="development")))
    response = client.get(
        "/v1/system-admin/organizations?status=active",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "org-db"
    assert "FROM organization" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_system_admin_message_traces_use_postgres_repository_when_database_url_is_configured(monkeypatch) -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "decision-db",
                    "org-db",
                    "store-db",
                    "req-db",
                    "msg-db",
                    "candidate",
                    "low",
                    "completed",
                    "2026-06-18T00:00:00Z",
                )
            ],
        ]
    )

    def fake_repo_init(self: PostgresSystemAdminRepository, database_url: str) -> None:
        self._database_url = database_url
        self._connect = lambda _url: connection

    monkeypatch.setattr(app_module, "system_admin_auth_service_for", lambda settings: InMemorySystemAdminAuthService(settings))
    monkeypatch.setattr(PostgresSystemAdminRepository, "__init__", fake_repo_init)

    client = TestClient(create_app(Settings(database_url="postgresql://example", environment="development")))
    response = client.get(
        "/v1/system-admin/message-traces?organization_id=org-db&store_id=store-db&external_message_id=msg-db",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response.status_code == 200
    assert response.json()["items"][0]["decision_id"] == "decision-db"
    assert response.json()["items"][0]["external_message_id"] == "msg-db"
    assert "FROM decision_record decision" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_system_admin_pagination_parameters_are_applied() -> None:
    client = TestClient(_test_app())
    headers = {"Cookie": "agent_system_admin_session=test-system-session"}
    for index in range(3):
        client.post(
            "/v1/system-admin/organizations",
            headers=headers,
            json={
                "name": f"Tenant {index}",
                "status": "active",
                "external_ref": f"org-page-{index}",
                "reason": "pagination test",
            },
        )

    response = client.get("/v1/system-admin/organizations?page=2&page_size=2", headers=headers)

    assert response.status_code == 200
    assert response.json()["page_info"] == {"page": 2, "page_size": 2, "total": 4}
    assert len(response.json()["items"]) == 2


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
