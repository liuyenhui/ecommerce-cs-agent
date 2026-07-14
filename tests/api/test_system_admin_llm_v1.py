from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ecommerce_cs_agent.api import app as app_module
from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import InMemorySystemAdminAuthService, SystemAdminSession
from ecommerce_cs_agent.services.llm_governance import InMemoryLlmGovernanceRepository


ORG_ID = "11111111-1111-1111-1111-111111111111"
PROVIDER_A_ID = "22222222-2222-2222-2222-222222222222"
PROVIDER_B_ID = "33333333-3333-3333-3333-333333333333"
STORE_A_ID = "44444444-4444-4444-4444-444444444444"
STORE_B_ID = "55555555-5555-5555-5555-555555555555"
SYSTEM_HEADERS = {"Cookie": "agent_system_admin_session=test-system-session"}
PROVIDER = {
    "name": "primary",
    "provider_type": "openai_compatible",
    "base_url": "https://llm.example.test/v1",
    "secret_ref": {"namespace": "runtime", "name": "llm-provider", "key": "api-key"},
    "reason": "configure primary provider",
    "idempotency_key": "provider-1",
}


def _routes(provider_id: str) -> list[dict[str, Any]]:
    return [
        {
            "scenario": scenario,
            "primary_provider_config_id": provider_id,
            "primary_model": "chat-pro",
            "fallback_provider_config_id": None,
            "fallback_model": None,
            "enabled": True,
            "temperature": 0.2,
            "max_output_tokens": 1200,
            "timeout_seconds": 18,
            "max_retries": 2,
            "circuit_breaker_threshold": 5,
            "recovery_probe_seconds": 30,
        }
        for scenario in (
            "reply_generation",
            "knowledge_extraction",
            "blind_test_question_generation",
        )
    ]


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "super_admin",
    repository: InMemoryLlmGovernanceRepository | None = None,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, InMemoryLlmGovernanceRepository]:
    settings = Settings(environment="test", database_url=None)
    auth = InMemorySystemAdminAuthService(settings)
    auth.sessions[settings.system_admin_session] = SystemAdminSession(
        token=settings.system_admin_session,
        user_id="system-user-1",
        email="system@example.test",
        display_name="System User",
        role=role,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(app_module, "system_admin_auth_service_for", lambda _settings: auth)
    service = repository or InMemoryLlmGovernanceRepository(
        connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 12},
        release_gate_checker=lambda _version, _run_id: {"status": "passed"},
    )
    app = create_app(settings, llm_governance_repository=service)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), service


def test_provider_create_list_update_redacts_secret_and_uses_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _service = _client(monkeypatch)

    created = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER)
    replayed = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER)
    conflicting = client.post(
        "/v1/system-admin/llm/providers",
        headers=SYSTEM_HEADERS,
        json={**PROVIDER, "name": "different-name"},
    )
    listed = client.get("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS)
    updated = client.patch(
        f"/v1/system-admin/llm/providers/{created.json()['provider_id']}",
        headers=SYSTEM_HEADERS,
        json={"name": "primary-renamed", "expected_revision": 1, "reason": "clarify name", "idempotency_key": "provider-update-1"},
    )
    stale = client.patch(
        f"/v1/system-admin/llm/providers/{created.json()['provider_id']}",
        headers=SYSTEM_HEADERS,
        json={"enabled": False, "expected_revision": 1, "reason": "stale update", "idempotency_key": "provider-update-2"},
    )

    assert created.status_code == 201
    assert replayed.status_code == 201
    assert replayed.json() == created.json()
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "idempotency_conflict"
    assert listed.status_code == 200
    assert listed.json()["items"][0]["secret_ref"] == PROVIDER["secret_ref"]
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_revision"
    flattened = json.dumps({"created": created.json(), "listed": listed.json(), "updated": updated.json()})
    assert "secret_value" not in flattened
    assert "Authorization" not in flattened


@pytest.mark.parametrize("sensitive_field", ["secret_value", "authorization", "prompt"])
def test_provider_request_rejects_sensitive_or_unknown_fields(monkeypatch: pytest.MonkeyPatch, sensitive_field: str) -> None:
    client, _service = _client(monkeypatch)

    response = client.post(
        "/v1/system-admin/llm/providers",
        headers=SYSTEM_HEADERS,
        json={**PROVIDER, sensitive_field: "must-not-enter"},
    )

    assert response.status_code == 422
    assert "must-not-enter" not in response.text


def test_write_request_types_are_not_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _service = _client(monkeypatch)
    provider = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()

    response = client.patch(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}",
        headers=SYSTEM_HEADERS,
        json={"enabled": "false", "expected_revision": "1", "reason": "invalid types", "idempotency_key": "invalid-types"},
    )

    assert response.status_code == 422


def test_customer_session_and_external_token_cannot_access_llm_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _service = _client(monkeypatch)

    customer = client.get(
        "/v1/system-admin/llm/providers",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )
    external = client.get(
        "/v1/system-admin/llm/providers",
        headers={"Authorization": "Bearer test-agent-token"},
    )

    assert customer.status_code == 403
    assert external.status_code == 403


def test_technical_support_can_only_run_draft_connection_test(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = InMemoryLlmGovernanceRepository(
        connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 9}
    )
    admin, _ = _client(monkeypatch, repository=repository)
    provider = admin.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()
    draft = admin.post(
        "/v1/system-admin/llm/config-versions/drafts",
        headers=SYSTEM_HEADERS,
        json={"organization_id": ORG_ID, "reason": "prepare draft", "idempotency_key": "draft-support"},
    ).json()
    support, _ = _client(monkeypatch, role="technical_support", repository=repository)

    allowed = support.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"config_version_id": draft["version_id"], "timeout_seconds": 10, "max_tokens": 32, "reason": "diagnose", "idempotency_key": "support-test"},
    )
    denied = support.post(
        "/v1/system-admin/llm/providers",
        headers=SYSTEM_HEADERS,
        json={**PROVIDER, "name": "denied", "idempotency_key": "support-provider"},
    )
    missing_draft = support.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"reason": "diagnose", "idempotency_key": "support-test-missing"},
    )

    assert allowed.status_code == 202
    assert allowed.json()["status"] == "passed"
    assert denied.status_code == 403
    assert missing_draft.status_code == 422


def test_draft_routes_validate_submit_publish_and_rollback_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _service = _client(monkeypatch, role="release_admin")
    provider = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()
    draft = client.post(
        "/v1/system-admin/llm/config-versions/drafts",
        headers=SYSTEM_HEADERS,
        json={"organization_id": ORG_ID, "description": "customer reply tuning", "reason": "prepare model config", "idempotency_key": "draft-1"},
    )
    changed = client.put(
        f"/v1/system-admin/llm/config-versions/{draft.json()['version_id']}/routes",
        headers=SYSTEM_HEADERS,
        json={"routes": _routes(provider["provider_id"]), "expected_revision": 1, "reason": "configure scenarios", "idempotency_key": "routes-1"},
    )
    tested = client.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"config_version_id": draft.json()["version_id"], "reason": "verify provider", "idempotency_key": "connection-1"},
    )
    validated = client.post(
        f"/v1/system-admin/llm/config-versions/{draft.json()['version_id']}/validate",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": changed.json()["revision"], "reason": "validation complete", "idempotency_key": "validate-1"},
    )
    submitted = client.post(
        f"/v1/system-admin/llm/config-versions/{draft.json()['version_id']}/submit-publish",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": validated.json()["revision"], "evaluation_run_id": "eval-2026-07-14", "reason": "evaluation passed", "idempotency_key": "submit-1"},
    )
    published = client.post(
        f"/v1/system-admin/llm/config-versions/{draft.json()['version_id']}/publish",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": submitted.json()["revision"], "reason": "release approved", "idempotency_key": "publish-1"},
    )
    fetched = client.get(
        f"/v1/system-admin/llm/config-versions/{draft.json()['version_id']}",
        headers=SYSTEM_HEADERS,
    )
    versions = client.get(
        f"/v1/system-admin/llm/config-versions?organization_id={ORG_ID}",
        headers=SYSTEM_HEADERS,
    )
    rolled_back = client.post(
        f"/v1/system-admin/llm/config-versions/{draft.json()['version_id']}/rollback",
        headers=SYSTEM_HEADERS,
        json={"reason": "provider regression", "idempotency_key": "rollback-1"},
    )

    assert draft.status_code == 201
    assert changed.status_code == 200
    assert tested.status_code == 202
    assert validated.json()["status"] == "validated"
    assert submitted.json()["status"] == "pending_publish"
    assert published.json()["status"] == "running"
    assert fetched.status_code == 200
    assert str(UUID(fetched.json()["release_record"]["release_record_id"])) == fetched.json()["release_record"]["release_record_id"]
    assert fetched.json()["evaluation"] == {"evaluation_run_id": "eval-2026-07-14"}
    assert versions.json()["items"][0]["version_id"] == draft.json()["version_id"]
    assert rolled_back.status_code == 200
    assert rolled_back.json()["status"] == "running"
    assert rolled_back.json()["rollback_of_version_id"] == draft.json()["version_id"]


def test_incomplete_routes_stale_revision_and_release_gate_have_exact_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = InMemoryLlmGovernanceRepository(
        connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 4},
        release_gate_checker=lambda _version, _run_id: {"status": "failed", "error_code": "red_line_failed"},
    )
    client, _service = _client(monkeypatch, repository=repository)
    provider = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()
    draft = client.post(
        "/v1/system-admin/llm/config-versions/drafts",
        headers=SYSTEM_HEADERS,
        json={"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "draft-conflicts"},
    ).json()
    changed = client.put(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/routes",
        headers=SYSTEM_HEADERS,
        json={"routes": _routes(provider["provider_id"]), "expected_revision": 1, "reason": "routes", "idempotency_key": "routes-conflicts"},
    ).json()
    stale = client.put(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/routes",
        headers=SYSTEM_HEADERS,
        json={"routes": _routes(provider["provider_id"]), "expected_revision": 1, "reason": "stale", "idempotency_key": "routes-stale"},
    )
    client.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "connection-conflicts"},
    )
    validated = client.post(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/validate",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "validate-conflicts"},
    ).json()
    gate = client.post(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/submit-publish",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": validated["revision"], "evaluation_run_id": "eval-failed", "reason": "submit", "idempotency_key": "submit-conflicts"},
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_revision"
    assert gate.status_code == 409
    assert gate.json()["error"]["code"] == "release_gate_failed"


def test_validate_rejects_incomplete_required_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _service = _client(monkeypatch)
    provider = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()
    draft = client.post(
        "/v1/system-admin/llm/config-versions/drafts",
        headers=SYSTEM_HEADERS,
        json={"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "incomplete-draft"},
    ).json()
    changed = client.put(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/routes",
        headers=SYSTEM_HEADERS,
        json={"routes": _routes(provider["provider_id"])[:1], "expected_revision": 1, "reason": "one route", "idempotency_key": "incomplete-routes"},
    ).json()
    client.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "incomplete-test"},
    )

    response = client.post(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/validate",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "incomplete-validate"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "llm_scenarios_incomplete"


def test_usage_endpoints_return_empty_and_mixed_currency_real_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    client, repository = _client(monkeypatch)
    empty = client.get(
        "/v1/system-admin/llm/usage/summary?start_at=2026-07-14T00:00:00Z&end_at=2026-07-15T00:00:00Z",
        headers=SYSTEM_HEADERS,
    )
    repository.invocation_metrics.extend(
        [
            {
                "invocation_id": "66666666-6666-6666-6666-666666666666", "occurred_at": "2026-07-14T08:00:00+00:00",
                "provider_config_id": PROVIDER_A_ID, "provider_name": "primary", "model": "chat-pro",
                "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": STORE_A_ID,
                "route_role": "primary", "input_tokens": 100, "output_tokens": 20, "latency_ms": 100,
                "status": "succeeded", "error_code": None, "estimated_cost_micros": 2500, "currency": "USD",
            },
            {
                "invocation_id": "77777777-7777-7777-7777-777777777777", "occurred_at": "2026-07-14T09:00:00+00:00",
                "provider_config_id": PROVIDER_B_ID, "provider_name": "fallback", "model": "chat-lite",
                "scenario": "reply_generation", "organization_id": ORG_ID, "store_id": STORE_B_ID,
                "route_role": "fallback", "input_tokens": 40, "output_tokens": 10, "latency_ms": 300,
                "status": "failed", "error_code": "timeout", "estimated_cost_micros": 900, "currency": "CNY",
            },
        ]
    )
    query = f"start_at=2026-07-14T00:00:00Z&end_at=2026-07-15T00:00:00Z&scenario=reply_generation&organization_id={ORG_ID}"
    summary = client.get(f"/v1/system-admin/llm/usage/summary?{query}", headers=SYSTEM_HEADERS)
    timeseries = client.get(f"/v1/system-admin/llm/usage/timeseries?{query}&currency=USD", headers=SYSTEM_HEADERS)
    breakdown = client.get(f"/v1/system-admin/llm/usage/breakdown?{query}&group_by=provider", headers=SYSTEM_HEADERS)
    invocations = client.get(
        f"/v1/system-admin/llm/usage/invocations?{query}&provider_config_id={PROVIDER_B_ID}&model=chat-lite&store_id={STORE_B_ID}&currency=CNY&limit=1",
        headers=SYSTEM_HEADERS,
    )

    assert empty.status_code == 200
    assert empty.json()["calls"] == 0
    assert empty.json()["estimated_cost_micros"] == 0
    assert empty.json()["cost_by_currency"] == {}
    assert summary.status_code == 200
    assert summary.json()["calls"] == 2
    assert summary.json()["estimated_cost_micros"] is None
    assert summary.json()["cost_by_currency"] == {"CNY": 900, "USD": 2500}
    assert timeseries.json()["items"][0]["currency"] == "USD"
    assert {item["key"] for item in breakdown.json()["items"]} == {"primary", "fallback"}
    assert invocations.json()["items"][0]["invocation_id"] == "77777777-7777-7777-7777-777777777777"
    assert invocations.json()["page_info"] == {"limit": 1, "has_more": False, "next_cursor": None}
    assert "prompt" not in invocations.text.lower()


def test_config_version_and_invocation_cursor_pages_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, repository = _client(monkeypatch)
    for index in range(3):
        response = client.post(
            "/v1/system-admin/llm/config-versions/drafts",
            headers=SYSTEM_HEADERS,
            json={"organization_id": ORG_ID, "reason": "page", "idempotency_key": f"page-{index}"},
        )
        assert response.status_code == 201

    first = client.get(f"/v1/system-admin/llm/config-versions?organization_id={ORG_ID}&limit=2", headers=SYSTEM_HEADERS)
    second = client.get(
        f"/v1/system-admin/llm/config-versions?organization_id={ORG_ID}&limit=2&cursor={first.json()['page_info']['next_cursor']}",
        headers=SYSTEM_HEADERS,
    )
    version_ids = [item["version_id"] for page in (first, second) for item in page.json()["items"]]
    assert len(version_ids) == len(set(version_ids)) == 3
    assert first.json()["page_info"]["has_more"] is True
    assert second.json()["page_info"]["has_more"] is False
    invalid_version_cursor = client.get(
        f"/v1/system-admin/llm/config-versions?organization_id={ORG_ID}&cursor=invalid",
        headers=SYSTEM_HEADERS,
    )
    assert invalid_version_cursor.status_code == 422

    for index in range(3):
        repository.invocation_metrics.append(
            {
                "invocation_id": str(UUID(int=100 + index)),
                "occurred_at": "2026-07-14T09:00:00+00:00",
                "provider_config_id": PROVIDER_A_ID,
                "provider_name": "primary",
                "model": "chat-pro",
                "scenario": "reply_generation",
                "organization_id": ORG_ID,
                "store_id": STORE_A_ID,
                "route_role": "primary",
                "input_tokens": 1,
                "output_tokens": 1,
                "latency_ms": 1,
                "status": "succeeded",
                "error_code": None,
                "estimated_cost_micros": 1,
                "currency": "USD",
            }
        )
    inv_first = client.get(f"/v1/system-admin/llm/usage/invocations?organization_id={ORG_ID}&limit=2", headers=SYSTEM_HEADERS)
    inv_second = client.get(
        f"/v1/system-admin/llm/usage/invocations?organization_id={ORG_ID}&limit=2&cursor={inv_first.json()['page_info']['next_cursor']}",
        headers=SYSTEM_HEADERS,
    )
    invocation_ids = [item["invocation_id"] for page in (inv_first, inv_second) for item in page.json()["items"]]
    assert len(invocation_ids) == len(set(invocation_ids)) == 3


@pytest.mark.parametrize(
    "query",
    [
        "start_at=1784016000",
        "start_at=2026-07-14T00:00:00",
        "start_at=2026-07-14%2000:00:00Z",
        "provider_config_id=provider-not-a-uuid",
        "cursor=not-a-cursor",
    ],
)
def test_usage_query_rejects_noncanonical_values(monkeypatch: pytest.MonkeyPatch, query: str) -> None:
    client, _repository = _client(monkeypatch)
    response = client.get(f"/v1/system-admin/llm/usage/invocations?{query}", headers=SYSTEM_HEADERS)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/v1/system-admin/llm/usage/summary?currency=EUR",
        "/v1/system-admin/llm/usage/summary?start_at=2026-07-15T00:00:00Z&end_at=2026-07-14T00:00:00Z",
        "/v1/system-admin/llm/usage/breakdown?group_by=secret",
        "/v1/system-admin/llm/usage/invocations?limit=501",
        "/v1/system-admin/llm/usage/summary?unknown_filter=value",
    ],
)
def test_usage_query_validation_is_strict(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    client, _service = _client(monkeypatch)

    response = client.get(path, headers=SYSTEM_HEADERS)

    assert response.status_code == 422


@pytest.mark.parametrize("provider_id", ["p" * 129, "provider%20id", "%00", "%0A"])
def test_llm_resource_ids_have_bounded_path_validation(monkeypatch: pytest.MonkeyPatch, provider_id: str) -> None:
    client, _service = _client(monkeypatch)

    response = client.patch(
        "/v1/system-admin/llm/providers/" + provider_id,
        headers=SYSTEM_HEADERS,
        json={"enabled": False, "expected_revision": 1, "reason": "bounded ID", "idempotency_key": "bounded-id"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("organization_id", ["not-a-uuid", "%00", "%20", "%0A", "11111111-1111-1111-1111-111111111111%20"])
def test_config_version_organization_filter_requires_canonical_uuid(monkeypatch: pytest.MonkeyPatch, organization_id: str) -> None:
    client, _service = _client(monkeypatch)

    response = client.get(
        f"/v1/system-admin/llm/config-versions?organization_id={organization_id}",
        headers=SYSTEM_HEADERS,
    )

    assert response.status_code == 422


def test_unexpected_repository_error_returns_safe_500(monkeypatch: pytest.MonkeyPatch) -> None:
    client, repository = _client(monkeypatch, raise_server_exceptions=False)
    repository.list_providers = lambda _session: (_ for _ in ()).throw(RuntimeError("credential-bearing upstream detail"))  # type: ignore[method-assign]

    response = client.get("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "credential-bearing" not in response.text


def test_default_test_adapters_fail_safely_instead_of_running_fake_checks() -> None:
    client = TestClient(create_app(Settings(environment="test", database_url=None)))
    provider = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()
    draft = client.post(
        "/v1/system-admin/llm/config-versions/drafts",
        headers=SYSTEM_HEADERS,
        json={"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "safe-default-draft"},
    ).json()

    tested = client.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "safe-default-test"},
    )

    assert tested.status_code == 202
    assert tested.json()["status"] == "failed"
    assert tested.json()["error_code"] == "tester_unavailable"
    assert "authorization" not in tested.text.lower()
    assert "prompt" not in tested.text.lower()


def test_default_release_gate_fails_safely_without_a_real_evaluation_adapter() -> None:
    client = TestClient(
        create_app(
            Settings(environment="test", database_url=None),
            llm_connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 5},
        )
    )
    provider = client.post("/v1/system-admin/llm/providers", headers=SYSTEM_HEADERS, json=PROVIDER).json()
    draft = client.post(
        "/v1/system-admin/llm/config-versions/drafts",
        headers=SYSTEM_HEADERS,
        json={"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "safe-gate-draft"},
    ).json()
    changed = client.put(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/routes",
        headers=SYSTEM_HEADERS,
        json={"routes": _routes(provider["provider_id"]), "expected_revision": 1, "reason": "routes", "idempotency_key": "safe-gate-routes"},
    ).json()
    client.post(
        f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
        headers=SYSTEM_HEADERS,
        json={"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "safe-gate-test"},
    )
    validated = client.post(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/validate",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "safe-gate-validate"},
    ).json()

    submitted = client.post(
        f"/v1/system-admin/llm/config-versions/{draft['version_id']}/submit-publish",
        headers=SYSTEM_HEADERS,
        json={"expected_revision": validated["revision"], "evaluation_run_id": "eval-without-adapter", "reason": "submit", "idempotency_key": "safe-gate-submit"},
    )

    assert submitted.status_code == 409
    assert submitted.json()["error"]["code"] == "release_gate_failed"
    assert "release_gate_unavailable" not in submitted.text


def test_non_test_app_selects_postgres_llm_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    sentinel = InMemoryLlmGovernanceRepository()

    def fake_postgres(database_url: str, **kwargs: Any) -> InMemoryLlmGovernanceRepository:
        captured["database_url"] = database_url
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(app_module, "PostgresLlmGovernanceRepository", fake_postgres)
    monkeypatch.setattr(
        app_module.KubernetesSecretProviderConnectionTester,
        "from_environment",
        lambda: (lambda _provider, _request: {"status": "passed", "latency_ms": 1}),
    )
    monkeypatch.setattr(
        app_module,
        "PostgresEvaluationReleaseGateChecker",
        lambda _database_url: (lambda _version, _run_id: {"status": "passed"}),
    )

    create_app(Settings(environment="development", database_url="postgresql://db.example.test/app"))

    assert captured["database_url"] == "postgresql://db.example.test/app"
    assert callable(captured["kwargs"]["connection_tester"])
    assert callable(captured["kwargs"]["release_gate_checker"])


def test_non_test_app_rejects_injected_in_memory_llm_repository() -> None:
    with pytest.raises(RuntimeError, match="test-only"):
        create_app(
            Settings(environment="development", database_url="postgresql://db.example.test/app"),
            llm_governance_repository=InMemoryLlmGovernanceRepository(),
        )


def test_non_test_app_fails_fast_without_kubernetes_secret_prerequisites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_PORT", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_PORT_HTTPS", raising=False)
    monkeypatch.delenv("LLM_GOVERNANCE_SECRET_NAMESPACE", raising=False)
    monkeypatch.delenv("LLM_GOVERNANCE_ALLOWED_SECRET_NAMES", raising=False)
    with pytest.raises(RuntimeError, match="Kubernetes in-cluster"):
        create_app(Settings(environment="development", database_url="postgresql://db.example.test/app"))
