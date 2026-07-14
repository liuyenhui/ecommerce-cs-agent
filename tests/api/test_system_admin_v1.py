from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _system_session():
    service = InMemorySystemAdminAuthService(Settings(environment="test", database_url=None))
    return service.require_session("agent_system_admin_session=test-system-session", None)[1]


def test_system_admin_repository_allows_in_memory_only_in_test() -> None:
    repository = system_admin_repository_for(Settings(environment="test", database_url=None))

    assert isinstance(repository, InMemorySystemAdminRepository)


def test_system_admin_repository_requires_database_outside_test() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL is required for System Admin"):
        system_admin_repository_for(Settings(environment="development", database_url=None))


def test_system_admin_dashboard_summary_contract() -> None:
    client = TestClient(_test_app())

    response = client.get(
        "/v1/system-admin/dashboard-summary",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "active_organizations",
        "active_stores",
        "decisions_today",
        "auto_reply_rate",
        "handoff_rate",
        "error_rate",
        "readiness_blockers",
        "pending_tasks",
        "critical_alerts",
        "generated_at",
    }
    assert response.json()["auto_reply_rate"] is None
    assert response.json()["handoff_rate"] is None
    assert response.json()["error_rate"] is None

    customer_session = client.get(
        "/v1/system-admin/dashboard-summary",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )
    missing_session = client.get("/v1/system-admin/dashboard-summary")

    assert customer_session.status_code == 403
    assert missing_session.status_code == 401


def test_in_memory_system_admin_dashboard_summary_uses_explicit_fixture_collections() -> None:
    now = datetime.now(timezone.utc)
    repository = InMemorySystemAdminRepository()
    repository.organizations = {
        "org-active": {"status": "active"},
        "org-suspended": {"status": "suspended"},
    }
    repository.stores = {
        "store-ready": {"status": "active", "readiness_status": "ready"},
        "store-blocked": {"status": "active", "readiness_status": "blocked"},
        "store-inactive": {"status": "inactive", "readiness_status": "ready"},
    }
    repository.decisions = {
        "auto": {"decision_type": "auto_reply", "status": "completed", "created_at": now},
        "handoff": {"decision_type": "handoff", "status": "completed", "created_at": now},
        "error": {"decision_type": "candidate", "status": "failed", "created_at": now},
        "old": {"decision_type": "auto_reply", "status": "completed", "created_at": now - timedelta(days=1)},
    }
    repository.tasks = {
        "queued": {"status": "queued"},
        "running": {"status": "running"},
        "failed": {"status": "failed"},
        "done": {"status": "completed"},
    }

    response = repository.dashboard_summary(_system_session())

    assert response["active_organizations"] == 1
    assert response["active_stores"] == 2
    assert response["decisions_today"] == 3
    assert response["auto_reply_rate"] == pytest.approx(1 / 3)
    assert response["handoff_rate"] == pytest.approx(1 / 3)
    assert response["error_rate"] == pytest.approx(1 / 3)
    assert response["readiness_blockers"] == 1
    assert response["pending_tasks"] == 2
    assert response["critical_alerts"] == 1


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


def test_system_admin_dashboard_summary_uses_postgres_total_aggregates(monkeypatch) -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (
                123,
                456,
                789,
                0.25,
                0.125,
                0.05,
                7,
                11,
                2,
                "2026-07-14T08:00:00Z",
            )
        ]
    )

    def fake_repo_init(self: PostgresSystemAdminRepository, database_url: str) -> None:
        self._database_url = database_url
        self._connect = lambda _url: connection

    monkeypatch.setattr(app_module, "system_admin_auth_service_for", lambda settings: InMemorySystemAdminAuthService(settings))
    monkeypatch.setattr(PostgresSystemAdminRepository, "__init__", fake_repo_init)

    client = TestClient(create_app(Settings(database_url="postgresql://example", environment="development")))
    response = client.get(
        "/v1/system-admin/dashboard-summary",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response.status_code == 200
    assert response.json() == {
        "active_organizations": 123,
        "active_stores": 456,
        "decisions_today": 789,
        "auto_reply_rate": 0.25,
        "handoff_rate": 0.125,
        "error_rate": 0.05,
        "readiness_blockers": 7,
        "pending_tasks": 11,
        "critical_alerts": 2,
        "generated_at": "2026-07-14T08:00:00Z",
    }
    assert "FROM organization" in executed_sql
    assert "FROM store" in executed_sql
    assert "FROM decision_record" in executed_sql
    assert "FROM background_task" in executed_sql
    assert "NULLIF" in executed_sql
    assert "LIMIT" not in executed_sql
    assert "OFFSET" not in executed_sql
    assert executed_sql.count("INSERT INTO system_admin_audit_log") == 1


def test_postgres_system_admin_dashboard_summary_maps_zero_denominator_rates_to_none() -> None:
    connection = _FakeConnection(fetch_rows=[(0, 0, 0, None, None, None, 0, 0, 0, "2026-07-14T08:00:00Z")])
    repository = PostgresSystemAdminRepository.__new__(PostgresSystemAdminRepository)
    repository._database_url = "postgresql://example"
    repository._connect = lambda _url: connection

    response = repository.dashboard_summary(_system_session())

    assert response["auto_reply_rate"] is None
    assert response["handoff_rate"] is None
    assert response["error_rate"] is None


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
