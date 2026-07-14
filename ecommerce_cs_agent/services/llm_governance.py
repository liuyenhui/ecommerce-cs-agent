from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.services.admin_auth import SystemAdminSession


_WRITE_ROLES = {"super_admin", "release_admin"}
_READ_ROLES = _WRITE_ROLES | {"technical_support", "security_auditor"}
_CONNECTION_TEST_ROLES = _WRITE_ROLES | {"technical_support"}
_PROVIDER_TYPES = {"openai", "openai_compatible", "anthropic", "azure_openai"}
_REQUIRED_SCENARIOS = {
    "reply_generation",
    "knowledge_extraction",
    "blind_test_question_generation",
}
_SAFE_ERROR_CODES = {
    "connection_failed", "auth_failed", "timeout", "dns_error", "tls_error",
    "rate_limited", "provider_unavailable", "invalid_response",
    "tester_unavailable", "upstream_error",
}
_PUBLIC_PROVIDER_FIELDS = (
    "provider_id", "name", "provider_type", "base_url", "enabled", "status",
    "last_connection_test_status", "last_connection_test_latency_ms",
    "last_connection_test_error_code", "last_connection_tested_at",
    "created_at", "updated_at", "revision",
)
_PUBLIC_INVOCATION_FIELDS = (
    "invocation_id", "occurred_at", "provider_config_id", "provider_name", "model",
    "scenario", "organization_id", "store_id", "route_role", "input_tokens",
    "output_tokens", "latency_ms", "status", "error_code", "estimated_cost_micros",
    "currency",
)


class LlmGovernanceRepository(Protocol):
    def list_providers(self, session: SystemAdminSession) -> list[dict[str, Any]]: ...
    def create_provider(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_provider(self, session: SystemAdminSession, provider_id: str, payload: dict[str, Any], *, expected_revision: int) -> dict[str, Any]: ...
    def test_connection(self, session: SystemAdminSession, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def list_versions(self, session: SystemAdminSession, organization_id: str) -> list[dict[str, Any]]: ...
    def list_versions_page(self, session: SystemAdminSession, organization_id: str, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]: ...
    def get_version(self, session: SystemAdminSession, version_id: str) -> dict[str, Any]: ...
    def create_draft(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]: ...
    def replace_routes(self, session: SystemAdminSession, version_id: str, routes: list[dict[str, Any]], *, expected_revision: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    def validate_draft(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def submit_publish(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def publish(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def rollback(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def usage_summary(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]: ...
    def usage_timeseries(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]: ...
    def usage_breakdown(self, session: SystemAdminSession, filters: dict[str, Any], group_by: str) -> list[dict[str, Any]]: ...
    def list_invocations(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]: ...
    def list_invocations_page(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]: ...


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.astimezone(timezone.utc).isoformat()


def _encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_scope_hash(kind: str, scope: dict[str, Any]) -> str:
    payload = {"kind": kind, "scope": scope}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _cursor_scope_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise api_error(422, "invalid_cursor_scope", "cursor scope datetimes must include a UTC offset")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _invocation_cursor_scope(filters: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "start_at",
        "end_at",
        "provider_config_id",
        "model",
        "scenario",
        "organization_id",
        "store_id",
        "currency",
        "status",
        "route_role",
    )
    return {
        "filters": {key: _cursor_scope_value(filters.get(key)) for key in keys},
        "sort": ["occurred_at:desc", "invocation_id:desc"],
    }


def _decode_cursor(value: str | None, *, kind: str, scope_hash: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if (
            not isinstance(data, dict)
            or data.get("version") != 1
            or data.get("kind") != kind
            or data.get("scope_hash") != scope_hash
        ):
            raise ValueError
        if kind == "config_versions":
            if not isinstance(data.get("version_number"), int) or data["version_number"] <= 0:
                raise ValueError
        elif kind == "invocations":
            occurred_at = datetime.fromisoformat(
                str(data.get("occurred_at", "")).replace("Z", "+00:00")
            )
            if occurred_at.tzinfo is None or occurred_at.utcoffset() != timezone.utc.utcoffset(occurred_at):
                raise ValueError
            uuid.UUID(str(data.get("id")))
        return data
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        raise api_error(422, "invalid_cursor", "cursor is invalid") from None


def _require_live_session(session: SystemAdminSession) -> None:
    now = _now_dt()
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if session.revoked_at is not None or expires_at <= now:
        raise api_error(401, "system_admin_session_expired", "system admin session is expired")


def _require_role(session: SystemAdminSession, roles: set[str]) -> None:
    _require_live_session(session)
    if session.role not in roles:
        raise api_error(403, "forbidden", "system admin role cannot perform this operation")


def _require_write(payload: dict[str, Any]) -> tuple[str, str]:
    reason = _bounded_text(payload.get("reason"), "reason", 512)
    key = _bounded_text(payload.get("idempotency_key"), "idempotency_key", 128)
    if not reason:
        raise api_error(422, "audit_reason_required", "reason is required")
    if not key:
        raise api_error(422, "idempotency_key_required", "idempotency_key is required")
    return reason, key


def _bounded_text(value: Any, field: str, maximum: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise api_error(422, f"{field}_required", f"{field} is required")
    if len(text) > maximum or any(ord(char) < 32 for char in text):
        raise api_error(422, f"invalid_{field}", f"{field} exceeds its safe text boundary")
    return text


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _public_provider(provider: dict[str, Any]) -> dict[str, Any]:
    result = {field: copy.deepcopy(provider.get(field)) for field in _PUBLIC_PROVIDER_FIELDS}
    result["secret_ref"] = {
        "namespace": str(provider.get("secret_namespace") or ""),
        "name": str(provider.get("secret_name") or ""),
        "key": str(provider.get("secret_key") or ""),
    }
    return result


def _validate_provider_input(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for field in ("name", "provider_type", "base_url", "enabled"):
        if field in payload:
            allowed[field] = payload[field]
    if "secret_ref" in payload:
        ref = payload.get("secret_ref")
        if not isinstance(ref, dict):
            raise api_error(422, "invalid_secret_ref", "secret_ref must be an object")
        values = {key: _bounded_text(ref.get(key), f"secret_{key}", 253) for key in ("namespace", "name", "key")}
        if not all(values.values()):
            raise api_error(422, "invalid_secret_ref", "secret_ref namespace, name, and key are required")
        allowed.update({"secret_namespace": values["namespace"], "secret_name": values["name"], "secret_key": values["key"]})
    required = ("name", "provider_type", "base_url", "secret_namespace", "secret_name", "secret_key")
    if not partial and any(not str(allowed.get(field) or "").strip() for field in required):
        raise api_error(422, "invalid_provider", "provider name, type, base URL, and Secret reference are required")
    if "provider_type" in allowed and allowed["provider_type"] not in _PROVIDER_TYPES:
        raise api_error(422, "invalid_provider_type", "provider type is not allowed")
    if "name" in allowed:
        allowed["name"] = _bounded_text(allowed["name"], "provider_name", 128)
    if "provider_type" in allowed:
        allowed["provider_type"] = _bounded_text(allowed["provider_type"], "provider_type", 64)
    if "base_url" in allowed:
        base_url = _bounded_text(allowed["base_url"], "provider_url", 2048)
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise api_error(422, "invalid_provider_url", "provider base URL must be a credential-free HTTPS origin without query or fragment")
        allowed["base_url"] = base_url.rstrip("/")
    if "enabled" in allowed:
        allowed["enabled"] = bool(allowed["enabled"])
    return allowed


def _validate_connection_request(payload: dict[str, Any]) -> dict[str, int]:
    timeout_seconds = int(payload.get("timeout_seconds", 20))
    max_tokens = int(payload.get("max_tokens", 256))
    if timeout_seconds <= 0 or timeout_seconds > 20:
        raise api_error(422, "invalid_connection_test_timeout", "timeout_seconds must be between 1 and 20")
    if max_tokens <= 0 or max_tokens > 256:
        raise api_error(422, "invalid_connection_test_token_limit", "max_tokens must be between 1 and 256")
    return {"timeout_seconds": timeout_seconds, "max_tokens": max_tokens}


def _redacted_error_message(error_code: Any) -> str | None:
    if not error_code:
        return None
    return "Provider connection failed; sensitive upstream details were removed."


def _sanitize_error_code(value: Any) -> str:
    candidate = str(value or "connection_failed").strip().lower()
    if candidate in _SAFE_ERROR_CODES:
        return candidate
    return "upstream_error"


def _safe_evaluation_run_id(value: Any) -> str:
    candidate = _bounded_text(value, "evaluation_run_id", 128)
    if not candidate or len(candidate) > 128 or not all(char.isalnum() or char in "-_:" for char in candidate):
        raise api_error(422, "evaluation_run_required", "a non-sensitive evaluation_run_id is required")
    return candidate


def _require_complete_scenarios(routes: list[dict[str, Any]]) -> None:
    scenarios = [str(route.get("scenario") or "") for route in routes]
    if len(scenarios) != len(set(scenarios)) or set(scenarios) != _REQUIRED_SCENARIOS:
        raise api_error(409, "llm_scenarios_incomplete", "all required LLM scenarios must be configured exactly once")


def _validate_route(route: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "scenario", "primary_provider_config_id", "primary_model",
        "fallback_provider_config_id", "fallback_model", "enabled", "temperature",
        "max_output_tokens", "timeout_seconds", "max_retries",
        "circuit_breaker_threshold", "recovery_probe_seconds",
    )
    item = {field: copy.deepcopy(route.get(field)) for field in fields}
    if not str(item["scenario"] or "").strip() or not str(item["primary_provider_config_id"] or "").strip() or not str(item["primary_model"] or "").strip():
        raise api_error(422, "invalid_llm_route", "scenario, primary provider, and primary model are required")
    has_fallback_provider = bool(item["fallback_provider_config_id"])
    has_fallback_model = bool(item["fallback_model"])
    if has_fallback_provider != has_fallback_model:
        raise api_error(422, "invalid_llm_route", "fallback provider and model must be supplied together")
    item["scenario"] = _bounded_text(item["scenario"], "scenario", 64)
    item["primary_provider_config_id"] = _bounded_text(item["primary_provider_config_id"], "primary_provider_config_id", 128)
    item["primary_model"] = _bounded_text(item["primary_model"], "primary_model", 128)
    if item["fallback_provider_config_id"] is not None:
        item["fallback_provider_config_id"] = _bounded_text(item["fallback_provider_config_id"], "fallback_provider_config_id", 128)
    if item["fallback_model"] is not None:
        item["fallback_model"] = _bounded_text(item["fallback_model"], "fallback_model", 128)
    item["enabled"] = bool(item["enabled"])
    item["temperature"] = float(item["temperature"])
    item["max_output_tokens"] = int(item["max_output_tokens"])
    item["timeout_seconds"] = int(item["timeout_seconds"])
    item["max_retries"] = int(item["max_retries"])
    item["circuit_breaker_threshold"] = int(item["circuit_breaker_threshold"])
    item["recovery_probe_seconds"] = int(item["recovery_probe_seconds"])
    if not 0 <= item["temperature"] <= 2 or min(item["max_output_tokens"], item["timeout_seconds"], item["circuit_breaker_threshold"], item["recovery_probe_seconds"]) <= 0 or item["max_retries"] < 0:
        raise api_error(422, "invalid_llm_route_parameters", "route runtime parameters are outside allowed ranges")
    return item


def _configuration_hash(routes: list[dict[str, Any]]) -> str:
    return _fingerprint(routes)


def _validate_route_collection(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(routes) > 32:
        raise api_error(422, "too_many_routes", "at most 32 scenario routes are allowed")
    return [_validate_route(route) for route in routes]


def _public_invocation(item: dict[str, Any]) -> dict[str, Any]:
    result = {field: copy.deepcopy(item.get(field)) for field in _PUBLIC_INVOCATION_FIELDS}
    result["occurred_at"] = _iso(result["occurred_at"])
    return result


def _bounded_snapshot(response: dict[str, Any]) -> dict[str, Any]:
    snapshot = copy.deepcopy(response)
    encoded = json.dumps(snapshot, sort_keys=True, default=str, separators=(",", ":")).encode()
    if len(encoded) > 64 * 1024:
        raise api_error(422, "idempotency_snapshot_too_large", "safe idempotency response exceeds 64 KiB")
    return snapshot


class InMemoryLlmGovernanceRepository:
    def __init__(
        self,
        connection_tester: Callable[[dict[str, Any], dict[str, int]], dict[str, Any]] | None = None,
        release_gate_checker: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
    ) -> None:
        self.providers: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.release_records: dict[str, dict[str, Any]] = {}
        self.connection_tests: list[dict[str, Any]] = []
        self.invocation_metrics: list[dict[str, Any]] = []
        self.audit_logs: list[dict[str, Any]] = []
        self._idempotency: dict[tuple[str, str], dict[str, Any]] = {}
        self._connection_tester = connection_tester or (lambda _provider, _request: {"status": "passed", "latency_ms": 0})
        self._release_gate_checker = release_gate_checker or (
            lambda _version, _evaluation_run_id: {"status": "failed", "error_code": "release_gate_unavailable"}
        )

    def _begin_write(self, session: SystemAdminSession, roles: set[str], action: str, payload: dict[str, Any], request_data: Any) -> tuple[str, str, dict[str, Any] | None]:
        _require_role(session, roles)
        reason, key = _require_write(payload)
        fingerprint = _fingerprint(request_data)
        prior = self._idempotency.get((action, key))
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise api_error(409, "idempotency_conflict", "idempotency key was already used with a different request")
            return reason, key, copy.deepcopy(prior["response"])
        return reason, key, None

    def _finish_write(self, session: SystemAdminSession, action: str, object_type: str, object_id: str, reason: str, key: str, request_data: Any, response: dict[str, Any]) -> dict[str, Any]:
        safe_diff = {"reason": reason, "idempotency_key": key, "request_hash": _fingerprint(request_data)}
        audit_id = f"audit-{uuid.uuid4().hex}"
        self.audit_logs.insert(0, {"audit_log_id": audit_id, "actor_system_user_id": session.user_id, "action": action, "object_type": object_type, "object_id": object_id, "reason": reason, "diff_summary": safe_diff, "created_at": _iso(_now_dt())})
        result = _bounded_snapshot(response)
        self._idempotency[(action, key)] = {"fingerprint": _fingerprint(request_data), "response": result}
        return copy.deepcopy(result)

    def list_providers(self, session: SystemAdminSession) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        return [_public_provider(item) for item in self.providers.values()]

    def create_provider(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        data = _validate_provider_input(payload)
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.provider.create", payload, data)
        if replay is not None:
            return replay
        if any(item["name"] == data["name"] for item in self.providers.values()):
            raise api_error(409, "provider_name_conflict", "provider name already exists")
        now = _iso(_now_dt())
        provider_id = str(uuid.uuid4())
        provider = {"provider_id": provider_id, **data, "enabled": data.get("enabled", True), "status": "active" if data.get("enabled", True) else "disabled", "last_connection_test_status": None, "last_connection_test_latency_ms": None, "last_connection_test_error_code": None, "last_connection_tested_at": None, "created_at": now, "updated_at": now, "revision": 1}
        self.providers[provider_id] = provider
        return self._finish_write(session, "llm.provider.create", "llm_provider_config", provider_id, reason, key, data, _public_provider(provider))

    def update_provider(self, session: SystemAdminSession, provider_id: str, payload: dict[str, Any], *, expected_revision: int) -> dict[str, Any]:
        data = _validate_provider_input(payload, partial=True)
        request_data = {"provider_id": provider_id, "expected_revision": expected_revision, "changes": data}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.provider.update", payload, request_data)
        if replay is not None:
            return replay
        provider = self.providers.get(provider_id)
        if not provider:
            raise api_error(404, "provider_not_found", "provider was not found")
        if provider["revision"] != expected_revision:
            raise api_error(409, "stale_revision", "provider revision is stale")
        for field in ("provider_type", "base_url", "secret_namespace", "secret_name", "secret_key"):
            if field in data and data[field] != provider[field]:
                raise api_error(409, "provider_endpoint_immutable", "provider endpoint and Secret reference are immutable; create a new Provider")
        if "name" in data and any(item["provider_id"] != provider_id and item["name"] == data["name"] for item in self.providers.values()):
            raise api_error(409, "provider_name_conflict", "provider name already exists")
        if not any(field in data for field in ("name", "enabled")):
            raise api_error(422, "provider_update_empty", "only provider name and enabled state may be updated")
        provider.update({field: data[field] for field in ("name", "enabled") if field in data})
        if "enabled" in data:
            provider["status"] = "active" if data["enabled"] else "disabled"
        provider["revision"] = expected_revision + 1
        provider["updated_at"] = _iso(_now_dt())
        return self._finish_write(session, "llm.provider.update", "llm_provider_config", provider_id, reason, key, request_data, _public_provider(provider))

    def test_connection(self, session: SystemAdminSession, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = _validate_connection_request(payload)
        request_data = {"provider_id": provider_id, **request, "config_version_id": payload.get("config_version_id")}
        reason, key, replay = self._begin_write(session, _CONNECTION_TEST_ROLES, "llm.provider.connection_test", payload, request_data)
        if replay is not None:
            return replay
        provider = self.providers.get(provider_id)
        if not provider:
            raise api_error(404, "provider_not_found", "provider was not found")
        config_version_id = payload.get("config_version_id")
        if config_version_id:
            version = self.versions.get(str(config_version_id))
            if not version or version["status"] != "draft":
                raise api_error(409, "connection_test_requires_draft", "connection tests may only target an existing draft")
        provider_snapshot = copy.deepcopy(provider)
        version_snapshot = copy.deepcopy(self.versions.get(str(config_version_id))) if config_version_id else None
        try:
            raw = self._connection_tester(_public_provider(provider_snapshot), request)
        except Exception:
            raw = {"status": "failed", "latency_ms": 0, "error_code": "tester_unavailable"}
        if self.providers.get(provider_id, {}).get("revision") != provider_snapshot["revision"]:
            raise api_error(409, "provider_changed_during_test", "provider changed while the connection test was running")
        if config_version_id and self.versions.get(str(config_version_id)) != version_snapshot:
            raise api_error(409, "draft_changed_during_test", "draft changed while the connection test was running")
        status = "passed" if raw.get("status") == "passed" else "failed"
        checked_at = _iso(_now_dt())
        error_code = _sanitize_error_code(raw.get("error_code")) if status == "failed" else None
        provider["revision"] += 1
        record = {"connection_test_id": str(uuid.uuid4()), "provider_config_id": provider_id, "config_version_id": config_version_id, "provider_revision": provider["revision"], "status": status, "latency_ms": max(0, int(raw.get("latency_ms") or 0)), "checked_at": checked_at, "error_code": error_code, "redacted_error_message": _redacted_error_message(error_code)}
        self.connection_tests.append(copy.deepcopy(record))
        provider.update({"last_connection_test_status": status, "last_connection_test_latency_ms": record["latency_ms"], "last_connection_test_error_code": error_code, "last_connection_tested_at": checked_at, "updated_at": checked_at})
        if provider["enabled"]:
            provider["status"] = "active" if status == "passed" else "unhealthy"
        return self._finish_write(session, "llm.provider.connection_test", "llm_connection_test", record["connection_test_id"], reason, key, request_data, record)

    def create_draft(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = _bounded_text(payload.get("organization_id"), "organization_id", 128)
        if not organization_id:
            raise api_error(422, "organization_required", "organization_id is required")
        description = _bounded_text(payload.get("description"), "description", 512, required=False) or None
        request_data = {"organization_id": organization_id, "description": description}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.config.create_draft", payload, request_data)
        if replay is not None:
            return replay
        number = max((int(v["version_number"]) for v in self.versions.values() if v["organization_id"] == organization_id), default=0) + 1
        version_id = str(uuid.uuid4())
        version = {"version_id": version_id, "organization_id": organization_id, "version_number": number, "status": "draft", "revision": 1, "description": request_data["description"], "configuration_hash": _configuration_hash([]), "created_by_system_admin_user_id": session.user_id, "created_at": _iso(_now_dt()), "published_by_system_admin_user_id": None, "published_at": None, "rollback_of_version_id": None, "release_record_id": None, "release_status": None, "evaluation_run_id": None, "routes": []}
        self.versions[version_id] = version
        return self._finish_write(session, "llm.config.create_draft", "llm_config_version", version_id, reason, key, request_data, copy.deepcopy(version))

    def list_versions(self, session: SystemAdminSession, organization_id: str) -> list[dict[str, Any]]:
        return self.list_versions_page(session, organization_id, limit=100)["items"]

    def list_versions_page(self, session: SystemAdminSession, organization_id: str, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        limit = min(max(int(limit), 1), 100)
        scope_hash = _cursor_scope_hash(
            "config_versions",
            {"organization_id": organization_id, "sort": ["version_number:desc"]},
        )
        decoded = _decode_cursor(cursor, kind="config_versions", scope_hash=scope_hash)
        before = int(decoded["version_number"]) if decoded else None
        candidates = [
            item for item in sorted(self.versions.values(), key=lambda value: int(value["version_number"]), reverse=True)
            if item["organization_id"] == organization_id
            and (before is None or int(item["version_number"]) < before)
        ]
        selected = candidates[: limit + 1]
        has_more = len(selected) > limit
        items = selected[:limit]
        next_cursor = _encode_cursor({"version": 1, "kind": "config_versions", "scope_hash": scope_hash, "version_number": items[-1]["version_number"]}) if has_more else None
        return {"items": [copy.deepcopy(item) for item in items], "page_info": {"limit": limit, "has_more": has_more, "next_cursor": next_cursor}}

    def get_version(self, session: SystemAdminSession, version_id: str) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        version = self.versions.get(version_id)
        if not version:
            raise api_error(404, "config_version_not_found", "config version was not found")
        return copy.deepcopy(version)

    def replace_routes(self, session: SystemAdminSession, version_id: str, routes: list[dict[str, Any]], *, expected_revision: int, payload: dict[str, Any]) -> dict[str, Any]:
        clean_routes = _validate_route_collection(routes)
        scenarios = [route["scenario"] for route in clean_routes]
        if len(scenarios) != len(set(scenarios)):
            raise api_error(422, "duplicate_scenario", "each scenario may appear only once")
        request_data = {"version_id": version_id, "expected_revision": expected_revision, "routes": clean_routes}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.config.replace_routes", payload, request_data)
        if replay is not None:
            return replay
        version = self.versions.get(version_id)
        if not version:
            raise api_error(404, "config_version_not_found", "config version was not found")
        if version["status"] != "draft":
            raise api_error(409, "config_version_immutable", "routes can only be changed on a draft")
        if version["revision"] != expected_revision:
            raise api_error(409, "stale_revision", "config version revision is stale")
        for route in clean_routes:
            for provider_field in ("primary_provider_config_id", "fallback_provider_config_id"):
                provider_id = route.get(provider_field)
                if provider_id and provider_id not in self.providers:
                    raise api_error(422, "provider_not_found", "route references an unknown provider")
        version["routes"] = [{"route_id": str(uuid.uuid4()), **copy.deepcopy(route)} for route in clean_routes]
        version["configuration_hash"] = _configuration_hash(clean_routes)
        version["revision"] += 1
        return self._finish_write(session, "llm.config.replace_routes", "llm_config_version", version_id, reason, key, request_data, copy.deepcopy(version))

    def _ensure_version_ready(self, version: dict[str, Any], *, require_current_test: bool = True) -> None:
        _require_complete_scenarios(version["routes"])
        used_provider_ids = {
            str(route[field])
            for route in version["routes"]
            for field in ("primary_provider_config_id", "fallback_provider_config_id")
            if route.get(field)
        }
        for provider_id in used_provider_ids:
            provider = self.providers.get(provider_id)
            if not provider or not provider["enabled"] or provider["status"] != "active":
                raise api_error(409, "provider_not_ready", "all route providers must be enabled and active")
            tests = [
                item for item in self.connection_tests
                if item["provider_config_id"] == provider_id
                and item.get("config_version_id") == version["version_id"]
            ]
            if not tests or tests[-1]["status"] != "passed" or (require_current_test and tests[-1].get("provider_revision") != provider["revision"]):
                raise api_error(409, "provider_connection_test_required", "each route provider needs a passed connection test for this draft")

    def validate_draft(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        expected_revision = int(payload.get("expected_revision", 0))
        request_data = {"version_id": version_id, "expected_revision": expected_revision}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.config.validate", payload, request_data)
        if replay is not None:
            return replay
        version = self.versions.get(version_id)
        if not version or version["status"] != "draft" or version["revision"] != expected_revision:
            raise api_error(409, "stale_revision", "config version is not a matching draft")
        self._ensure_version_ready(version)
        version["status"] = "validated"
        version["revision"] += 1
        return self._finish_write(session, "llm.config.validate", "llm_config_version", version_id, reason, key, request_data, copy.deepcopy(version))

    def submit_publish(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        expected_revision = int(payload.get("expected_revision", 0))
        evaluation_run_id = _safe_evaluation_run_id(payload.get("evaluation_run_id"))
        request_data = {"version_id": version_id, "expected_revision": expected_revision, "evaluation_run_id": evaluation_run_id}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.config.submit_publish", payload, request_data)
        if replay is not None:
            return replay
        version = self.versions.get(version_id)
        if not version or version["status"] != "validated" or version["revision"] != expected_revision:
            raise api_error(409, "stale_revision", "config version is not a matching validated version")
        self._ensure_version_ready(version)
        version_snapshot = copy.deepcopy(version)
        try:
            gate = self._release_gate_checker(copy.deepcopy(version_snapshot), evaluation_run_id)
        except Exception:
            gate = {"status": "failed", "error_code": "release_gate_unavailable"}
        if self.versions.get(version_id) != version_snapshot:
            raise api_error(409, "draft_changed_during_release_gate", "config version changed while release evaluation was running")
        self._ensure_version_ready(version)
        if gate.get("status") != "passed":
            raise api_error(409, "release_gate_failed", "release evaluation gate did not pass")
        version["status"] = "pending_publish"
        version["revision"] += 1
        version["evaluation_run_id"] = evaluation_run_id
        release_id = str(uuid.uuid4())
        self.release_records[version_id] = {"release_record_id": release_id, "organization_id": version["organization_id"], "config_version_id": version_id, "evaluation_run_id": evaluation_run_id, "evaluation_config_version_id": version_id, "status": "pending", "revision": 1, "submitted_by_system_admin_user_id": session.user_id, "submitted_at": _iso(_now_dt()), "published_by_system_admin_user_id": None, "published_at": None, "rollback_of_release_id": None, "rollback_of_version_id": None}
        version["release_record_id"] = release_id
        version["release_status"] = "pending"
        return self._finish_write(session, "llm.config.submit_publish", "llm_config_version", version_id, reason, key, request_data, copy.deepcopy(version))

    def publish(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        expected_revision = int(payload.get("expected_revision", 0))
        request_data = {"version_id": version_id, "expected_revision": expected_revision}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.config.publish", payload, request_data)
        if replay is not None:
            return replay
        version = self.versions.get(version_id)
        if not version:
            raise api_error(404, "config_version_not_found", "config version was not found")
        if version["status"] != "pending_publish":
            raise api_error(409, "config_not_publishable", "only a pending publish version can be published")
        if version["revision"] != expected_revision:
            raise api_error(409, "stale_revision", "config version revision is stale")
        self._ensure_version_ready(version)
        for current in self.versions.values():
            if current["organization_id"] == version["organization_id"] and current["status"] == "running":
                current["status"] = "superseded"
                current["revision"] += 1
                release = self.release_records.get(current["version_id"])
                if release:
                    release["status"] = "superseded"
                    release["revision"] += 1
                    current["release_status"] = "superseded"
        version["status"] = "running"
        version["revision"] += 1
        version["published_by_system_admin_user_id"] = session.user_id
        version["published_at"] = _iso(_now_dt())
        release = self.release_records[version_id]
        release.update({"status": "running", "revision": release["revision"] + 1, "published_by_system_admin_user_id": session.user_id, "published_at": version["published_at"]})
        version["release_status"] = "running"
        response = copy.deepcopy(version)
        return self._finish_write(session, "llm.config.publish", "llm_config_version", version_id, reason, key, request_data, response)

    def rollback(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_data = {"version_id": version_id}
        reason, key, replay = self._begin_write(session, _WRITE_ROLES, "llm.config.rollback", payload, request_data)
        if replay is not None:
            return replay
        source = self.versions.get(version_id)
        if not source or source["status"] not in {"running", "superseded", "rolled_back"}:
            raise api_error(409, "rollback_source_invalid", "rollback source must be released history")
        self._ensure_version_ready(source, require_current_test=False)
        versions_before = copy.deepcopy(self.versions)
        releases_before = copy.deepcopy(self.release_records)
        try:
            for current in self.versions.values():
                if current["organization_id"] == source["organization_id"] and current["status"] == "running":
                    current["status"] = "superseded" if current["version_id"] == version_id else "rolled_back"
                    current["revision"] += 1
                    current_release = self.release_records.get(current["version_id"])
                    if current_release:
                        current_release["status"] = "superseded" if current["version_id"] == version_id else "rolled_back"
                        current_release["revision"] += 1
                        current["release_status"] = current_release["status"]
            number = max(int(v["version_number"]) for v in self.versions.values() if v["organization_id"] == source["organization_id"]) + 1
            new_id = str(uuid.uuid4())
            rolled_back = {"version_id": new_id, "organization_id": source["organization_id"], "version_number": number, "status": "running", "revision": 4, "description": f"Rollback of version {source['version_number']}", "configuration_hash": source["configuration_hash"], "created_by_system_admin_user_id": session.user_id, "created_at": _iso(_now_dt()), "published_by_system_admin_user_id": session.user_id, "published_at": _iso(_now_dt()), "rollback_of_version_id": version_id, "evaluation_run_id": source.get("evaluation_run_id"), "release_status": "running", "routes": copy.deepcopy(source["routes"])}
            self.versions[new_id] = rolled_back
            source_release = self.release_records.get(version_id)
            release_id = str(uuid.uuid4())
            self.release_records[new_id] = {"release_record_id": release_id, "organization_id": source["organization_id"], "config_version_id": new_id, "evaluation_run_id": source.get("evaluation_run_id"), "evaluation_config_version_id": version_id, "status": "running", "revision": 2, "submitted_by_system_admin_user_id": session.user_id, "submitted_at": rolled_back["created_at"], "published_by_system_admin_user_id": session.user_id, "published_at": rolled_back["published_at"], "rollback_of_release_id": source_release.get("release_record_id") if source_release else None, "rollback_of_version_id": version_id}
            rolled_back["release_record_id"] = release_id
            return self._finish_write(session, "llm.config.rollback", "llm_config_version", new_id, reason, key, request_data, copy.deepcopy(rolled_back))
        except Exception:
            self.versions = versions_before
            self.release_records = releases_before
            raise

    def _filtered_metrics(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        items = list(self.invocation_metrics)
        start_at, end_at = filters.get("start_at"), filters.get("end_at")
        if start_at:
            items = [item for item in items if item.get("occurred_at") >= start_at]
        if end_at:
            items = [item for item in items if item.get("occurred_at") < end_at]
        for key in ("provider_config_id", "model", "scenario", "organization_id", "store_id", "status", "route_role", "currency"):
            if filters.get(key) is not None:
                items = [item for item in items if item.get(key) == filters[key]]
        return items

    def usage_summary(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        items = self._filtered_metrics(session, filters)
        calls = len(items)
        latencies = sorted(int(item.get("latency_ms", 0)) for item in items)
        if calls:
            position = (calls - 1) * 0.95
            lower = math.floor(position)
            upper = math.ceil(position)
            p95 = latencies[lower] + (latencies[upper] - latencies[lower]) * (position - lower)
        else:
            p95 = None
        costs: dict[str, int] = {}
        for item in items:
            currency = str(item.get("currency") or "USD")
            costs[currency] = costs.get(currency, 0) + int(item.get("estimated_cost_micros", 0))
        estimated_cost = 0 if not costs else next(iter(costs.values())) if len(costs) == 1 else None
        return {"calls": calls, "input_tokens": sum(int(item.get("input_tokens", 0)) for item in items), "output_tokens": sum(int(item.get("output_tokens", 0)) for item in items), "total_tokens": sum(int(item.get("input_tokens", 0)) + int(item.get("output_tokens", 0)) for item in items), "estimated_cost_micros": estimated_cost, "cost_by_currency": costs, "p95_latency_ms": p95, "error_rate": sum(item.get("status") != "succeeded" for item in items) / calls if calls else None, "fallback_rate": sum(item.get("route_role") == "fallback" for item in items) / calls if calls else None}

    def usage_timeseries(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in self._filtered_metrics(session, filters):
            occurred = item.get("occurred_at")
            if isinstance(occurred, str):
                occurred = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
            bucket = occurred.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
            buckets.setdefault(f"{bucket}|{item.get('currency') or 'USD'}", []).append(item)
        return [{"bucket": key.rsplit("|", 1)[0], "currency": key.rsplit("|", 1)[1], "calls": len(items), "input_tokens": sum(int(x.get("input_tokens", 0)) for x in items), "output_tokens": sum(int(x.get("output_tokens", 0)) for x in items), "estimated_cost_micros": sum(int(x.get("estimated_cost_micros", 0)) for x in items), "errors": sum(x.get("status") != "succeeded" for x in items)} for key, items in sorted(buckets.items())]

    def usage_breakdown(self, session: SystemAdminSession, filters: dict[str, Any], group_by: str) -> list[dict[str, Any]]:
        field = {"provider": "provider_name", "model": "model", "scenario": "scenario", "organization": "organization_id", "store": "store_id", "status": "status", "error_code": "error_code"}.get(group_by)
        if not field:
            raise api_error(422, "invalid_usage_group", "unsupported usage breakdown dimension")
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in self._filtered_metrics(session, filters):
            key = f"{str(item.get(field) or 'unknown')}|{item.get('currency') or 'USD'}"
            groups.setdefault(key, []).append(item)
        return [{"key": key.rsplit("|", 1)[0], "currency": key.rsplit("|", 1)[1], "calls": len(items), "total_tokens": sum(int(x.get("input_tokens", 0)) + int(x.get("output_tokens", 0)) for x in items), "estimated_cost_micros": sum(int(x.get("estimated_cost_micros", 0)) for x in items)} for key, items in sorted(groups.items())]

    def list_invocations(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return self.list_invocations_page(session, filters)["items"]

    def list_invocations_page(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(filters.get("limit", 100)), 1), 500)
        scope_hash = _cursor_scope_hash("invocations", _invocation_cursor_scope(filters))
        decoded = _decode_cursor(filters.get("cursor"), kind="invocations", scope_hash=scope_hash)
        items = sorted(
            self._filtered_metrics(session, filters),
            key=lambda item: (str(_iso(item.get("occurred_at"))), str(item.get("invocation_id"))),
            reverse=True,
        )
        if decoded:
            boundary = (str(decoded["occurred_at"]), str(decoded["id"]))
            items = [item for item in items if (str(_iso(item.get("occurred_at"))), str(item.get("invocation_id"))) < boundary]
        selected = items[: limit + 1]
        has_more = len(selected) > limit
        page_items = selected[:limit]
        next_cursor = None
        if has_more:
            last = page_items[-1]
            next_cursor = _encode_cursor({"version": 1, "kind": "invocations", "scope_hash": scope_hash, "occurred_at": _iso(last.get("occurred_at")), "id": last.get("invocation_id")})
        return {"items": [_public_invocation(item) for item in page_items], "page_info": {"limit": limit, "has_more": has_more, "next_cursor": next_cursor}}


class PostgresLlmGovernanceRepository:
    def __init__(
        self,
        database_url: str,
        connection_tester: Callable[[dict[str, Any], dict[str, int]], dict[str, Any]] | None = None,
        release_gate_checker: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
    ) -> None:
        import psycopg
        self._connect = psycopg.connect
        self._database_url = database_url
        self._connection_tester = connection_tester or (
            lambda _provider, _request: {
                "status": "failed",
                "latency_ms": 0,
                "error_code": "tester_unavailable",
            }
        )
        self._release_gate_checker = release_gate_checker or (
            lambda _version, _evaluation_run_id: {"status": "failed", "error_code": "release_gate_unavailable"}
        )

    @staticmethod
    def _map_postgres_error(exc: Exception) -> Exception:
        if getattr(exc, "status_code", None) is not None:
            return exc
        sqlstate = getattr(exc, "sqlstate", None)
        constraint = str(getattr(getattr(exc, "diag", None), "constraint_name", "") or "")
        if sqlstate == "23505" and "provider" in constraint:
            return api_error(409, "provider_name_conflict", "provider name already exists")
        if sqlstate == "23505":
            return api_error(409, "governance_conflict", "LLM governance record conflicts with existing state")
        if sqlstate == "23503":
            return api_error(422, "invalid_governance_reference", "referenced governance resource does not exist")
        if sqlstate in {"22P02", "22001"}:
            return api_error(422, "invalid_governance_input", "governance identifier or text input is invalid")
        if sqlstate == "23514":
            return api_error(409, "invalid_governance_state", "LLM governance state transition was rejected")
        return api_error(500, "governance_database_error", "LLM governance database operation failed")

    def _transaction(self, operation: Callable[[Any], dict[str, Any] | list[dict[str, Any]]]) -> Any:
        conn = None
        try:
            conn = self._connect(self._database_url)
            with conn.cursor() as cur:
                result = operation(cur)
            conn.commit()
            return result
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            mapped = self._map_postgres_error(exc)
            if mapped is exc:
                raise
            raise mapped from exc
        finally:
            if conn is not None:
                conn.close()

    def _read(self, operation: Callable[[Any], Any]) -> Any:
        conn = None
        try:
            conn = self._connect(self._database_url)
            with conn.cursor() as cur:
                return operation(cur)
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            mapped = self._map_postgres_error(exc)
            if mapped is exc:
                raise
            raise mapped from exc
        finally:
            if conn is not None:
                conn.close()

    def _find_idempotency(self, cur: Any, action: str, key: str, request_data: Any) -> dict[str, Any] | None:
        # Serialize same-key writers before reading the unique audit record so concurrent
        # retries replay instead of surfacing a database uniqueness error.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"llm_idempotency:{action}:{key}",),
        )
        cur.execute("SELECT object_id, diff_summary->>'request_hash', diff_summary->'response_snapshot' FROM system_admin_audit_log WHERE action = %s AND idempotency_key = %s ORDER BY created_at LIMIT 1", (action, key))
        row = cur.fetchone()
        if not row:
            return None
        if str(row[1] or "") != _fingerprint(request_data):
            raise api_error(409, "idempotency_conflict", "idempotency key was already used with a different request")
        return {"object_id": str(row[0]), "response": copy.deepcopy(row[2])}

    def _audit(self, cur: Any, session: SystemAdminSession, action: str, object_type: str, object_id: str, reason: str, key: str, request_data: Any, response: dict[str, Any]) -> None:
        safe_snapshot = _bounded_snapshot(response)
        cur.execute("INSERT INTO system_admin_audit_log (id, system_admin_user_id, action, object_type, object_id, diff_summary, idempotency_key) VALUES (%s, %s, %s, %s, %s, %s, %s)", (str(uuid.uuid4()), session.user_id, action, object_type, object_id, Jsonb({"reason": reason, "request_hash": _fingerprint(request_data), "response_snapshot": safe_snapshot}), key))

    @staticmethod
    def _provider_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = ("provider_id", "name", "provider_type", "base_url", "secret_namespace", "secret_name", "secret_key", "enabled", "status", "last_connection_test_status", "last_connection_test_latency_ms", "last_connection_test_error_code", "last_connection_tested_at", "created_at", "updated_at", "revision")
        value = dict(zip(keys, row))
        for field in ("last_connection_tested_at", "created_at", "updated_at"):
            value[field] = _iso(value[field])
        return _public_provider(value)

    def list_providers(self, session: SystemAdminSession) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        def op(cur: Any) -> list[dict[str, Any]]:
            cur.execute("SELECT id::text, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status, last_connection_test_status, last_connection_test_latency_ms, last_connection_test_error_code, last_connection_tested_at, created_at, updated_at, revision FROM llm_provider_config ORDER BY name")
            return [self._provider_from_row(row) for row in cur.fetchall()]
        return self._read(op)

    def create_provider(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        data = _validate_provider_input(payload)
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.provider.create", key, data)
            if replay:
                return replay["response"]
            provider_id = str(uuid.uuid4())
            enabled = data.get("enabled", True)
            cur.execute("INSERT INTO llm_provider_config (id, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id::text, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status, last_connection_test_status, last_connection_test_latency_ms, last_connection_test_error_code, last_connection_tested_at, created_at, updated_at, revision", (provider_id, data["name"], data["provider_type"], data["base_url"], data["secret_namespace"], data["secret_name"], data["secret_key"], enabled, "active" if enabled else "disabled"))
            result = self._provider_from_row(cur.fetchone())
            self._audit(cur, session, "llm.provider.create", "llm_provider_config", provider_id, reason, key, data, result)
            return result
        return self._transaction(op)

    def update_provider(self, session: SystemAdminSession, provider_id: str, payload: dict[str, Any], *, expected_revision: int) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        data = _validate_provider_input(payload, partial=True)
        def op(cur: Any) -> dict[str, Any]:
            request_data = {"provider_id": provider_id, "expected_revision": expected_revision, "changes": data}
            replay = self._find_idempotency(cur, "llm.provider.update", key, request_data)
            if replay and replay["object_id"] != provider_id:
                raise api_error(409, "idempotency_conflict", "idempotency key belongs to another provider")
            if replay:
                return replay["response"]
            cur.execute("SELECT id::text, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status, last_connection_test_status, last_connection_test_latency_ms, last_connection_test_error_code, last_connection_tested_at, created_at, updated_at, revision FROM llm_provider_config WHERE id=%s FOR UPDATE", (provider_id,))
            current_row = cur.fetchone()
            if not current_row:
                raise api_error(404, "provider_not_found", "provider was not found")
            current = self._provider_from_row(current_row)
            immutable_values = {"provider_type": current["provider_type"], "base_url": current["base_url"], "secret_namespace": current["secret_ref"]["namespace"], "secret_name": current["secret_ref"]["name"], "secret_key": current["secret_ref"]["key"]}
            for field, value in immutable_values.items():
                if field in data and data[field] != value:
                    raise api_error(409, "provider_endpoint_immutable", "provider endpoint and Secret reference are immutable; create a new Provider")
            if not any(field in data for field in ("name", "enabled")):
                raise api_error(422, "provider_update_empty", "only provider name and enabled state may be updated")
            assignments, params = [], []
            for field in ("name", "enabled"):
                if field in data:
                    assignments.append(f"{field} = %s")
                    params.append(data[field])
            if "enabled" in data:
                assignments.append("status = %s")
                params.append("active" if data["enabled"] else "disabled")
            assignments.extend(["revision = revision + 1", "updated_at = now()"])
            params.extend([provider_id, expected_revision])
            cur.execute(f"UPDATE llm_provider_config SET {', '.join(assignments)} WHERE id = %s AND revision = %s RETURNING id::text, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status, last_connection_test_status, last_connection_test_latency_ms, last_connection_test_error_code, last_connection_tested_at, created_at, updated_at, revision", tuple(params))
            row = cur.fetchone()
            if not row:
                raise api_error(409, "stale_revision", "provider revision is stale or provider was not found")
            result = self._provider_from_row(row)
            self._audit(cur, session, "llm.provider.update", "llm_provider_config", provider_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def test_connection(self, session: SystemAdminSession, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _CONNECTION_TEST_ROLES)
        reason, key = _require_write(payload)
        request = _validate_connection_request(payload)
        config_version_id = payload.get("config_version_id")
        request_data = {"provider_id": provider_id, **request, "config_version_id": config_version_id}
        def preload(cur: Any) -> dict[str, Any]:
            cur.execute("SELECT diff_summary->>'request_hash', diff_summary->'response_snapshot' FROM system_admin_audit_log WHERE action='llm.provider.connection_test' AND idempotency_key=%s", (key,))
            replay = cur.fetchone()
            if replay:
                if str(replay[0] or "") != _fingerprint(request_data):
                    raise api_error(409, "idempotency_conflict", "idempotency key was already used with a different request")
                return {"replay": copy.deepcopy(replay[1])}
            cur.execute("SELECT id::text, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status, last_connection_test_status, last_connection_test_latency_ms, last_connection_test_error_code, last_connection_tested_at, created_at, updated_at, revision FROM llm_provider_config WHERE id=%s", (provider_id,))
            provider_row = cur.fetchone()
            if not provider_row:
                raise api_error(404, "provider_not_found", "provider was not found")
            version_snapshot = None
            if config_version_id:
                cur.execute("SELECT status, revision, configuration_hash FROM llm_config_version WHERE id=%s", (config_version_id,))
                version_snapshot = cur.fetchone()
                if not version_snapshot or version_snapshot[0] != "draft":
                    raise api_error(409, "connection_test_requires_draft", "connection tests may only target an existing draft")
            return {"provider": self._provider_from_row(provider_row), "version": version_snapshot}
        snapshot = self._read(preload)
        if snapshot.get("replay") is not None:
            return snapshot["replay"]
        try:
            raw = self._connection_tester(copy.deepcopy(snapshot["provider"]), request)
        except Exception:
            raw = {"status": "failed", "latency_ms": 0, "error_code": "tester_unavailable"}
        status = "passed" if raw.get("status") == "passed" else "failed"
        latency_ms = max(0, int(raw.get("latency_ms") or 0))
        error_code = _sanitize_error_code(raw.get("error_code")) if status == "failed" else None
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.provider.connection_test", key, request_data)
            if replay:
                return replay["response"]
            cur.execute("SELECT id::text, name, provider_type, base_url, secret_namespace, secret_name, secret_key, enabled, status, last_connection_test_status, last_connection_test_latency_ms, last_connection_test_error_code, last_connection_tested_at, created_at, updated_at, revision FROM llm_provider_config WHERE id=%s FOR UPDATE", (provider_id,))
            provider_row = cur.fetchone()
            current_provider = self._provider_from_row(provider_row) if provider_row else None
            if not current_provider or current_provider["revision"] != snapshot["provider"]["revision"]:
                raise api_error(409, "provider_changed_during_test", "provider changed while the connection test was running")
            if config_version_id:
                cur.execute("SELECT status, revision, configuration_hash FROM llm_config_version WHERE id=%s FOR UPDATE", (config_version_id,))
                version_row = cur.fetchone()
                if tuple(version_row or ()) != tuple(snapshot["version"] or ()):
                    raise api_error(409, "draft_changed_during_test", "draft changed while the connection test was running")
            cur.execute("UPDATE llm_provider_config SET last_connection_test_status=%s, last_connection_test_latency_ms=%s, last_connection_test_error_code=%s, last_connection_tested_at=now(), status=CASE WHEN enabled THEN %s ELSE 'disabled' END, revision=revision+1, updated_at=now() WHERE id=%s AND revision=%s RETURNING revision", (status, latency_ms, error_code, "active" if status == "passed" else "unhealthy", provider_id, snapshot["provider"]["revision"]))
            new_provider_revision = int(cur.fetchone()[0])
            test_id = str(uuid.uuid4())
            cur.execute("INSERT INTO llm_connection_test (id, provider_config_id, config_version_id, provider_revision, checked_by_system_admin_user_id, status, latency_ms, error_code, redacted_error_message) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id::text, provider_config_id::text, config_version_id::text, provider_revision, status, latency_ms, checked_at, error_code, redacted_error_message", (test_id, provider_id, config_version_id, new_provider_revision, session.user_id, status, latency_ms, error_code, _redacted_error_message(error_code)))
            result = _connection_test_from_row(cur.fetchone())
            self._audit(cur, session, "llm.provider.connection_test", "llm_connection_test", test_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def create_draft(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        organization_id = _bounded_text(payload.get("organization_id"), "organization_id", 128)
        if not organization_id:
            raise api_error(422, "organization_required", "organization_id is required")
        description = _bounded_text(payload.get("description"), "description", 512, required=False) or None
        def op(cur: Any) -> dict[str, Any]:
            request_data = {"organization_id": organization_id, "description": description}
            replay = self._find_idempotency(cur, "llm.config.create_draft", key, request_data)
            if replay:
                return replay["response"]
            version_id = str(uuid.uuid4())
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"llm_version_number:{organization_id}",))
            cur.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM llm_config_version WHERE organization_id=%s", (organization_id,))
            version_number = int(cur.fetchone()[0])
            cur.execute("INSERT INTO llm_config_version (id, organization_id, version_number, description, configuration_hash, created_by_system_admin_user_id) VALUES (%s,%s,%s,%s,%s,%s)", (version_id, organization_id, version_number, description, _configuration_hash([]), session.user_id))
            result = self._fetch_version(cur, version_id)
            self._audit(cur, session, "llm.config.create_draft", "llm_config_version", version_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def list_versions(self, session: SystemAdminSession, organization_id: str) -> list[dict[str, Any]]:
        return self.list_versions_page(session, organization_id, limit=100)["items"]

    def list_versions_page(self, session: SystemAdminSession, organization_id: str, *, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        limit = min(max(int(limit), 1), 100)
        scope_hash = _cursor_scope_hash(
            "config_versions",
            {"organization_id": organization_id, "sort": ["version_number:desc"]},
        )
        decoded = _decode_cursor(cursor, kind="config_versions", scope_hash=scope_hash)
        before = int(decoded["version_number"]) if decoded else None
        def op(cur: Any) -> dict[str, Any]:
            cur.execute(
                "SELECT id::text, version_number FROM llm_config_version WHERE organization_id=%s "
                "AND (%s::bigint IS NULL OR version_number < %s::bigint) ORDER BY version_number DESC LIMIT %s",
                (organization_id, before, before, limit + 1),
            )
            rows = cur.fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            items = [self._fetch_version(cur, str(row[0])) for row in rows]
            next_cursor = _encode_cursor({"version": 1, "kind": "config_versions", "scope_hash": scope_hash, "version_number": int(rows[-1][1])}) if has_more else None
            return {"items": items, "page_info": {"limit": limit, "has_more": has_more, "next_cursor": next_cursor}}
        return self._read(op)

    def get_version(self, session: SystemAdminSession, version_id: str) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        return self._read(lambda cur: self._fetch_version(cur, version_id))

    def _fetch_version(self, cur: Any, version_id: str, *, lock: bool = False) -> dict[str, Any]:
        cur.execute("SELECT id::text, organization_id::text, version_number, status, revision, description, configuration_hash, created_by_system_admin_user_id::text, created_at, published_by_system_admin_user_id::text, published_at, rollback_of_version_id::text FROM llm_config_version WHERE id=%s" + (" FOR UPDATE" if lock else ""), (version_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "config_version_not_found", "config version was not found")
        keys = ("version_id", "organization_id", "version_number", "status", "revision", "description", "configuration_hash", "created_by_system_admin_user_id", "created_at", "published_by_system_admin_user_id", "published_at", "rollback_of_version_id")
        version = dict(zip(keys, row))
        version["created_at"], version["published_at"] = _iso(version["created_at"]), _iso(version["published_at"])
        cur.execute("SELECT id::text, scenario, primary_provider_config_id::text, primary_model, fallback_provider_config_id::text, fallback_model, enabled, temperature, max_output_tokens, timeout_seconds, max_retries, circuit_breaker_threshold, recovery_probe_seconds, revision FROM llm_scenario_route WHERE config_version_id=%s ORDER BY scenario", (version_id,))
        route_keys = ("route_id", "scenario", "primary_provider_config_id", "primary_model", "fallback_provider_config_id", "fallback_model", "enabled", "temperature", "max_output_tokens", "timeout_seconds", "max_retries", "circuit_breaker_threshold", "recovery_probe_seconds", "revision")
        version["routes"] = [{**dict(zip(route_keys, route)), "temperature": float(route[7])} for route in cur.fetchall()]
        cur.execute("SELECT id::text, evaluation_run_id, status FROM llm_release_record WHERE config_version_id=%s", (version_id,))
        release_row = cur.fetchone()
        version["release_record_id"] = str(release_row[0]) if release_row else None
        version["evaluation_run_id"] = str(release_row[1]) if release_row else None
        version["release_status"] = str(release_row[2]) if release_row else None
        return version

    def replace_routes(self, session: SystemAdminSession, version_id: str, routes: list[dict[str, Any]], *, expected_revision: int, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        clean = _validate_route_collection(routes)
        if len({route["scenario"] for route in clean}) != len(clean):
            raise api_error(422, "duplicate_scenario", "each scenario may appear only once")
        request_data = {"version_id": version_id, "expected_revision": expected_revision, "routes": clean}
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.config.replace_routes", key, request_data)
            if replay:
                return replay["response"]
            version = self._fetch_version(cur, version_id, lock=True)
            if version["status"] != "draft" or version["revision"] != expected_revision:
                raise api_error(409, "stale_revision", "config version is not an editable matching draft")
            cur.execute("DELETE FROM llm_scenario_route WHERE config_version_id=%s", (version_id,))
            for route in clean:
                cur.execute("INSERT INTO llm_scenario_route (config_version_id, scenario, primary_provider_config_id, primary_model, fallback_provider_config_id, fallback_model, enabled, temperature, max_output_tokens, timeout_seconds, max_retries, circuit_breaker_threshold, recovery_probe_seconds) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (version_id, route["scenario"], route["primary_provider_config_id"], route["primary_model"], route["fallback_provider_config_id"], route["fallback_model"], route["enabled"], route["temperature"], route["max_output_tokens"], route["timeout_seconds"], route["max_retries"], route["circuit_breaker_threshold"], route["recovery_probe_seconds"]))
            cur.execute("UPDATE llm_config_version SET configuration_hash=%s, revision=revision+1 WHERE id=%s AND revision=%s", (_configuration_hash(clean), version_id, expected_revision))
            result = self._fetch_version(cur, version_id)
            self._audit(cur, session, "llm.config.replace_routes", "llm_config_version", version_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def _ensure_version_ready_pg(self, cur: Any, version: dict[str, Any], *, require_current_test: bool = True) -> None:
        _require_complete_scenarios(version["routes"])
        provider_ids = {
            str(route[field])
            for route in version["routes"]
            for field in ("primary_provider_config_id", "fallback_provider_config_id")
            if route.get(field)
        }
        for provider_id in provider_ids:
            cur.execute("SELECT enabled, status, revision FROM llm_provider_config WHERE id=%s FOR KEY SHARE", (provider_id,))
            provider = cur.fetchone()
            if not provider or not provider[0] or provider[1] != "active":
                raise api_error(409, "provider_not_ready", "all route providers must be enabled and active")
            cur.execute("SELECT status, provider_revision FROM llm_connection_test WHERE provider_config_id=%s AND config_version_id=%s ORDER BY checked_at DESC, id DESC LIMIT 1", (provider_id, version["version_id"]))
            tested = cur.fetchone()
            if not tested or tested[0] != "passed" or (require_current_test and int(tested[1]) != int(provider[2])):
                raise api_error(409, "provider_connection_test_required", "each route provider needs a passed connection test for this draft")

    def validate_draft(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        expected_revision = int(payload.get("expected_revision", 0))
        request_data = {"version_id": version_id, "expected_revision": expected_revision}
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.config.validate", key, request_data)
            if replay:
                return replay["response"]
            version = self._fetch_version(cur, version_id, lock=True)
            if version["status"] != "draft" or version["revision"] != expected_revision:
                raise api_error(409, "stale_revision", "config version is not a matching draft")
            self._ensure_version_ready_pg(cur, version)
            cur.execute("UPDATE llm_config_version SET status='validated', revision=revision+1 WHERE id=%s AND status='draft' AND revision=%s", (version_id, expected_revision))
            result = self._fetch_version(cur, version_id)
            self._audit(cur, session, "llm.config.validate", "llm_config_version", version_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def submit_publish(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        expected_revision = int(payload.get("expected_revision", 0))
        evaluation_run_id = _safe_evaluation_run_id(payload.get("evaluation_run_id"))
        request_data = {"version_id": version_id, "expected_revision": expected_revision, "evaluation_run_id": evaluation_run_id}
        def preload(cur: Any) -> dict[str, Any]:
            cur.execute("SELECT diff_summary->>'request_hash', diff_summary->'response_snapshot' FROM system_admin_audit_log WHERE action='llm.config.submit_publish' AND idempotency_key=%s", (key,))
            replay = cur.fetchone()
            if replay:
                if str(replay[0] or "") != _fingerprint(request_data):
                    raise api_error(409, "idempotency_conflict", "idempotency key was already used with a different request")
                return {"replay": copy.deepcopy(replay[1])}
            return {"version": self._fetch_version(cur, version_id)}
        snapshot = self._read(preload)
        if snapshot.get("replay") is not None:
            return snapshot["replay"]
        candidate = snapshot["version"]
        if candidate["status"] != "validated" or candidate["revision"] != expected_revision:
            raise api_error(409, "stale_revision", "config version is not a matching validated version")
        try:
            gate = self._release_gate_checker(copy.deepcopy(candidate), evaluation_run_id)
        except Exception:
            gate = {"status": "failed", "error_code": "release_gate_unavailable"}
        if gate.get("status") != "passed":
            raise api_error(409, "release_gate_failed", "release evaluation gate did not pass")
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.config.submit_publish", key, request_data)
            if replay:
                return replay["response"]
            version = self._fetch_version(cur, version_id, lock=True)
            if version["status"] != "validated" or version["revision"] != expected_revision or version["configuration_hash"] != candidate["configuration_hash"]:
                raise api_error(409, "stale_revision", "config version is not a matching validated version")
            self._ensure_version_ready_pg(cur, version)
            cur.execute("UPDATE llm_config_version SET status='pending_publish', revision=revision+1 WHERE id=%s AND status='validated' AND revision=%s", (version_id, expected_revision))
            cur.execute("INSERT INTO llm_release_record (organization_id, config_version_id, evaluation_run_id, evaluation_config_version_id, submitted_by_system_admin_user_id) VALUES (%s,%s,%s,%s,%s)", (version["organization_id"], version_id, evaluation_run_id, version_id, session.user_id))
            result = self._fetch_version(cur, version_id)
            self._audit(cur, session, "llm.config.submit_publish", "llm_config_version", version_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def publish(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        expected_revision = int(payload.get("expected_revision", 0))
        request_data = {"version_id": version_id, "expected_revision": expected_revision}
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.config.publish", key, request_data)
            if replay:
                return replay["response"]
            cur.execute("SELECT organization_id::text FROM llm_config_version WHERE id=%s", (version_id,))
            organization_row = cur.fetchone()
            if not organization_row:
                raise api_error(404, "config_version_not_found", "config version was not found")
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"llm_publish:{organization_row[0]}",))
            target = self._fetch_version(cur, version_id, lock=True)
            if target["status"] != "pending_publish" or target["revision"] != expected_revision:
                raise api_error(409, "config_not_publishable", "config must be a matching pending publish version")
            self._ensure_version_ready_pg(cur, target)
            cur.execute("SELECT id::text FROM llm_config_version WHERE organization_id=%s AND status='running' FOR UPDATE", (target["organization_id"],))
            running = [str(row[0]) for row in cur.fetchall()]
            for current_id in running:
                cur.execute("UPDATE llm_config_version SET status='superseded', revision=revision+1 WHERE id=%s", (current_id,))
                cur.execute("UPDATE llm_release_record SET status='superseded', revision=revision+1 WHERE config_version_id=%s AND status='running'", (current_id,))
            cur.execute("UPDATE llm_config_version SET status='running', revision=revision+1, published_by_system_admin_user_id=%s, published_at=now() WHERE id=%s", (session.user_id, version_id))
            cur.execute("UPDATE llm_release_record SET status='running', revision=revision+1, published_by_system_admin_user_id=%s, published_at=now() WHERE config_version_id=%s AND status='pending'", (session.user_id, version_id))
            result = self._fetch_version(cur, version_id)
            self._audit(cur, session, "llm.config.publish", "llm_config_version", version_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    def rollback(self, session: SystemAdminSession, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        reason, key = _require_write(payload)
        request_data = {"version_id": version_id}
        def op(cur: Any) -> dict[str, Any]:
            replay = self._find_idempotency(cur, "llm.config.rollback", key, request_data)
            if replay:
                return replay["response"]
            cur.execute("SELECT organization_id::text FROM llm_config_version WHERE id=%s", (version_id,))
            organization_row = cur.fetchone()
            if not organization_row:
                raise api_error(404, "config_version_not_found", "config version was not found")
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"llm_publish:{organization_row[0]}",))
            source = self._fetch_version(cur, version_id, lock=True)
            if source["status"] not in {"running", "superseded", "rolled_back"}:
                raise api_error(409, "rollback_source_invalid", "rollback source must be released history")
            self._ensure_version_ready_pg(cur, source, require_current_test=False)
            cur.execute("SELECT id::text FROM llm_config_version WHERE organization_id=%s AND status='running' FOR UPDATE", (source["organization_id"],))
            running = [str(row[0]) for row in cur.fetchall()]
            for current_id in running:
                terminal_status = "superseded" if current_id == version_id else "rolled_back"
                cur.execute("UPDATE llm_config_version SET status=%s, revision=revision+1 WHERE id=%s", (terminal_status, current_id))
                cur.execute("UPDATE llm_release_record SET status=%s, revision=revision+1 WHERE config_version_id=%s AND status='running'", (terminal_status, current_id))
            new_id = str(uuid.uuid4())
            cur.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM llm_config_version WHERE organization_id=%s", (source["organization_id"],))
            number = int(cur.fetchone()[0])
            cur.execute("INSERT INTO llm_config_version (id, organization_id, version_number, description, configuration_hash, created_by_system_admin_user_id, rollback_of_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", (new_id, source["organization_id"], number, f"Rollback of version {source['version_number']}", source["configuration_hash"], session.user_id, version_id))
            cur.execute("INSERT INTO llm_release_record (organization_id, config_version_id, evaluation_run_id, evaluation_config_version_id, submitted_by_system_admin_user_id, rollback_of_release_id, rollback_of_version_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", (source["organization_id"], new_id, source["evaluation_run_id"], version_id, session.user_id, source.get("release_record_id"), version_id))
            cur.execute("INSERT INTO llm_scenario_route (config_version_id, scenario, primary_provider_config_id, primary_model, fallback_provider_config_id, fallback_model, enabled, temperature, max_output_tokens, timeout_seconds, max_retries, circuit_breaker_threshold, recovery_probe_seconds) SELECT %s, scenario, primary_provider_config_id, primary_model, fallback_provider_config_id, fallback_model, enabled, temperature, max_output_tokens, timeout_seconds, max_retries, circuit_breaker_threshold, recovery_probe_seconds FROM llm_scenario_route WHERE config_version_id=%s", (new_id, version_id))
            for state in ("validated", "pending_publish"):
                cur.execute("UPDATE llm_config_version SET status=%s, revision=revision+1 WHERE id=%s", (state, new_id))
            cur.execute("UPDATE llm_config_version SET status='running', revision=revision+1, published_by_system_admin_user_id=%s, published_at=now() WHERE id=%s", (session.user_id, new_id))
            cur.execute("UPDATE llm_release_record SET status='running', revision=revision+1, published_by_system_admin_user_id=%s, published_at=now() WHERE config_version_id=%s AND status='pending'", (session.user_id, new_id))
            result = self._fetch_version(cur, new_id)
            self._audit(cur, session, "llm.config.rollback", "llm_config_version", new_id, reason, key, request_data, result)
            return result
        return self._transaction(op)

    @staticmethod
    def _usage_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
        clauses, params = [], []
        columns = {"start_at": "metric.occurred_at >=", "end_at": "metric.occurred_at <", "provider_config_id": "COALESCE(CASE WHEN metric.route_role='fallback' THEN route.fallback_provider_config_id ELSE route.primary_provider_config_id END, route.primary_provider_config_id) =", "model": "CASE WHEN metric.route_role='fallback' THEN route.fallback_model ELSE route.primary_model END =", "scenario": "route.scenario =", "organization_id": "metric.organization_id =", "store_id": "metric.store_id =", "status": "metric.status =", "route_role": "metric.route_role =", "currency": "metric.currency ="}
        for key, expression in columns.items():
            if filters.get(key) is not None:
                clauses.append(f"{expression} %s")
                params.append(filters[key])
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params

    @staticmethod
    def _usage_from() -> str:
        return " FROM llm_invocation_metric metric JOIN llm_scenario_route route ON route.id=metric.scenario_route_id JOIN llm_provider_config provider ON provider.id=CASE WHEN metric.route_role='fallback' THEN route.fallback_provider_config_id ELSE route.primary_provider_config_id END "

    def usage_summary(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        where, params = self._usage_where(filters)
        def op(cur: Any) -> dict[str, Any]:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(input_tokens+output_tokens),0), percentile_cont(.95) WITHIN GROUP (ORDER BY latency_ms), COUNT(*) FILTER (WHERE metric.status<>'succeeded')::float/NULLIF(COUNT(*),0), COUNT(*) FILTER (WHERE route_role='fallback')::float/NULLIF(COUNT(*),0)" + self._usage_from() + where, tuple(params))
            row = cur.fetchone()
            cur.execute("SELECT metric.currency, SUM(metric.estimated_cost_micros)" + self._usage_from() + where + " GROUP BY metric.currency ORDER BY metric.currency", tuple(params))
            costs = {str(cost[0]): int(cost[1]) for cost in cur.fetchall()}
            estimated_cost = 0 if not costs else next(iter(costs.values())) if len(costs) == 1 else None
            return {"calls": int(row[0]), "input_tokens": int(row[1]), "output_tokens": int(row[2]), "total_tokens": int(row[3]), "estimated_cost_micros": estimated_cost, "cost_by_currency": costs, "p95_latency_ms": float(row[4]) if row[4] is not None else None, "error_rate": float(row[5]) if row[5] is not None else None, "fallback_rate": float(row[6]) if row[6] is not None else None}
        return self._read(op)

    def usage_timeseries(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        where, params = self._usage_where(filters)
        def op(cur: Any) -> list[dict[str, Any]]:
            cur.execute("SELECT date_trunc('hour', occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC', metric.currency, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(estimated_cost_micros), COUNT(*) FILTER (WHERE metric.status<>'succeeded')" + self._usage_from() + where + " GROUP BY 1,2 ORDER BY 1,2", tuple(params))
            return [{"bucket": _iso(row[0]), "currency": str(row[1]), "calls": int(row[2]), "input_tokens": int(row[3]), "output_tokens": int(row[4]), "estimated_cost_micros": int(row[5]), "errors": int(row[6])} for row in cur.fetchall()]
        return self._read(op)

    def usage_breakdown(self, session: SystemAdminSession, filters: dict[str, Any], group_by: str) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        dimensions = {"provider": "provider.name", "model": "CASE WHEN metric.route_role='fallback' THEN route.fallback_model ELSE route.primary_model END", "scenario": "route.scenario", "organization": "metric.organization_id::text", "store": "metric.store_id::text", "status": "metric.status", "error_code": "metric.error_code"}
        dimension = dimensions.get(group_by)
        if not dimension:
            raise api_error(422, "invalid_usage_group", "unsupported usage breakdown dimension")
        where, params = self._usage_where(filters)
        def op(cur: Any) -> list[dict[str, Any]]:
            cur.execute(f"SELECT COALESCE({dimension}, 'unknown'), metric.currency, COUNT(*), SUM(input_tokens+output_tokens), SUM(estimated_cost_micros)" + self._usage_from() + where + " GROUP BY 1,2 ORDER BY 3 DESC", tuple(params))
            return [{"key": str(row[0]), "currency": str(row[1]), "calls": int(row[2]), "total_tokens": int(row[3]), "estimated_cost_micros": int(row[4])} for row in cur.fetchall()]
        return self._read(op)

    def list_invocations(self, session: SystemAdminSession, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return self.list_invocations_page(session, filters)["items"]

    def list_invocations_page(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        where, params = self._usage_where(filters)
        limit = min(max(int(filters.get("limit", 100)), 1), 500)
        scope_hash = _cursor_scope_hash("invocations", _invocation_cursor_scope(filters))
        decoded = _decode_cursor(filters.get("cursor"), kind="invocations", scope_hash=scope_hash)
        if decoded:
            cursor_clause = "(metric.occurred_at, metric.id) < (%s::timestamptz, %s::uuid)"
            where += (" AND " if where else " WHERE ") + cursor_clause
            params.extend([decoded.get("occurred_at"), decoded.get("id")])
        def op(cur: Any) -> dict[str, Any]:
            cur.execute("SELECT metric.id::text, metric.occurred_at, provider.id::text, provider.name, CASE WHEN metric.route_role='fallback' THEN route.fallback_model ELSE route.primary_model END, route.scenario, metric.organization_id::text, metric.store_id::text, metric.route_role, metric.input_tokens, metric.output_tokens, metric.latency_ms, metric.status, metric.error_code, metric.estimated_cost_micros, metric.currency" + self._usage_from() + where + " ORDER BY metric.occurred_at DESC, metric.id DESC LIMIT %s", tuple(params + [limit + 1]))
            rows = []
            for row in cur.fetchall():
                data = dict(zip(_PUBLIC_INVOCATION_FIELDS, row))
                data["occurred_at"] = _iso(data["occurred_at"])
                rows.append(data)
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = None
            if has_more:
                last = rows[-1]
                next_cursor = _encode_cursor({"version": 1, "kind": "invocations", "scope_hash": scope_hash, "occurred_at": last["occurred_at"], "id": last["invocation_id"]})
            return {"items": rows, "page_info": {"limit": limit, "has_more": has_more, "next_cursor": next_cursor}}
        return self._read(op)


def _connection_test_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = ("connection_test_id", "provider_config_id", "config_version_id", "provider_revision", "status", "latency_ms", "checked_at", "error_code", "redacted_error_message")
    value = dict(zip(keys, row))
    value["checked_at"] = _iso(value["checked_at"])
    return value
