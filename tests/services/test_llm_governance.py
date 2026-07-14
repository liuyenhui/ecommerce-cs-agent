from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import HTTPException

from ecommerce_cs_agent.services.admin_auth import SystemAdminSession
from ecommerce_cs_agent.services.llm_governance import (
    InMemoryLlmGovernanceRepository,
    PostgresLlmGovernanceRepository,
)


ORG_ID = "11111111-1111-1111-1111-111111111111"
PROVIDER_PAYLOAD = {
    "name": "primary",
    "provider_type": "openai_compatible",
    "base_url": "https://llm.example.test/v1",
    "secret_ref": {"namespace": "runtime", "name": "llm", "key": "api-key"},
    "reason": "configure provider",
    "idempotency_key": "provider-1",
}
REPLY_ROUTE = {
    "scenario": "reply_generation",
    "primary_provider_config_id": "provider-primary",
    "primary_model": "chat-pro",
    "fallback_provider_config_id": "provider-fallback",
    "fallback_model": "chat-lite",
    "enabled": True,
    "temperature": 0.2,
    "max_output_tokens": 1200,
    "timeout_seconds": 18,
    "max_retries": 2,
    "circuit_breaker_threshold": 5,
    "recovery_probe_seconds": 30,
}


def _session(role: str = "super_admin", *, expired: bool = False) -> SystemAdminSession:
    return SystemAdminSession(
        token="system-session",
        user_id="22222222-2222-2222-2222-222222222222",
        email="system@example.test",
        display_name="System Admin",
        role=role,
        expires_at=datetime.now(timezone.utc) + (-timedelta(minutes=1) if expired else timedelta(hours=1)),
    )


def _create_provider(service: InMemoryLlmGovernanceRepository, *, name: str, idem: str) -> dict[str, Any]:
    payload = dict(PROVIDER_PAYLOAD, name=name, idempotency_key=idem)
    return service.create_provider(_session(), payload)


def test_provider_response_uses_allowlist_and_never_contains_secret_value() -> None:
    service = InMemoryLlmGovernanceRepository()
    payload = dict(PROVIDER_PAYLOAD, secret_value="must-not-survive", authorization="Bearer private")

    provider = service.create_provider(_session(), payload)

    assert provider["secret_ref"] == {"namespace": "runtime", "name": "llm", "key": "api-key"}
    flattened = json.dumps({"provider": provider, "audit": service.audit_logs})
    assert "secret_value" not in flattened
    assert "must-not-survive" not in flattened
    assert "Bearer private" not in flattened


def test_all_writes_require_live_system_session_role_reason_and_idempotency_key() -> None:
    service = InMemoryLlmGovernanceRepository()
    with pytest.raises(HTTPException) as expired:
        service.create_provider(_session(expired=True), PROVIDER_PAYLOAD)
    assert expired.value.status_code == 401

    with pytest.raises(HTTPException) as denied:
        service.create_provider(_session("technical_support"), PROVIDER_PAYLOAD)
    assert denied.value.status_code == 403

    for missing in ("reason", "idempotency_key"):
        payload = dict(PROVIDER_PAYLOAD)
        payload.pop(missing)
        with pytest.raises(HTTPException) as invalid:
            service.create_provider(_session(), payload)
        assert invalid.value.status_code == 422


def test_idempotency_replays_same_request_and_rejects_different_payload() -> None:
    service = InMemoryLlmGovernanceRepository()
    first = service.create_provider(_session(), PROVIDER_PAYLOAD)
    assert service.create_provider(_session(), PROVIDER_PAYLOAD) == first

    with pytest.raises(HTTPException) as conflict:
        service.create_provider(_session(), dict(PROVIDER_PAYLOAD, base_url="https://other.example.test"))
    assert conflict.value.status_code == 409
    assert conflict.value.detail["error"]["code"] == "idempotency_conflict"


def test_provider_update_uses_expected_revision_and_audits() -> None:
    service = InMemoryLlmGovernanceRepository()
    provider = service.create_provider(_session(), PROVIDER_PAYLOAD)
    updated = service.update_provider(
        _session(),
        provider["provider_id"],
        {"enabled": False, "reason": "pause service", "idempotency_key": "provider-update-1"},
        expected_revision=1,
    )
    assert updated["revision"] == 2
    assert updated["status"] == "disabled"
    with pytest.raises(HTTPException) as stale:
        service.update_provider(
            _session(),
            provider["provider_id"],
            {"enabled": True, "reason": "stale", "idempotency_key": "provider-update-2"},
            expected_revision=1,
        )
    assert stale.value.status_code == 409
    assert any(log["action"] == "llm.provider.update" for log in service.audit_logs)


def test_connection_test_enforces_boundary_and_stores_only_redacted_metadata() -> None:
    service = InMemoryLlmGovernanceRepository(
        connection_tester=lambda _provider, _request: {
            "status": "failed",
            "latency_ms": 41,
            "error_code": "upstream_auth",
            "error_message": "Bearer abc secret-private request body customer text",
            "response": "private model output",
        }
    )
    provider = service.create_provider(_session(), PROVIDER_PAYLOAD)
    with pytest.raises(HTTPException):
        service.test_connection(
            _session("technical_support"), provider["provider_id"],
            {"timeout_seconds": 21, "max_tokens": 32, "reason": "diagnose", "idempotency_key": "test-bad"},
        )
    result = service.test_connection(
        _session("technical_support"), provider["provider_id"],
        {"timeout_seconds": 20, "max_tokens": 256, "reason": "diagnose", "idempotency_key": "test-1"},
    )
    assert set(result) == {"connection_test_id", "provider_config_id", "status", "latency_ms", "checked_at", "error_code", "redacted_error_message"}
    flattened = json.dumps({"result": result, "stored": service.connection_tests, "audit": service.audit_logs})
    assert "abc" not in flattened
    assert "secret-private" not in flattened
    assert "customer text" not in flattened
    assert "private model output" not in flattened


def test_draft_publish_and_rollback_preserve_immutable_history() -> None:
    service = InMemoryLlmGovernanceRepository()
    primary = _create_provider(service, name="primary", idem="p-primary")
    fallback = _create_provider(service, name="fallback", idem="p-fallback")
    route = dict(
        REPLY_ROUTE,
        primary_provider_config_id=primary["provider_id"],
        fallback_provider_config_id=fallback["provider_id"],
    )
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "description": "reply", "reason": "tune reply model", "idempotency_key": "draft-1"})
    changed = service.replace_routes(
        _session(), draft["version_id"], [route], expected_revision=1,
        payload={"reason": "set route", "idempotency_key": "routes-1"},
    )
    published = service.publish(
        _session(), draft["version_id"],
        {"reason": "eval passed", "idempotency_key": "pub-1", "expected_revision": changed["revision"]},
    )
    rolled_back = service.rollback(
        _session(), published["version_id"],
        {"reason": "provider regression", "idempotency_key": "rb-1"},
    )
    assert published["status"] == "running"
    assert service.versions[published["version_id"]]["status"] == "superseded"
    assert rolled_back["status"] == "running"
    assert rolled_back["version_id"] != published["version_id"]
    assert rolled_back["rollback_of_version_id"] == published["version_id"]
    assert rolled_back["routes"] == published["routes"]
    assert service.versions[published["version_id"]]["routes"] == published["routes"]


def test_route_replacement_rejects_duplicate_scenario_missing_primary_and_stale_revision() -> None:
    service = InMemoryLlmGovernanceRepository()
    provider = _create_provider(service, name="primary", idem="provider-route")
    route = dict(REPLY_ROUTE, primary_provider_config_id=provider["provider_id"], fallback_provider_config_id=None, fallback_model=None)
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "route-draft"})
    write = {"reason": "routes", "idempotency_key": "route-write"}
    with pytest.raises(HTTPException):
        service.replace_routes(_session(), draft["version_id"], [route, route], expected_revision=1, payload=write)
    with pytest.raises(HTTPException):
        service.replace_routes(_session(), draft["version_id"], [dict(route, primary_model="")], expected_revision=1, payload=dict(write, idempotency_key="missing-primary"))
    changed = service.replace_routes(_session(), draft["version_id"], [route], expected_revision=1, payload=write)
    assert changed["revision"] == 2
    with pytest.raises(HTTPException) as stale:
        service.replace_routes(_session(), draft["version_id"], [route], expected_revision=1, payload=dict(write, idempotency_key="route-stale"))
    assert stale.value.status_code == 409


def test_usage_filters_summary_rates_groups_trends_and_metadata_without_content() -> None:
    service = InMemoryLlmGovernanceRepository()
    now = datetime.now(timezone.utc)
    service.invocation_metrics.extend(
        [
            {"invocation_id": "i1", "occurred_at": now, "provider_config_id": "p1", "provider_name": "primary", "model": "chat-pro", "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": "s1", "route_role": "primary", "input_tokens": 10, "output_tokens": 5, "latency_ms": 100, "status": "succeeded", "error_code": None, "estimated_cost_micros": 200, "currency": "USD", "prompt": "private"},
            {"invocation_id": "i2", "occurred_at": now, "provider_config_id": "p1", "provider_name": "primary", "model": "chat-pro", "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": "s1", "route_role": "fallback", "input_tokens": 20, "output_tokens": 10, "latency_ms": 300, "status": "failed", "error_code": "timeout", "estimated_cost_micros": 400, "currency": "USD", "response": "private"},
        ]
    )
    filters = {"start_at": now - timedelta(minutes=1), "end_at": now + timedelta(minutes=1), "provider_config_id": "p1", "model": "chat-pro", "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": "s1"}
    summary = service.usage_summary(_session("security_auditor"), filters)
    assert summary == {"calls": 2, "input_tokens": 30, "output_tokens": 15, "total_tokens": 45, "estimated_cost_micros": 600, "p95_latency_ms": 300, "error_rate": 0.5, "fallback_rate": 0.5}
    assert service.usage_timeseries(_session(), filters)
    assert service.usage_breakdown(_session(), filters, "model")[0]["calls"] == 2
    flattened = json.dumps(service.list_invocations(_session(), filters))
    assert "private" not in flattened
    assert "prompt" not in flattened
    assert "response" not in flattened


def test_zero_usage_has_nullable_rates_and_empty_collections() -> None:
    service = InMemoryLlmGovernanceRepository()
    assert service.usage_summary(_session(), {}) == {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated_cost_micros": 0, "p95_latency_ms": None, "error_rate": None, "fallback_rate": None}
    assert service.usage_timeseries(_session(), {}) == []
    assert service.usage_breakdown(_session(), {}, "provider") == []
    assert service.list_invocations(_session(), {}) == []


def test_postgres_queries_are_parameterized_transactional_and_never_select_content() -> None:
    connection = _FakeConnection(fetch_rows=[None])
    service = PostgresLlmGovernanceRepository("postgresql://example")
    service._connect = lambda _url: connection
    with pytest.raises(HTTPException):
        service.update_provider(
            _session(), "33333333-3333-3333-3333-333333333333",
            {"name": "new", "reason": "rename", "idempotency_key": "pg-update"}, expected_revision=9,
        )
    sql = "\n".join(statement for statement, _params in connection.executed).lower()
    assert "where id = %s" in sql
    assert "revision = %s" in sql
    assert "secret_value" not in sql
    assert "prompt" not in sql and "message" not in sql and "response" not in sql
    assert connection.rollbacks == 1


class _FakeConnection:
    def __init__(self, fetch_rows: list[Any] | None = None) -> None:
        self.fetch_rows = fetch_rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


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
        return self.connection.fetch_rows.pop(0) if self.connection.fetch_rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        row = self.connection.fetch_rows.pop(0) if self.connection.fetch_rows else []
        return row if isinstance(row, list) else [row]
