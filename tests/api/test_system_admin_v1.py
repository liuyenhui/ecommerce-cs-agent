from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any

import pytest
from fastapi import HTTPException
from psycopg import OperationalError, ProgrammingError
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
        "recent_releases",
        "recent_releases_status",
        "recent_releases_error",
        "generated_at",
    }
    assert response.json()["auto_reply_rate"] is None
    assert response.json()["handoff_rate"] is None
    assert response.json()["error_rate"] is None
    assert response.json()["recent_releases"] == []
    assert response.json()["recent_releases_status"] == "available"
    assert response.json()["recent_releases_error"] is None

    customer_session = client.get(
        "/v1/system-admin/dashboard-summary",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )
    missing_session = client.get("/v1/system-admin/dashboard-summary")

    assert customer_session.status_code == 403
    assert missing_session.status_code == 401


def test_system_admin_readiness_api_filters_before_total_and_page(monkeypatch) -> None:
    repository = InMemorySystemAdminRepository()
    repository.stores = {
        "ready-first": {"id": "ready-first", "organization_id": "org-001", "status": "active"},
        **{
            f"blocked-{index}": {"id": f"blocked-{index}", "organization_id": "org-001", "status": "active"}
            for index in range(1, 7)
        },
    }
    repository.product_store_ids = {"ready-first"}
    repository.price_snapshot_store_ids = {"ready-first"}
    repository.approved_knowledge_store_ids = {"ready-first"}
    repository.active_integration_store_ids = {"ready-first"}
    monkeypatch.setattr(app_module, "system_admin_repository_for", lambda _settings: repository)
    client = TestClient(_test_app())

    response = client.get(
        "/v1/system-admin/readiness/stores?status=blocked&page=1&page_size=5",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    assert response.status_code == 200
    assert response.json()["page_info"] == {"page": 1, "page_size": 5, "total": 6}
    assert len(response.json()["items"]) == 5
    assert {item["status"] for item in response.json()["items"]} == {"blocked"}

    unfiltered = client.get(
        "/v1/system-admin/readiness/stores?status=&page=1&page_size=5",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )
    invalid = client.get(
        "/v1/system-admin/readiness/stores?status=unknown",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )
    assert unfiltered.status_code == 200
    assert unfiltered.json()["page_info"]["total"] == 7
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_in_memory_system_admin_dashboard_summary_uses_explicit_fixture_collections() -> None:
    now = datetime.now(timezone.utc)
    repository = InMemorySystemAdminRepository()
    repository.organizations = {
        "org-active": {"status": "active"},
        "org-suspended": {"status": "suspended"},
    }
    repository.stores = {
        "store-ready": {"id": "store-ready", "organization_id": "org-active", "status": "active"},
        "store-product-only": {"id": "store-product-only", "organization_id": "org-active", "status": "active"},
        "store-inactive": {"id": "store-inactive", "organization_id": "org-active", "status": "inactive"},
    }
    repository.product_store_ids = {"store-ready", "store-product-only"}
    repository.price_snapshot_store_ids = {"store-ready"}
    repository.approved_knowledge_store_ids = {"store-ready"}
    repository.active_integration_store_ids = {"store-ready"}
    repository.decisions = {
        "auto": {"decision_type": "auto_reply", "status": "completed", "created_at": now},
        "handoff": {"decision_type": "handoff", "status": "completed", "created_at": now},
        "error": {"decision_type": "candidate", "status": "failed", "created_at": now},
        "old": {"decision_type": "auto_reply", "status": "completed", "created_at": now - timedelta(days=1)},
        "future": {
            "decision_type": "candidate",
            "status": "completed",
            "created_at": now.replace(hour=23, minute=59, second=59, microsecond=999999),
        },
    }
    repository.tasks = {
        "queued": {"status": "queued"},
        "running": {"status": "running"},
        "failed": {"status": "failed"},
        "done": {"status": "completed"},
    }
    repository.releases = {
        "release-new": {
            "release_id": "release-new",
            "organization_id": "org-active",
            "config_version_id": "version-2",
            "version_number": 2,
            "status": "running",
            "published_at": "2026-07-15T08:00:00Z",
            "submitted_at": "2026-07-15T07:00:00Z",
        },
        "release-old": {
            "release_id": "release-old",
            "organization_id": "org-active",
            "config_version_id": "version-1",
            "version_number": 1,
            "status": "superseded",
            "published_at": "2026-07-14T08:00:00Z",
            "submitted_at": "2026-07-14T07:00:00Z",
        },
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
    assert [item["release_id"] for item in response["recent_releases"]] == ["release-new", "release-old"]

    repository.price_snapshot_store_ids.add("store-product-only")
    repository.approved_knowledge_store_ids.add("store-product-only")
    repository.active_integration_store_ids.add("store-product-only")

    assert repository.dashboard_summary(_system_session())["readiness_blockers"] == 0


@pytest.mark.parametrize(
    "missing_fixture",
    [
        "product_store_ids",
        "price_snapshot_store_ids",
        "approved_knowledge_store_ids",
        "active_integration_store_ids",
    ],
)
def test_in_memory_system_admin_dashboard_requires_every_readiness_input(missing_fixture: str) -> None:
    repository = InMemorySystemAdminRepository()
    repository.stores = {"store-check": {"id": "store-check", "status": "active"}}
    repository.product_store_ids = {"store-check"}
    repository.price_snapshot_store_ids = {"store-check"}
    repository.approved_knowledge_store_ids = {"store-check"}
    repository.active_integration_store_ids = {"store-check"}
    getattr(repository, missing_fixture).clear()

    response = repository.dashboard_summary(_system_session())

    assert response["readiness_blockers"] == 1


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


@pytest.mark.parametrize(
    "payload",
    [
        {"idempotency_key": "   ", "reason": "manual"},
        {"idempotency_key": "retry-valid", "reason": "   "},
        {"idempotency_key": "x" * 129, "reason": "manual"},
        {"idempotency_key": "retry-valid", "reason": "x" * 513},
        {"idempotency_key": 123, "reason": "manual"},
        {"idempotency_key": "retry-valid", "reason": ["manual"]},
    ],
)
def test_system_admin_task_retry_rejects_invalid_trimmed_input(payload: dict[str, Any]) -> None:
    response = TestClient(_test_app()).post(
        "/v1/system-admin/tasks/task-missing/retry",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_in_memory_system_admin_tasks_return_persisted_retryable_flag() -> None:
    repository = InMemorySystemAdminRepository()
    repository.tasks = {
        "safe": {"task_id": "safe", "task_type": "embedding", "status": "failed", "retryable": True},
        "unsafe": {"task_id": "unsafe", "task_type": "bulk_import", "status": "failed", "retryable": False},
    }

    response = repository.list_tasks(_system_session(), {})

    assert [(item["task_id"], item["retryable"]) for item in response["items"]] == [
        ("safe", True),
        ("unsafe", False),
    ]

    with pytest.raises(Exception, match="not retryable"):
        repository.retry_task(_system_session(), "unsafe", {"idempotency_key": "unsafe-retry", "reason": "manual"})


def test_in_memory_task_retry_replays_only_for_same_task_and_actor() -> None:
    repository = InMemorySystemAdminRepository()
    repository.tasks = {
        "task-1": {"task_id": "task-1", "task_type": "embedding", "status": "failed", "retryable": True},
        "task-2": {"task_id": "task-2", "task_type": "embedding", "status": "failed", "retryable": True},
    }
    session = _system_session()
    payload = {"idempotency_key": "retry-shared", "reason": "manual"}

    first = repository.retry_task(session, "task-1", payload)
    second = repository.retry_task(session, "task-1", payload)

    assert second == first
    assert repository.tasks["task-1"]["retry_count"] == 1
    assert repository.tasks["task-1"]["retryable"] is False
    with pytest.raises(Exception, match="different task or system admin"):
        repository.retry_task(session, "task-2", payload)
    with pytest.raises(Exception, match="different task or system admin"):
        repository.retry_task(replace(session, user_id="other-system-admin"), "task-1", payload)


def test_in_memory_task_retry_same_key_is_concurrently_replayed_once() -> None:
    class SlowTask(dict[str, Any]):
        def __getitem__(self, key: str) -> Any:
            value = super().__getitem__(key)
            if key == "status":
                time.sleep(0.03)
            return value

    repository = InMemorySystemAdminRepository()
    repository.tasks = {
        "task-1": SlowTask(task_id="task-1", task_type="embedding", status="failed", retryable=True),
    }
    session = _system_session()
    payload = {"idempotency_key": "retry-concurrent", "reason": "manual"}
    start = threading.Barrier(2)

    def retry() -> dict[str, Any]:
        start.wait(timeout=3)
        return repository.retry_task(session, "task-1", payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(retry) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]

    assert results[0] == results[1]
    assert repository.tasks["task-1"]["retry_count"] == 1
    assert sum(item["action"] == "system_admin.task.retry" for item in repository.audit_logs) == 1


def test_in_memory_system_admin_audit_filters_actor_scope_action_sensitive_and_half_open_time() -> None:
    repository = InMemorySystemAdminRepository()
    repository.audit_logs = [
        {
            "audit_log_id": "audit-match",
            "actor_system_user_id": "sysadmin-001",
            "organization_id": "org-001",
            "store_id": "store-001",
            "action": "system_admin.release.publish",
            "object_type": "llm_release",
            "object_id": "release-1",
            "reason": "publish",
            "diff_summary": {"sensitive_access": True},
            "sensitive_access": True,
            "created_at": "2026-07-15T08:30:00Z",
        },
        {
            "audit_log_id": "audit-outside",
            "actor_system_user_id": "sysadmin-001",
            "organization_id": "org-001",
            "store_id": "store-001",
            "action": "system_admin.release.publish",
            "object_type": "llm_release",
            "object_id": "release-2",
            "reason": "publish",
            "diff_summary": {"sensitive_access": True},
            "sensitive_access": True,
            "created_at": "2026-07-15T09:00:00Z",
        },
    ]

    response = repository.list_audit_logs(_system_session(), {
        "actor_user_id": "sysadmin-001",
        "organization_id": "org-001",
        "store_id": "store-001",
        "action": "system_admin.release.publish",
        "sensitive_access": "true",
        "time_from": "2026-07-15T08:00:00Z",
        "time_to": "2026-07-15T09:00:00Z",
    })

    assert response["page_info"]["total"] == 1
    assert [item["audit_log_id"] for item in response["items"]] == ["audit-match"]


def test_in_memory_audit_list_excludes_its_own_read_audit_from_items_and_total() -> None:
    repository = InMemorySystemAdminRepository()
    repository.audit_logs = [{
        "audit_log_id": "audit-existing",
        "actor_system_user_id": "sysadmin-001",
        "organization_id": None,
        "store_id": None,
        "action": "system_admin.health.get",
        "object_type": "system_health",
        "object_id": "summary",
        "reason": None,
        "diff_summary": {},
        "sensitive_access": False,
        "created_at": "2026-07-15T08:30:00Z",
    }]

    response = repository.list_audit_logs(_system_session(), {})

    assert response["page_info"]["total"] == 1
    assert [item["audit_log_id"] for item in response["items"]] == ["audit-existing"]
    assert len(repository.audit_logs) == 2


def test_in_memory_audit_action_prefix_filters_before_pagination_and_total() -> None:
    repository = InMemorySystemAdminRepository()
    repository.audit_logs = [
        {
            "audit_log_id": f"audit-other-{index}", "actor_system_user_id": "sysadmin-001",
            "organization_id": None, "store_id": None, "action": "system_admin.health.get",
            "object_type": "health", "object_id": str(index), "reason": None,
            "diff_summary": {}, "sensitive_access": False, "created_at": "2026-07-15T08:30:00Z",
        }
        for index in range(101)
    ] + [{
        "audit_log_id": "audit-llm", "actor_system_user_id": "sysadmin-llm",
        "organization_id": None, "store_id": None, "action": "llm.config.publish",
        "object_type": "llm_config_version", "object_id": "version-1", "reason": "approved",
        "diff_summary": {"result": "running", "secret": "must-not-render"},
        "sensitive_access": False, "created_at": "2026-07-15T08:31:00Z",
    }]

    response = repository.list_audit_logs(_system_session(), {"action_prefix": "llm.", "page": 1, "page_size": 20})

    assert response["page_info"] == {"page": 1, "page_size": 20, "total": 1}
    assert response["items"][0]["actor_system_user_id"] == "sysadmin-llm"
    assert response["items"][0]["diff_summary"]["result"] == "running"


def test_system_admin_audit_rejects_wildcard_action_prefix() -> None:
    repository = InMemorySystemAdminRepository()
    with pytest.raises(HTTPException) as invalid:
        repository.list_audit_logs(_system_session(), {"action_prefix": "llm.%"})
    assert invalid.value.status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        "time_from=not-a-time",
        "time_from=2026-07-15T09%3A00%3A00Z&time_to=2026-07-15T08%3A00%3A00Z",
        "sensitive_access=maybe",
    ],
)
def test_system_admin_audit_rejects_invalid_filter_boundaries(query: str) -> None:
    response = TestClient(_test_app()).get(
        f"/v1/system-admin/audit-logs?{query}",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    assert response.status_code == 422


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
            ),
            [
                (
                    "release-db",
                    "org-db",
                    "version-db",
                    17,
                    "running",
                    "2026-07-14T07:30:00Z",
                    "2026-07-14T07:00:00Z",
                )
            ],
        ]
    )

    def fake_repo_init(self: PostgresSystemAdminRepository, database_url: str) -> None:
        self._database_url = database_url
        self._connect = lambda _url: connection

    monkeypatch.setattr(app_module, "system_admin_auth_service_for", lambda settings: InMemorySystemAdminAuthService(settings))
    monkeypatch.setattr(PostgresSystemAdminRepository, "__init__", fake_repo_init)

    client = TestClient(create_app(
        Settings(database_url="postgresql://example", environment="development"),
        llm_connection_tester=lambda _provider, _request: {"status": "failed", "latency_ms": 0, "error_code": "tester_unavailable"},
        llm_release_gate_checker=lambda _version, _run_id: {"status": "failed", "error_code": "release_gate_unavailable"},
    ))
    response = client.get(
        "/v1/system-admin/dashboard-summary",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    normalized_sql = " ".join(executed_sql.split())
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
        "recent_releases": [{
            "release_id": "release-db",
            "organization_id": "org-db",
            "config_version_id": "version-db",
            "version_number": 17,
            "status": "running",
            "published_at": "2026-07-14T07:30:00Z",
            "submitted_at": "2026-07-14T07:00:00Z",
        }],
        "recent_releases_status": "available",
        "recent_releases_error": None,
        "generated_at": "2026-07-14T08:00:00Z",
    }
    assert "FROM organization" in executed_sql
    assert "FROM store" in executed_sql
    assert "FROM product_price_snapshot" in executed_sql
    assert "FROM knowledge_entry" in executed_sql
    assert "FROM platform_account" in executed_sql
    assert "FROM external_api_token" in executed_sql
    assert "FROM decision_record" in executed_sql
    assert "FROM background_task" in executed_sql
    assert "FROM llm_release_record" in executed_sql
    assert "LIMIT 5" in executed_sql
    assert "NULLIF" in executed_sql
    assert "LIMIT %s" not in executed_sql
    assert "OFFSET %s" not in executed_sql
    assert executed_sql.count("INSERT INTO system_admin_audit_log") == 1
    assert "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'" in normalized_sql
    assert "created_at >=" in normalized_sql
    assert "created_at <" in normalized_sql
    assert "INTERVAL '1 day'" in normalized_sql
    assert "created_at <= CURRENT_TIMESTAMP" in normalized_sql
    assert normalized_sql.count("created_at >=") == 1
    assert normalized_sql.count("created_at < (") == 1


def test_postgres_dashboard_degrades_only_recent_releases_on_operational_failure(monkeypatch) -> None:
    class ReleaseFailureCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            if "FROM llm_release_record" in sql:
                raise OperationalError("release storage temporarily unavailable")
            super().execute(sql, params)

    class ReleaseFailureConnection(_FakeConnection):
        def cursor(self) -> ReleaseFailureCursor:
            return ReleaseFailureCursor(self)

    connection = ReleaseFailureConnection(fetch_rows=[(
        2, 3, 4, 0.5, 0.25, 0.0, 1, 2, 0, "2026-07-15T08:00:00Z",
    )])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    response = repository.dashboard_summary(_system_session())

    assert response["active_organizations"] == 2
    assert response["recent_releases"] == []
    assert response["recent_releases_status"] == "unavailable"
    assert response["recent_releases_error"] == "release_data_unavailable"


def test_postgres_dashboard_does_not_hide_unexpected_release_query_programming_errors() -> None:
    class BrokenReleaseCursor(_FakeCursor):
        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            if "FROM llm_release_record" in sql:
                raise ProgrammingError("invalid release query")
            super().execute(sql, params)

    class BrokenReleaseConnection(_FakeConnection):
        def cursor(self) -> BrokenReleaseCursor:
            return BrokenReleaseCursor(self)

    connection = BrokenReleaseConnection(fetch_rows=[(
        2, 3, 4, 0.5, 0.25, 0.0, 1, 2, 0, "2026-07-15T08:00:00Z",
    )])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    with pytest.raises(ProgrammingError, match="invalid release query"):
        repository.dashboard_summary(_system_session())


def test_postgres_system_admin_dashboard_summary_maps_zero_denominator_rates_to_none() -> None:
    connection = _FakeConnection(fetch_rows=[(0, 0, 0, None, None, None, 0, 0, 0, "2026-07-14T08:00:00Z"), []])
    repository = PostgresSystemAdminRepository.__new__(PostgresSystemAdminRepository)
    repository._database_url = "postgresql://example"
    repository._connect = lambda _url: connection

    response = repository.dashboard_summary(_system_session())

    assert response["auto_reply_rate"] is None
    assert response["handoff_rate"] is None
    assert response["error_rate"] is None


def test_postgres_system_admin_tasks_select_and_map_retryable() -> None:
    connection = _FakeConnection(fetch_rows=[(1,), [("task-db", "embedding", "failed", True, "org-db", "store-db", "in", None, "failed", 1, None, "2026-07-15T08:00:00Z")]])
    repository = PostgresSystemAdminRepository.__new__(PostgresSystemAdminRepository)
    repository._database_url = "postgresql://example"
    repository._connect = lambda _url: connection

    response = repository.list_tasks(_system_session(), {})

    assert response["items"][0]["retryable"] is True
    assert "task.retryable" in "\n".join(sql for sql, _params in connection.executed)


def test_postgres_system_admin_audit_applies_all_filters_to_count_and_page_queries() -> None:
    connection = _FakeConnection(fetch_rows=[(0,), []])
    repository = PostgresSystemAdminRepository.__new__(PostgresSystemAdminRepository)
    repository._database_url = "postgresql://example"
    repository._connect = lambda _url: connection

    repository.list_audit_logs(_system_session(), {
        "actor_user_id": "sysadmin-001",
        "organization_id": "org-db",
        "store_id": "store-db",
        "action": "system_admin.release.publish",
        "sensitive_access": "true",
        "time_from": "2026-07-15T08:00:00Z",
        "time_to": "2026-07-15T09:00:00Z",
    })

    select_sql = [sql for sql, _params in connection.executed if "FROM system_admin_audit_log audit" in sql]
    assert len(select_sql) == 2
    assert all("audit.action =" in sql for sql in select_sql)
    assert all("audit.created_at >=" in sql for sql in select_sql)
    assert all("audit.created_at <" in sql for sql in select_sql)


def test_postgres_system_admin_audit_parameterizes_action_prefix_for_count_and_page() -> None:
    connection = _FakeConnection(fetch_rows=[(0,), []])
    repository = PostgresSystemAdminRepository.__new__(PostgresSystemAdminRepository)
    repository._database_url = "postgresql://example"
    repository._connect = lambda _url: connection

    repository.list_audit_logs(_system_session(), {"action_prefix": "llm."})

    selects = [(sql, params) for sql, params in connection.executed if "FROM system_admin_audit_log audit" in sql]
    assert len(selects) == 2
    assert all("audit.action LIKE %s ESCAPE" in sql for sql, _ in selects)
    assert all("llm.%" in params for _, params in selects)


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

    client = TestClient(create_app(
        Settings(database_url="postgresql://example", environment="development"),
        llm_connection_tester=lambda _provider, _request: {"status": "failed", "latency_ms": 0, "error_code": "tester_unavailable"},
        llm_release_gate_checker=lambda _version, _run_id: {"status": "failed", "error_code": "release_gate_unavailable"},
    ))
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

    client = TestClient(create_app(
        Settings(database_url="postgresql://example", environment="development"),
        llm_connection_tester=lambda _provider, _request: {"status": "failed", "latency_ms": 0, "error_code": "tester_unavailable"},
        llm_release_gate_checker=lambda _version, _run_id: {"status": "failed", "error_code": "release_gate_unavailable"},
    ))
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
