from __future__ import annotations

import base64
import copy
import hashlib
import hmac
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
    InMemoryLlmGovernanceRepository as _InMemoryLlmGovernanceRepository,
    PostgresLlmGovernanceRepository as _PostgresLlmGovernanceRepository,
    _bounded_snapshot,
    _fingerprint,
)
from ecommerce_cs_agent.services.llm_governance_adapters import PostgresEvaluationReleaseGateChecker


ORG_ID = "11111111-1111-1111-1111-111111111111"
CURSOR_SIGNING_KEY = "test-only-fixed-llm-cursor-signing-key"


class InMemoryLlmGovernanceRepository(_InMemoryLlmGovernanceRepository):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(cursor_signing_key=CURSOR_SIGNING_KEY, **kwargs)


class PostgresLlmGovernanceRepository(_PostgresLlmGovernanceRepository):
    def __init__(self, database_url: str, **kwargs: Any) -> None:
        super().__init__(database_url, cursor_signing_key=CURSOR_SIGNING_KEY, **kwargs)


def _cursor_payload(cursor: str) -> dict[str, Any]:
    encoded, _signature = cursor.split(".", 1)
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def _signed_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(CURSOR_SIGNING_KEY.encode(), raw, hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


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


def _integration_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


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


def test_release_records_are_real_cursor_paginated_history() -> None:
    service = InMemoryLlmGovernanceRepository(
        connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 4},
        release_gate_checker=lambda _version, _run_id: {"status": "passed"},
    )
    primary = _create_provider(service, name="primary", idem="release-list-provider")
    routes = _all_routes(primary["provider_id"])
    first = _release(service, routes, suffix="release-list-one")
    second = _release(service, routes, suffix="release-list-two")

    first_page = service.list_release_records_page(_session("security_auditor"), ORG_ID, limit=1)
    second_page = service.list_release_records_page(_session(), ORG_ID, limit=1, cursor=first_page["page_info"]["next_cursor"])

    assert first_page["page_info"]["has_more"] is True
    assert first_page["items"][0]["config_version_id"] == second["version_id"]
    assert first_page["items"][0]["status"] == "running"
    assert second_page["items"][0]["config_version_id"] == first["version_id"]
    assert second_page["items"][0]["status"] == "superseded"
    assert second_page["page_info"]["next_cursor"] is None
    audits = [item for item in service.audit_logs if item["action"] == "llm.release.list"]
    assert len(audits) == 2
    assert audits[0]["actor_system_user_id"] == _session().user_id
    assert audits[0]["organization_id"] == ORG_ID
    assert audits[0]["diff_summary"]["cursor_present"] is True
    assert "secret" not in json.dumps(audits).lower()


def test_llm_cursors_are_hmac_authenticated_and_unsigned_cursors_are_rejected() -> None:
    service = InMemoryLlmGovernanceRepository()
    for index in range(3):
        service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "page", "idempotency_key": f"signed-page-{index}"})
    cursor = service.list_versions_page(_session(), ORG_ID, limit=2)["page_info"]["next_cursor"]
    payload = _cursor_payload(cursor)
    assert payload["kind"] == "config_versions"
    encoded, signature = cursor.split(".", 1)
    payload["version_number"] -= 1
    tampered_raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    tampered = f"{base64.urlsafe_b64encode(tampered_raw).decode().rstrip('=')}.{signature}"
    with pytest.raises(HTTPException) as changed:
        service.list_versions_page(_session(), ORG_ID, limit=2, cursor=tampered)
    assert changed.value.status_code == 422
    with pytest.raises(HTTPException) as unsigned:
        service.list_versions_page(_session(), ORG_ID, limit=2, cursor=encoded)
    assert unsigned.value.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [("submitted_at", "2026-07-15 00:00:00"), ("id", "not-a-uuid")],
)
def test_release_cursor_requires_strict_rfc3339_and_uuid_boundary(field: str, value: str) -> None:
    service = InMemoryLlmGovernanceRepository(
        connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 4},
        release_gate_checker=lambda _version, _run_id: {"status": "passed"},
    )
    provider = _create_provider(service, name="cursor-boundary", idem="cursor-boundary-provider")
    _release(service, _all_routes(provider["provider_id"]), suffix="cursor-boundary-one")
    _release(service, _all_routes(provider["provider_id"]), suffix="cursor-boundary-two")
    cursor = service.list_release_records_page(_session(), ORG_ID, limit=1)["page_info"]["next_cursor"]
    payload = _cursor_payload(cursor)
    payload[field] = value
    with pytest.raises(HTTPException) as invalid:
        service.list_release_records_page(_session(), ORG_ID, limit=1, cursor=_signed_cursor(payload))
    assert invalid.value.status_code == 422


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

    release_provider = service.create_provider(_session("release_admin"), dict(PROVIDER_PAYLOAD, name="release-admin", idempotency_key="release-admin"))
    assert release_provider["name"] == "release-admin"
    assert service.test_connection(_session("technical_support"), release_provider["provider_id"], {"reason": "diagnose", "idempotency_key": "support-test"})["status"] == "passed"
    with pytest.raises(HTTPException):
        service.test_connection(_session("security_auditor"), release_provider["provider_id"], {"reason": "diagnose", "idempotency_key": "auditor-test"})
    with pytest.raises(HTTPException):
        service.create_provider(_session("technical_support"), dict(PROVIDER_PAYLOAD, idempotency_key="support-denied"))


@pytest.mark.parametrize("base_url", [
    "https://user:password@llm.example.test/v1",
    "https://llm.example.test/v1?token=private",
    "https://llm.example.test/v1#secret",
    "https:///missing-host",
    "http://llm.example.test/v1",
])
def test_provider_url_rejects_credentials_query_fragment_and_non_https(base_url: str) -> None:
    with pytest.raises(HTTPException) as invalid:
        InMemoryLlmGovernanceRepository().create_provider(_session(), dict(PROVIDER_PAYLOAD, base_url=base_url, idempotency_key=f"invalid-url-{len(base_url)}"))
    assert invalid.value.detail["error"]["code"] == "invalid_provider_url"


@pytest.mark.parametrize(
    "secret_ref",
    [
        {"namespace": "Bad_Name", "name": "llm", "key": "api-key"},
        {"namespace": "runtime", "name": "a..b", "key": "api-key"},
        {"namespace": "runtime", "name": "Upper", "key": "api-key"},
        {"namespace": "a" * 64, "name": "llm", "key": "api-key"},
        {"namespace": "runtime", "name": "a" * 64, "key": "api-key"},
        {"namespace": "runtime", "name": "llm", "key": ""},
        {"namespace": "runtime\n", "name": "llm", "key": "api-key"},
        {"namespace": "runtime", "name": "llm\n", "key": "api-key"},
        {"namespace": "runtime", "name": "llm", "key": "api-key\n"},
    ],
)
def test_direct_service_provider_writes_reject_invalid_secret_references(
    secret_ref: dict[str, str],
) -> None:
    service = InMemoryLlmGovernanceRepository()
    with pytest.raises(HTTPException) as invalid_create:
        service.create_provider(
            _session(),
            {**PROVIDER_PAYLOAD, "secret_ref": secret_ref},
        )
    assert invalid_create.value.status_code == 422
    assert service.providers == {}

    provider = _create_provider(service, name="valid-provider", idem="valid-provider")
    with pytest.raises(HTTPException) as invalid_update:
        service.update_provider(
            _session(),
            provider["provider_id"],
            {
                "secret_ref": secret_ref,
                "reason": "reject invalid secret reference",
                "idempotency_key": f"invalid-secret-update-{len(str(secret_ref))}",
            },
            expected_revision=1,
        )
    assert invalid_update.value.status_code == 422
    assert service.providers[provider["provider_id"]]["revision"] == 1


def test_provider_endpoint_is_immutable_and_revision_change_requires_retest() -> None:
    service = InMemoryLlmGovernanceRepository()
    provider = _create_provider(service, name="immutable", idem="immutable-provider")
    for changes in ({"base_url": "https://other.example.test"}, {"secret_ref": {"namespace": "runtime", "name": "other", "key": "api-key"}}):
        with pytest.raises(HTTPException) as immutable:
            service.update_provider(_session(), provider["provider_id"], {**changes, "reason": "change endpoint", "idempotency_key": f"immutable-{len(str(changes))}"}, expected_revision=1)
        assert immutable.value.detail["error"]["code"] == "provider_endpoint_immutable"
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "immutable-draft"})
    changed = service.replace_routes(_session(), draft["version_id"], _all_routes(provider["provider_id"]), expected_revision=1, payload={"reason": "routes", "idempotency_key": "immutable-routes"})
    service.test_connection(_session("technical_support"), provider["provider_id"], {"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "immutable-test-one"})
    service.update_provider(_session(), provider["provider_id"], {"name": "renamed", "reason": "rename", "idempotency_key": "immutable-rename"}, expected_revision=2)
    with pytest.raises(HTTPException) as stale_test:
        service.validate_draft(_session(), draft["version_id"], {"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "immutable-validate-fail"})
    assert stale_test.value.detail["error"]["code"] == "provider_connection_test_required"
    service.test_connection(_session("technical_support"), provider["provider_id"], {"config_version_id": draft["version_id"], "reason": "retest", "idempotency_key": "immutable-test-two"})
    assert service.validate_draft(_session(), draft["version_id"], {"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "immutable-validate"})["status"] == "validated"


def test_input_boundaries_reject_audit_growth_and_too_many_routes() -> None:
    service = InMemoryLlmGovernanceRepository()
    with pytest.raises(HTTPException):
        service.create_provider(_session(), dict(PROVIDER_PAYLOAD, name="x" * 129, idempotency_key="long-name"))
    with pytest.raises(HTTPException):
        service.create_provider(_session(), dict(PROVIDER_PAYLOAD, reason="x" * 513, idempotency_key="long-reason"))
    with pytest.raises(HTTPException):
        service.create_draft(_session(), {"organization_id": ORG_ID, "description": "x" * 513, "reason": "draft", "idempotency_key": "long-description"})
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "bounded-draft"})
    with pytest.raises(HTTPException) as excessive:
        service.replace_routes(_session(), draft["version_id"], [dict(REPLY_ROUTE, scenario=f"scenario-{index}") for index in range(33)], expected_revision=1, payload={"reason": "routes", "idempotency_key": "too-many-routes"})
    assert excessive.value.detail["error"]["code"] == "too_many_routes"
    with pytest.raises(HTTPException):
        service.replace_routes(_session(), draft["version_id"], [dict(REPLY_ROUTE, primary_model="x" * 129)], expected_revision=1, payload={"reason": "routes", "idempotency_key": "long-model"})
    with pytest.raises(HTTPException) as oversized_snapshot:
        _bounded_snapshot({"safe": "x" * (65 * 1024)})
    assert oversized_snapshot.value.detail["error"]["code"] == "idempotency_snapshot_too_large"


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
    assert set(result) == {"connection_test_id", "provider_config_id", "config_version_id", "provider_revision", "status", "latency_ms", "checked_at", "error_code", "redacted_error_message"}
    assert result["error_code"] == "upstream_error"
    assert service.providers[provider["provider_id"]]["revision"] == 2
    flattened = json.dumps({"result": result, "stored": service.connection_tests, "audit": service.audit_logs})
    assert "leak-token-927" not in flattened
    assert "secret-private" not in flattened
    assert "customer text" not in flattened
    assert "private model output" not in flattened


def test_callbacks_use_snapshots_and_reject_concurrent_changes_without_leaking_exceptions() -> None:
    service = InMemoryLlmGovernanceRepository()
    provider = _create_provider(service, name="callback", idem="callback-provider")
    draft = service.create_draft(_session(), {"organization_id": ORG_ID, "reason": "draft", "idempotency_key": "callback-draft"})
    service._connection_tester = lambda _provider, _request: service.providers[provider["provider_id"]].update(revision=99) or {"status": "passed"}
    with pytest.raises(HTTPException) as changed:
        service.test_connection(_session("technical_support"), provider["provider_id"], {"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "callback-test"})
    assert changed.value.detail["error"]["code"] == "provider_changed_during_test"
    assert service.connection_tests == []

    safe = InMemoryLlmGovernanceRepository(connection_tester=lambda _provider, _request: (_ for _ in ()).throw(RuntimeError("Bearer secret")))
    safe_provider = _create_provider(safe, name="callback-safe", idem="callback-safe-provider")
    result = safe.test_connection(_session("technical_support"), safe_provider["provider_id"], {"reason": "test", "idempotency_key": "callback-safe-test"})
    assert result["error_code"] == "tester_unavailable"
    assert "Bearer secret" not in json.dumps({"result": result, "stored": safe.connection_tests, "audit": safe.audit_logs})


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
    assert service.release_records[published["version_id"]]["evaluation_config_version_id"] == published["version_id"]
    assert service.release_records[rolled_back["version_id"]]["evaluation_config_version_id"] == published["version_id"]


def test_running_source_rollback_is_atomic_and_creates_a_new_running_version() -> None:
    service = InMemoryLlmGovernanceRepository(release_gate_checker=lambda _version, _run: {"status": "passed"})
    provider = _create_provider(service, name="rollback-running", idem="rollback-running-provider")
    published = _release(service, _all_routes(provider["provider_id"]), suffix="rollback-running")
    rolled_back = service.rollback(_session(), published["version_id"], {"reason": "emergency rollback", "idempotency_key": "rollback-running"})
    assert service.get_version(_session(), published["version_id"])["status"] == "superseded"
    assert rolled_back["status"] == "running"
    assert rolled_back["rollback_of_version_id"] == published["version_id"]
    assert rolled_back["evaluation_run_id"] == published["evaluation_run_id"]


def test_in_memory_rollback_restores_running_version_when_audit_fails() -> None:
    service = InMemoryLlmGovernanceRepository(release_gate_checker=lambda _version, _run: {"status": "passed"})
    provider = _create_provider(service, name="rollback-failure", idem="rollback-failure-provider")
    published = _release(service, _all_routes(provider["provider_id"]), suffix="rollback-failure")
    before = copy.deepcopy(service.versions)
    original_finish = service._finish_write
    service._finish_write = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed"))
    with pytest.raises(RuntimeError, match="audit failed"):
        service.rollback(_session(), published["version_id"], {"reason": "emergency rollback", "idempotency_key": "rollback-failure"})
    service._finish_write = original_finish
    assert service.versions == before


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
    with pytest.raises(HTTPException):
        service.submit_publish(_session(), draft["version_id"], {"expected_revision": 3, "evaluation_run_id": "x" * 129, "reason": "submit", "idempotency_key": "explicit-long-eval"})
    service._release_gate_checker = lambda _version, _run: (_ for _ in ()).throw(RuntimeError("Bearer secret"))
    with pytest.raises(HTTPException) as safe_gate_error:
        service.submit_publish(_session(), draft["version_id"], {"expected_revision": 3, "evaluation_run_id": "eval-safe", "reason": "submit", "idempotency_key": "explicit-submit-exception"})
    assert "Bearer secret" not in json.dumps(safe_gate_error.value.detail)
    service._release_gate_checker = lambda _version, _run: {"status": "passed"}
    pending = service.submit_publish(_session(), draft["version_id"], {"expected_revision": 3, "evaluation_run_id": "eval-explicit", "reason": "submit", "idempotency_key": "explicit-submit"})
    assert (pending["status"], pending["revision"]) == ("pending_publish", 4)
    assert service.get_version(_session(), draft["version_id"])["evaluation_run_id"] == "eval-explicit"
    assert service.list_versions(_session(), ORG_ID)[0]["evaluation_run_id"] == "eval-explicit"
    running = service.publish(_session(), draft["version_id"], {"expected_revision": 4, "reason": "publish", "idempotency_key": "explicit-publish"})
    assert (running["status"], running["revision"]) == ("running", 5)
    assert running["evaluation_run_id"] == "eval-explicit"


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
    assert summary == {"calls": 2, "input_tokens": 30, "output_tokens": 15, "total_tokens": 45, "estimated_cost_micros": 600, "cost_by_currency": {"USD": 600}, "p95_latency_ms": 290.0, "error_rate": 0.5, "fallback_rate": 0.5}
    assert service.usage_timeseries(_session(), filters)
    assert service.usage_breakdown(_session(), filters, "model")[0]["calls"] == 2
    flattened = json.dumps(service.list_invocations(_session(), filters))
    assert "private" not in flattened
    assert "prompt" not in flattened
    assert "response" not in flattened


def test_zero_usage_has_nullable_rates_and_empty_collections() -> None:
    service = InMemoryLlmGovernanceRepository()
    assert service.usage_summary(_session(), {}) == {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated_cost_micros": None, "cost_by_currency": {}, "p95_latency_ms": None, "error_rate": None, "fallback_rate": None}
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
    now = datetime.now(timezone.utc)
    provider_row = ("33333333-3333-3333-3333-333333333333", "old", "openai_compatible", "https://llm.example.test/v1", "runtime", "llm", "api-key", True, "active", None, None, None, None, now, now, 9)
    connection = _FakeConnection(fetch_rows=[None, provider_row, None])
    service = PostgresLlmGovernanceRepository("postgresql://example")
    service._connect = lambda _url: connection
    with pytest.raises(HTTPException):
        service.update_provider(
            _session(), "33333333-3333-3333-3333-333333333333",
            {"name": "new", "reason": "rename", "idempotency_key": "pg-update"}, expected_revision=9,
        )
    sql = "\n".join(statement for statement, _params in connection.executed).lower()
    assert "where id=%s" in sql
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
    def __init__(
        self,
        fetch_rows: list[Any] | None = None,
        execute_errors: list[Exception | None] | None = None,
    ) -> None:
        self.fetch_rows = fetch_rows or []
        self.execute_errors = execute_errors or []
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
        error = self.connection.execute_errors.pop(0) if self.connection.execute_errors else None
        if error is not None:
            raise error

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.connection.fetch_rows.pop(0) if self.connection.fetch_rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        row = self.connection.fetch_rows.pop(0) if self.connection.fetch_rows else []
        return row if isinstance(row, list) else [row]


class _FakePostgresError(Exception):
    def __init__(self, sqlstate: str, raw_message: str) -> None:
        super().__init__(raw_message)
        self.sqlstate = sqlstate
        self.diag = type("FakeDiag", (), {"constraint_name": "secret_constraint_name"})()


@pytest.mark.parametrize("read_operation", ["get_version", "list_versions", "preload"])
def test_postgres_reads_map_invalid_uuid_without_leaking_database_text(
    read_operation: str,
) -> None:
    raw_message = "invalid input syntax for uuid: raw-db-value SELECT private_table"
    execute_errors: list[Exception | None] = [
        None,
        _FakePostgresError("22P02", raw_message),
    ] if read_operation == "preload" else [_FakePostgresError("22P02", raw_message)]
    connection = _FakeConnection(execute_errors=execute_errors)
    service = PostgresLlmGovernanceRepository("postgresql://example")
    service._connect = lambda _url: connection

    with pytest.raises(HTTPException) as invalid:
        if read_operation == "get_version":
            service.get_version(_session(), "not-a-uuid")
        elif read_operation == "list_versions":
            service.list_versions(_session(), "not-a-uuid")
        else:
            service.test_connection(
                _session("technical_support"),
                "not-a-uuid",
                {"reason": "preload", "idempotency_key": "invalid-preload"},
            )

    assert invalid.value.status_code == 422
    assert invalid.value.detail["error"]["code"] == "invalid_governance_input"
    public_error = json.dumps(invalid.value.detail)
    assert raw_message not in public_error
    assert "secret_constraint_name" not in public_error
    assert connection.rollbacks == 1


def test_postgres_reads_map_unknown_database_errors_to_safe_500() -> None:
    raw_message = "internal SQL SELECT private_table secret_constraint_name"
    connection = _FakeConnection(
        execute_errors=[_FakePostgresError("XX000", raw_message)]
    )
    service = PostgresLlmGovernanceRepository("postgresql://example")
    service._connect = lambda _url: connection

    with pytest.raises(HTTPException) as failed:
        service.get_version(_session(), "not-a-uuid")

    assert failed.value.status_code == 500
    assert failed.value.detail["error"]["code"] == "governance_database_error"
    public_error = json.dumps(failed.value.detail)
    assert raw_message not in public_error
    assert "secret_constraint_name" not in public_error


def test_postgres_service_full_lifecycle_when_database_is_available() -> None:
    database_url = _integration_database_url()
    if not database_url:
        pytest.skip("set TEST_DATABASE_URL to run PostgreSQL service integration")
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
        service = PostgresLlmGovernanceRepository(
            scoped_url,
            connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 2},
            release_gate_checker=PostgresEvaluationReleaseGateChecker(scoped_url),
        )
        def complete_evaluation(version: dict[str, Any], evaluation_run_id: str) -> None:
            with psycopg.connect(scoped_url) as evaluation_connection:
                with evaluation_connection.cursor() as cur:
                    cur.execute(
                        "INSERT INTO llm_eval_run (id, organization_id, config_version_id, config_revision, configuration_hash) VALUES (%s,%s,%s,%s,%s)",
                        (evaluation_run_id, version["organization_id"], version["version_id"], version["revision"], version["configuration_hash"]),
                    )
                    cur.execute(
                        "UPDATE llm_eval_run SET status='completed', gate_status='passed', completed_at=now(), revision=2 WHERE id=%s",
                        (evaluation_run_id,),
                    )
        provider_payload = dict(PROVIDER_PAYLOAD, idempotency_key="integration-provider")
        provider = service.create_provider(session, provider_payload)
        assert set(provider["secret_ref"]) == {"namespace", "name", "key"}
        with pytest.raises(HTTPException) as immutable_provider:
            service.update_provider(session, provider["provider_id"], {"base_url": "https://other.example.test", "reason": "integration", "idempotency_key": "integration-immutable"}, expected_revision=1)
        assert immutable_provider.value.detail["error"]["code"] == "provider_endpoint_immutable"
        with pytest.raises(HTTPException) as duplicate_provider:
            service.create_provider(session, dict(provider_payload, idempotency_key="integration-provider-duplicate"))
        assert duplicate_provider.value.detail["error"]["code"] == "provider_name_conflict"
        with pytest.raises(HTTPException) as invalid_org:
            service.create_draft(session, {"organization_id": "ffffffff-ffff-ffff-ffff-ffffffffffff", "reason": "integration", "idempotency_key": "integration-invalid-org"})
        assert invalid_org.value.detail["error"]["code"] == "invalid_governance_reference"
        invalid_route_draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-invalid-route-draft"})
        with pytest.raises(HTTPException) as invalid_provider:
            service.replace_routes(session, invalid_route_draft["version_id"], _all_routes("ffffffff-ffff-ffff-ffff-ffffffffffff"), expected_revision=1, payload={"reason": "integration", "idempotency_key": "integration-invalid-provider"})
        assert invalid_provider.value.detail["error"]["code"] == "invalid_governance_reference"
        concurrent_provider = service.create_provider(session, dict(provider_payload, name="concurrent-provider", idempotency_key="integration-concurrent-provider"))
        concurrent_draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-concurrent-draft"})
        def mutate_provider_outside_test_transaction(_provider: dict[str, Any], _request: dict[str, int]) -> dict[str, Any]:
            with psycopg.connect(scoped_url) as concurrent_connection:
                with concurrent_connection.cursor() as cur:
                    cur.execute("UPDATE llm_provider_config SET name='changed-during-test', revision=revision+1 WHERE id=%s", (concurrent_provider["provider_id"],))
            return {"status": "passed", "latency_ms": 1}
        concurrent_service = PostgresLlmGovernanceRepository(scoped_url, connection_tester=mutate_provider_outside_test_transaction)
        with pytest.raises(HTTPException) as concurrent_change:
            concurrent_service.test_connection(session, concurrent_provider["provider_id"], {"config_version_id": concurrent_draft["version_id"], "reason": "integration", "idempotency_key": "integration-concurrent-test"})
        assert concurrent_change.value.detail["error"]["code"] == "provider_changed_during_test"
        with psycopg.connect(scoped_url) as verify_no_stale_test:
            with verify_no_stale_test.cursor() as cur:
                cur.execute("SELECT count(*) FROM llm_connection_test WHERE provider_config_id=%s", (concurrent_provider["provider_id"],))
                assert cur.fetchone() == (0,)
        gate_draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-gate-draft"})
        gate_changed = service.replace_routes(session, gate_draft["version_id"], _all_routes(concurrent_provider["provider_id"]), expected_revision=1, payload={"reason": "integration", "idempotency_key": "integration-gate-routes"})
        service.test_connection(session, concurrent_provider["provider_id"], {"config_version_id": gate_draft["version_id"], "reason": "integration", "idempotency_key": "integration-gate-test"})
        gate_validated = service.validate_draft(session, gate_draft["version_id"], {"expected_revision": gate_changed["revision"], "reason": "integration", "idempotency_key": "integration-gate-validate"})
        def mutate_version_outside_gate_transaction(_version: dict[str, Any], _evaluation: str) -> dict[str, Any]:
            with psycopg.connect(scoped_url) as concurrent_connection:
                with concurrent_connection.cursor() as cur:
                    cur.execute("UPDATE llm_config_version SET revision=revision+1 WHERE id=%s", (gate_draft["version_id"],))
            return {"status": "passed"}
        concurrent_gate_service = PostgresLlmGovernanceRepository(scoped_url, release_gate_checker=mutate_version_outside_gate_transaction)
        with pytest.raises(HTTPException) as gate_change:
            concurrent_gate_service.submit_publish(session, gate_draft["version_id"], {"expected_revision": gate_validated["revision"], "evaluation_run_id": "integration-concurrent-gate", "reason": "integration", "idempotency_key": "integration-concurrent-gate"})
        assert gate_change.value.status_code == 409
        with psycopg.connect(scoped_url) as verify_no_release:
            with verify_no_release.cursor() as cur:
                cur.execute("SELECT count(*) FROM llm_release_record WHERE config_version_id=%s", (gate_draft["version_id"],))
                assert cur.fetchone() == (0,)
        draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-draft"})
        changed = service.replace_routes(session, draft["version_id"], _all_routes(provider["provider_id"]), expected_revision=1, payload={"reason": "integration", "idempotency_key": "integration-routes"})
        tested = service.test_connection(session, provider["provider_id"], {"config_version_id": draft["version_id"], "reason": "integration", "idempotency_key": "integration-test"})
        assert tested["status"] == "passed"
        assert service.create_provider(session, provider_payload) == provider
        with pytest.raises(HTTPException) as create_conflict:
            service.create_provider(session, dict(provider_payload, base_url="https://other.example.test"))
        assert create_conflict.value.status_code == 409
        validated = service.validate_draft(session, draft["version_id"], {"expected_revision": changed["revision"], "reason": "integration", "idempotency_key": "integration-validate"})
        complete_evaluation(validated, "integration-eval")
        pending = service.submit_publish(session, draft["version_id"], {"expected_revision": validated["revision"], "evaluation_run_id": "integration-eval", "reason": "integration", "idempotency_key": "integration-submit"})
        assert pending["release_status"] == "pending"
        assert service.get_version(session, draft["version_id"])["evaluation_run_id"] == "integration-eval"
        assert service.list_versions(session, organization_id)[0]["evaluation_run_id"] == "integration-eval"
        running = service.publish(session, draft["version_id"], {"expected_revision": pending["revision"], "reason": "integration", "idempotency_key": "integration-publish"})
        assert running["status"] == "running"
        assert running["evaluation_run_id"] == "integration-eval"
        assert running["release_status"] == "running"
        release_page = service.list_release_records_page(session, organization_id, limit=1)
        assert release_page["items"][0]["config_version_id"] == running["version_id"]
        with psycopg.connect(scoped_url) as verify_release_read_audit:
            with verify_release_read_audit.cursor() as cur:
                cur.execute("SELECT system_admin_user_id::text, organization_id::text, diff_summary FROM system_admin_audit_log WHERE action='llm.release.list' ORDER BY created_at DESC LIMIT 1")
                audit_row = cur.fetchone()
                assert audit_row[0] == user_id
                assert audit_row[1] == organization_id
                assert audit_row[2]["limit"] == 1
                assert "cursor" not in json.dumps(audit_row[2]).lower().replace("cursor_present", "")
        second_draft = service.create_draft(session, {"organization_id": organization_id, "reason": "integration", "idempotency_key": "integration-draft-two"})
        second_changed = service.replace_routes(session, second_draft["version_id"], _all_routes(provider["provider_id"]), expected_revision=1, payload={"reason": "integration", "idempotency_key": "integration-routes-two"})
        service.test_connection(session, provider["provider_id"], {"config_version_id": second_draft["version_id"], "reason": "integration", "idempotency_key": "integration-test-two"})
        service.update_provider(session, provider["provider_id"], {"enabled": False, "reason": "integration", "idempotency_key": "integration-disable"}, expected_revision=3)
        with pytest.raises(HTTPException) as disabled_provider:
            service.validate_draft(session, second_draft["version_id"], {"expected_revision": second_changed["revision"], "reason": "integration", "idempotency_key": "integration-disabled-validate"})
        assert disabled_provider.value.detail["error"]["code"] == "provider_not_ready"
        service.update_provider(session, provider["provider_id"], {"enabled": True, "reason": "integration", "idempotency_key": "integration-enable"}, expected_revision=4)
        service.test_connection(session, provider["provider_id"], {"config_version_id": second_draft["version_id"], "reason": "integration", "idempotency_key": "integration-retest-after-enable"})
        second_validated = service.validate_draft(session, second_draft["version_id"], {"expected_revision": second_changed["revision"], "reason": "integration", "idempotency_key": "integration-validate-two"})
        complete_evaluation(second_validated, "integration-eval-two")
        second_pending = service.submit_publish(session, second_draft["version_id"], {"expected_revision": second_validated["revision"], "evaluation_run_id": "integration-eval-two", "reason": "integration", "idempotency_key": "integration-submit-two"})
        original_audit = service._audit
        service._audit = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("publish audit failed"))
        with pytest.raises(HTTPException) as publish_audit_failure:
            service.publish(session, second_draft["version_id"], {"expected_revision": second_pending["revision"], "reason": "integration", "idempotency_key": "integration-publish-two-audit-fail"})
        assert publish_audit_failure.value.status_code == 500
        assert publish_audit_failure.value.detail["error"]["code"] == "governance_database_error"
        publish_public_error = json.dumps(publish_audit_failure.value.detail)
        assert "publish audit failed" not in publish_public_error
        assert "RuntimeError" not in publish_public_error
        service._audit = original_audit
        with psycopg.connect(scoped_url) as verify_publish_rollback:
            with verify_publish_rollback.cursor() as cur:
                cur.execute("SELECT status FROM llm_config_version WHERE id=%s", (running["version_id"],))
                assert cur.fetchone() == ("running",)
                cur.execute("SELECT status FROM llm_config_version WHERE id=%s", (second_draft["version_id"],))
                assert cur.fetchone() == ("pending_publish",)
                cur.execute("SELECT status FROM llm_release_record WHERE config_version_id=%s", (running["version_id"],))
                assert cur.fetchone() == ("running",)
                cur.execute("SELECT status FROM llm_release_record WHERE config_version_id=%s", (second_draft["version_id"],))
                assert cur.fetchone() == ("pending",)
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
        assert len(service.list_providers(session)) == 2
        second_running = service.publish(session, second_draft["version_id"], {"expected_revision": second_pending["revision"], "reason": "integration", "idempotency_key": "integration-publish-two-success"})
        assert second_running["status"] == "running"
        original_audit = service._audit
        service._audit = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rollback audit failed"))
        with pytest.raises(HTTPException) as rollback_audit_failure:
            service.rollback(session, running["version_id"], {"reason": "integration", "idempotency_key": "integration-rollback-audit-fail"})
        assert rollback_audit_failure.value.status_code == 500
        assert rollback_audit_failure.value.detail["error"]["code"] == "governance_database_error"
        rollback_public_error = json.dumps(rollback_audit_failure.value.detail)
        assert "rollback audit failed" not in rollback_public_error
        assert "RuntimeError" not in rollback_public_error
        service._audit = original_audit
        with psycopg.connect(scoped_url) as verify_rollback:
            with verify_rollback.cursor() as cur:
                cur.execute("SELECT status FROM llm_config_version WHERE id=%s", (second_running["version_id"],))
                assert cur.fetchone() == ("running",)
                cur.execute("SELECT status FROM llm_release_record WHERE config_version_id=%s", (second_running["version_id"],))
                assert cur.fetchone() == ("running",)
                cur.execute("SELECT count(*) FROM llm_config_version WHERE organization_id=%s", (organization_id,))
                assert cur.fetchone() == (5,)
        rolled_back = service.rollback(session, second_running["version_id"], {"reason": "integration", "idempotency_key": "integration-rollback-running"})
        assert rolled_back["status"] == "running"
        assert rolled_back["rollback_of_version_id"] == second_running["version_id"]
        assert service.get_version(session, second_running["version_id"])["status"] == "superseded"
        assert rolled_back["evaluation_run_id"] == "integration-eval-two"
    finally:
        setup.close()
        with psycopg.connect(database_url, autocommit=True) as cleanup:
            with cleanup.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))


def test_service_integration_never_falls_back_to_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-be-used")
    assert _integration_database_url() is None
