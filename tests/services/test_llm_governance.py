from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql

from ecommerce_cs_agent.db.migrations import load_migrations
from ecommerce_cs_agent.services.admin_auth import SystemAdminSession
from ecommerce_cs_agent.services.llm_governance import (
    InMemoryLlmGovernanceRepository,
    PostgresLlmGovernanceRepository,
    _fingerprint,
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


def _all_routes(primary_id: str, fallback_id: str | None = None) -> list[dict[str, Any]]:
    return [
        dict(REPLY_ROUTE, scenario=scenario, primary_provider_config_id=primary_id,
             fallback_provider_config_id=fallback_id,
             fallback_model="chat-lite" if fallback_id else None)
        for scenario in (
            "reply_generation", "knowledge_extraction", "blind_test_question_generation"
        )
    ]


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


def _release(
    service: InMemoryLlmGovernanceRepository,
    routes: list[dict[str, Any]],
    *,
    suffix: str,
) -> dict[str, Any]:
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "draft", "idempotency_key": f"draft-{suffix}"})
    changed = service.replace_routes(_session(), draft["version_id"], routes, expected_revision=1, payload={"reason": "routes", "idempotency_key": f"routes-{suffix}"})
    provider_ids = {route["primary_provider_config_id"] for route in routes} | {route["fallback_provider_config_id"] for route in routes if route.get("fallback_provider_config_id")}
    for index, provider_id in enumerate(provider_ids):
        service.test_connection(_session("technical_support"), provider_id, {"config_version_id": draft["version_id"], "reason": "validate", "idempotency_key": f"connection-{suffix}-{index}"})
    validated = service.validate_draft(_session(), draft["version_id"], {"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": f"validate-{suffix}"})
    pending = service.submit_publish(_session(), draft["version_id"], {"expected_revision": validated["revision"], "evaluation_run_id": f"eval-{suffix}", "reason": "submit", "idempotency_key": f"submit-{suffix}"})
    return service.publish(_session(), draft["version_id"], {"expected_revision": pending["revision"], "reason": "publish", "idempotency_key": f"publish-{suffix}"})


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
            "error_code": "Bearer leak-token-927 " + "s" + "k-redacted secret-private",
            "error_message": "request body customer text",
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
    assert set(result) == {"connection_test_id", "provider_config_id", "config_version_id", "status", "latency_ms", "checked_at", "error_code", "redacted_error_message"}
    assert result["error_code"] == "upstream_error"
    assert service.providers[provider["provider_id"]]["revision"] == 2
    flattened = json.dumps({"result": result, "stored": service.connection_tests, "audit": service.audit_logs})
    assert "leak-token-927" not in flattened
    assert "secret-private" not in flattened
    assert "customer text" not in flattened
    assert "private model output" not in flattened


def test_draft_publish_and_rollback_preserve_immutable_history() -> None:
    service = InMemoryLlmGovernanceRepository(release_gate_checker=lambda _version, _run: {"status": "passed"})
    primary = _create_provider(service, name="primary", idem="p-primary")
    fallback = _create_provider(service, name="fallback", idem="p-fallback")
    routes = _all_routes(primary["provider_id"], fallback["provider_id"])
    published = _release(service, routes, suffix="one")
    second = _release(service, routes, suffix="two")
    rolled_back = service.rollback(
        _session(), published["version_id"],
        {"reason": "provider regression", "idempotency_key": "rb-1"},
    )
    assert published["status"] == "running"
    assert service.versions[published["version_id"]]["status"] == "superseded"
    assert second["status"] == "running"
    assert rolled_back["status"] == "running"
    assert rolled_back["version_id"] != published["version_id"]
    assert rolled_back["rollback_of_version_id"] == published["version_id"]
    assert rolled_back["routes"] == published["routes"]
    assert service.versions[published["version_id"]]["routes"] == published["routes"]


def test_validate_submit_and_publish_are_explicit_and_gate_failure_preserves_state() -> None:
    service = InMemoryLlmGovernanceRepository()
    provider = _create_provider(service, name="explicit", idem="explicit-provider")
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "explicit-draft"})
    changed = service.replace_routes(_session(), draft["version_id"], _all_routes(provider["provider_id"]), expected_revision=1, payload={"reason": "routes", "idempotency_key": "explicit-routes"})
    service.test_connection(_session("technical_support"), provider["provider_id"], {"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "explicit-test"})
    validated = service.validate_draft(_session(), draft["version_id"], {"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "explicit-validate"})
    assert (validated["status"], validated["revision"]) == ("validated", 3)
    with pytest.raises(HTTPException) as failed_gate:
        service.submit_publish(_session(), draft["version_id"], {"expected_revision": 3, "evaluation_run_id": "eval-explicit", "reason": "submit", "idempotency_key": "explicit-submit-fail"})
    assert failed_gate.value.detail["error"]["code"] == "release_gate_failed"
    assert service.get_version(_session(), draft["version_id"])["status"] == "validated"
    service._release_gate_checker = lambda _version, _run: {"status": "passed"}
    pending = service.submit_publish(_session(), draft["version_id"], {"expected_revision": 3, "evaluation_run_id": "eval-explicit", "reason": "submit", "idempotency_key": "explicit-submit"})
    assert (pending["status"], pending["revision"]) == ("pending_publish", 4)
    running = service.publish(_session(), draft["version_id"], {"expected_revision": 4, "reason": "publish", "idempotency_key": "explicit-publish"})
    assert (running["status"], running["revision"]) == ("running", 5)


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
    with pytest.raises(HTTPException) as incomplete:
        service.validate_draft(_session(), draft["version_id"], {"expected_revision": 2, "reason": "validate", "idempotency_key": "validate-incomplete"})
    assert incomplete.value.detail["error"]["code"] == "llm_scenarios_incomplete"
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
    assert summary == {"calls": 2, "input_tokens": 30, "output_tokens": 15, "total_tokens": 45, "estimated_cost_micros": 600, "cost_by_currency": {"USD": 600}, "p95_latency_ms": 300, "error_rate": 0.5, "fallback_rate": 0.5}
    assert service.usage_timeseries(_session(), filters)
    assert service.usage_breakdown(_session(), filters, "model")[0]["calls"] == 2
    flattened = json.dumps(service.list_invocations(_session(), filters))
    assert "private" not in flattened
    assert "prompt" not in flattened
    assert "response" not in flattened


def test_zero_usage_has_nullable_rates_and_empty_collections() -> None:
    service = InMemoryLlmGovernanceRepository()
    assert service.usage_summary(_session(), {}) == {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated_cost_micros": 0, "cost_by_currency": {}, "p95_latency_ms": None, "error_rate": None, "fallback_rate": None}
    assert service.usage_timeseries(_session(), {}) == []
    assert service.usage_breakdown(_session(), {}, "provider") == []
    assert service.list_invocations(_session(), {}) == []


def test_usage_never_mixes_currency_and_details_are_sorted_and_limited() -> None:
    service = InMemoryLlmGovernanceRepository()
    now = datetime.now(timezone.utc)
    service.invocation_metrics.extend([
        {"invocation_id": "old", "occurred_at": now - timedelta(seconds=1), "provider_config_id": "p", "provider_name": "p", "model": "m", "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": "s", "route_role": "primary", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1, "status": "succeeded", "error_code": None, "estimated_cost_micros": 100, "currency": "USD"},
        {"invocation_id": "new", "occurred_at": now, "provider_config_id": "p", "provider_name": "p", "model": "m", "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": "s", "route_role": "primary", "input_tokens": 1, "output_tokens": 1, "latency_ms": 1, "status": "succeeded", "error_code": None, "estimated_cost_micros": 700, "currency": "CNY"},
    ])
    summary = service.usage_summary(_session(), {})
    assert summary["estimated_cost_micros"] is None
    assert summary["cost_by_currency"] == {"USD": 100, "CNY": 700}
    assert {row["currency"] for row in service.usage_timeseries(_session(), {})} == {"USD", "CNY"}
    assert {row["currency"] for row in service.usage_breakdown(_session(), {}, "model")} == {"USD", "CNY"}
    assert service.usage_summary(_session(), {"currency": "CNY"})["estimated_cost_micros"] == 700
    assert [row["invocation_id"] for row in service.list_invocations(_session(), {"limit": 1})] == ["new"]


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
    assert "prompt" not in sql and "customer_message" not in sql and "model_response" not in sql
    assert connection.rollbacks == 1


def test_postgres_idempotency_returns_stable_snapshot_and_rejects_conflict() -> None:
    provider_id = "33333333-3333-3333-3333-333333333333"
    request = {"provider_id": provider_id, "expected_revision": 1, "changes": {"name": "new"}}
    snapshot = {"provider_id": provider_id, "name": "old", "revision": 1, "secret_ref": {"namespace": "runtime", "name": "llm", "key": "api-key"}}
    replay_connection = _FakeConnection(fetch_rows=[(provider_id, _fingerprint(request), snapshot)])
    replay_service = PostgresLlmGovernanceRepository("postgresql://example")
    replay_service._connect = lambda _url: replay_connection
    assert replay_service.update_provider(_session(), provider_id, {"name": "new", "reason": "rename", "idempotency_key": "stable"}, expected_revision=1) == snapshot
    assert replay_connection.commits == 1

    conflict_connection = _FakeConnection(fetch_rows=[(provider_id, "different-request-hash", snapshot)])
    conflict_service = PostgresLlmGovernanceRepository("postgresql://example")
    conflict_service._connect = lambda _url: conflict_connection
    with pytest.raises(HTTPException) as conflict:
        conflict_service.update_provider(_session(), provider_id, {"name": "new", "reason": "rename", "idempotency_key": "stable"}, expected_revision=1)
    assert conflict.value.status_code == 409
    assert conflict_connection.rollbacks == 1


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


def test_postgres_service_full_lifecycle_when_database_is_available() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("set TEST_DATABASE_URL or DATABASE_URL to run PostgreSQL service integration")
    schema_name = f"llm_service_test_{__import__('uuid').uuid4().hex}"
    setup = psycopg.connect(database_url)
    try:
        with setup.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema_name)))
            for migration in load_migrations(Path("migrations")):
                cur.execute(migration.sql)
            cur.execute("INSERT INTO system_admin_user (email,password_hash,display_name,role) VALUES ('llm-service@example.invalid','not-real','LLM Service','super_admin') RETURNING id")
            user_id = str(cur.fetchone()[0])
            cur.execute("INSERT INTO organization (name) VALUES ('LLM Service Integration') RETURNING id")
            organization_id = str(cur.fetchone()[0])
        setup.commit()
        scoped_url = psycopg.conninfo.make_conninfo(database_url, options=f"-c search_path={schema_name},public")
        session = SystemAdminSession(token="integration", user_id=user_id, email="llm-service@example.invalid", display_name="LLM Service", role="super_admin", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        service = PostgresLlmGovernanceRepository(scoped_url, connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 2}, release_gate_checker=lambda _version, _run: {"status": "passed"})
        provider = service.create_provider(session, dict(PROVIDER_PAYLOAD, idempotency_key="integration-provider"))
        assert set(provider["secret_ref"]) == {"namespace", "name", "key"}
        draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-draft"})
        changed = service.replace_routes(session, draft["version_id"], _all_routes(provider["provider_id"]), expected_revision=1, payload={"reason": "integration", "idempotency_key": "integration-routes"})
        tested = service.test_connection(session, provider["provider_id"], {"config_version_id": draft["version_id"], "reason": "integration", "idempotency_key": "integration-test"})
        assert tested["status"] == "passed"
        validated = service.validate_draft(session, draft["version_id"], {"expected_revision": changed["revision"], "reason": "integration", "idempotency_key": "integration-validate"})
        pending = service.submit_publish(session, draft["version_id"], {"expected_revision": validated["revision"], "evaluation_run_id": "integration-eval", "reason": "integration", "idempotency_key": "integration-submit"})
        running = service.publish(session, draft["version_id"], {"expected_revision": pending["revision"], "reason": "integration", "idempotency_key": "integration-publish"})
        assert running["status"] == "running"
        second_draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-draft-two"})
        second_changed = service.replace_routes(session, second_draft["version_id"], _all_routes(provider["provider_id"]), expected_revision=1, payload={"reason": "integration", "idempotency_key": "integration-routes-two"})
        service.test_connection(session, provider["provider_id"], {"config_version_id": second_draft["version_id"], "reason": "integration", "idempotency_key": "integration-test-two"})
        second_validated = service.validate_draft(session, second_draft["version_id"], {"expected_revision": second_changed["revision"], "reason": "integration", "idempotency_key": "integration-validate-two"})
        second_pending = service.submit_publish(session, second_draft["version_id"], {"expected_revision": second_validated["revision"], "evaluation_run_id": "integration-eval-two", "reason": "integration", "idempotency_key": "integration-submit-two"})
        service.update_provider(session, provider["provider_id"], {"enabled": False, "reason": "integration", "idempotency_key": "integration-disable"}, expected_revision=3)
        with pytest.raises(HTTPException):
            service.publish(session, second_draft["version_id"], {"expected_revision": second_pending["revision"], "reason": "integration", "idempotency_key": "integration-publish-two"})
        assert service.get_version(session, running["version_id"])["status"] == "running"
        with psycopg.connect(scoped_url) as metrics_connection:
            with metrics_connection.cursor() as cur:
                cur.execute("SELECT id FROM llm_scenario_route WHERE config_version_id=%s ORDER BY scenario LIMIT 1", (running["version_id"],))
                route_id = cur.fetchone()[0]
                cur.execute("INSERT INTO llm_invocation_metric (scenario_route_id,route_role,organization_id,input_tokens,output_tokens,latency_ms,status,estimated_cost_micros,currency) VALUES (%s,'primary',%s,1,2,4,'succeeded',10,'USD'),(%s,'primary',%s,1,2,4,'succeeded',20,'CNY')", (route_id, organization_id, route_id, organization_id))
        usage = service.usage_summary(session, {"organization_id": organization_id})
        assert usage["estimated_cost_micros"] is None
        assert usage["cost_by_currency"] == {"CNY": 20, "USD": 10}
        assert service.usage_summary(session, {"organization_id": organization_id, "currency": "USD"})["estimated_cost_micros"] == 10
        assert {row["currency"] for row in service.usage_timeseries(session, {"organization_id": organization_id})} == {"CNY", "USD"}
        assert {row["currency"] for row in service.usage_breakdown(session, {"organization_id": organization_id}, "model")} == {"CNY", "USD"}
        assert len(service.list_invocations(session, {"organization_id": organization_id, "currency": "CNY", "limit": 1})) == 1
        assert len(service.list_providers(session)) == 1
        service.update_provider(session, provider["provider_id"], {"enabled": True, "reason": "integration", "idempotency_key": "integration-enable"}, expected_revision=4)
        second_running = service.publish(session, second_draft["version_id"], {"expected_revision": second_pending["revision"], "reason": "integration", "idempotency_key": "integration-publish-two-success"})
        assert second_running["status"] == "running"
        rolled_back = service.rollback(session, running["version_id"], {"reason": "integration", "idempotency_key": "integration-rollback"})
        assert rolled_back["status"] == "running"
        assert rolled_back["rollback_of_version_id"] == running["version_id"]
    finally:
        setup.close()
        with psycopg.connect(database_url, autocommit=True) as cleanup:
            with cleanup.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
