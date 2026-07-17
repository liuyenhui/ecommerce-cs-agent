from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import json
import time
import ipaddress
import socket
from typing import Any, Callable
import uuid
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.services.outbound_http import validate_public_https_url


@dataclass(frozen=True)
class LangGraphNodeDefinition:
    node_id: str
    label: str
    uses_llm: bool
    required: bool = False
    description: str = ""


LANGGRAPH_NODE_REGISTRY = (
    LangGraphNodeDefinition("normalize_request", "归一化请求", False),
    LangGraphNodeDefinition("retrieve_context", "检索上下文", False),
    LangGraphNodeDefinition("classify_service_stage", "咨询阶段分类", True, True, "判断售前、售中或售后阶段"),
    LangGraphNodeDefinition("classify_intent", "识别意图", False),
    LangGraphNodeDefinition("context_gate", "上下文闸门", False),
    LangGraphNodeDefinition("action_gate", "动作闸门", False),
    LangGraphNodeDefinition("generate_candidate", "生成候选", True, True, "生成客服候选回复"),
    LangGraphNodeDefinition("policy_gate", "规则闸门", False),
    LangGraphNodeDefinition("persist_trace", "记录检查点", False),
)

_NODE_BY_ID = {item.node_id: item for item in LANGGRAPH_NODE_REGISTRY}
_WRITE_ROLES = {"super_admin", "release_admin"}
_TEST_ROLES = _WRITE_ROLES | {"technical_support"}
_READ_ROLES = _TEST_ROLES | {"security_auditor"}


class ApiKeyCipher:
    version = "aes-256-gcm-v1"

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("LLM credential encryption key must decode to exactly 32 bytes")
        self._aead = AESGCM(key)

    @classmethod
    def from_base64(cls, value: str) -> "ApiKeyCipher":
        try:
            key = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("LLM credential encryption key must be valid base64") from exc
        return cls(key)

    def encrypt(self, plaintext: str) -> dict[str, str]:
        nonce = os.urandom(12)
        ciphertext = self._aead.encrypt(nonce, plaintext.encode(), self.version.encode())
        return {
            "ciphertext": base64.b64encode(ciphertext).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "encryption_version": self.version,
        }

    def decrypt(self, value: dict[str, Any]) -> str:
        if value.get("encryption_version") != self.version:
            raise ValueError("unsupported LLM credential encryption version")
        return self._aead.decrypt(
            base64.b64decode(str(value["nonce"]), validate=True),
            base64.b64decode(str(value["ciphertext"]), validate=True),
            self.version.encode(),
        ).decode()


class InMemoryLlmNodeConfigurationRepository:
    def __init__(
        self,
        cipher: ApiKeyCipher,
        *,
        connection_tester: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
    ) -> None:
        self.cipher = cipher
        self.models: dict[str, dict[str, Any]] = {}
        self.bindings: dict[str, str] = {}
        self.binding_revision = 0
        self.audit_logs: list[dict[str, Any]] = []
        self._connection_tester = connection_tester or (lambda _model, _key: {"status": "passed", "latency_ms": 0})

    def list_llms(self, session: Any) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        return [_public_model(value) for value in self.models.values()]

    def create_llm(self, session: Any, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        api_key = _required_secret(payload.get("api_key"))
        model_id = str(uuid.uuid4())
        now = _now()
        record = {
            "llm_id": model_id,
            "name": _required_text(payload.get("name"), "name"),
            "provider": _required_text(payload.get("provider"), "provider"),
            "base_url": validate_public_https_url(_required_text(payload.get("base_url"), "base_url"), field="LLM base URL"),
            "model_id": _required_text(payload.get("model_id"), "model_id"),
            **self.cipher.encrypt(api_key),
            "api_key_last_four": api_key[-4:],
            "enabled": True,
            "status": "untested",
            "last_connection_test_status": None,
            "last_connection_test_latency_ms": None,
            "last_connection_test_error_code": None,
            "last_connection_tested_at": None,
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        }
        self.models[model_id] = record
        self._audit(session, "llm.model.create", model_id, {"credential_updated": True})
        return _public_model(record)

    def update_llm(self, session: Any, llm_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        record = self._model(llm_id)
        if payload.get("expected_revision") != record["revision"]:
            raise api_error(409, "stale_revision", "LLM configuration has changed")
        enabled = payload.get("enabled")
        if enabled is False and llm_id in self.bindings.values():
            raise api_error(409, "llm_in_use", "a required node uses this LLM")
        for field in ("name", "provider", "model_id"):
            if field in payload:
                record[field] = _required_text(payload[field], field)
        if "base_url" in payload:
            record["base_url"] = validate_public_https_url(_required_text(payload["base_url"], "base_url"), field="LLM base URL")
        connection_changed = any(field in payload for field in ("provider", "base_url", "model_id"))
        credential_updated = False
        if "api_key" in payload:
            api_key = _required_secret(payload["api_key"])
            record.update(self.cipher.encrypt(api_key))
            record["api_key_last_four"] = api_key[-4:]
            record["last_connection_test_status"] = None
            record["status"] = "untested"
            credential_updated = True
        if connection_changed:
            record["last_connection_test_status"] = None
            record["last_connection_test_latency_ms"] = None
            record["last_connection_test_error_code"] = None
            record["last_connection_tested_at"] = None
            record["status"] = "untested"
        if enabled is not None:
            record["enabled"] = bool(enabled)
            record["status"] = "disabled" if not enabled else record["status"]
        record["revision"] += 1
        record["updated_at"] = _now()
        self._audit(session, "llm.model.update", llm_id, {"credential_updated": credential_updated})
        return _public_model(record)

    def test_connection(self, session: Any, llm_id: str) -> dict[str, Any]:
        _require_role(session, _TEST_ROLES)
        record = self._model(llm_id)
        try:
            api_key = self.cipher.decrypt(record)
            raw = self._connection_tester(_public_model(record), api_key)
        except Exception:
            raw = {"status": "failed", "latency_ms": 0, "error_code": "connection_failed"}
        status = "passed" if raw.get("status") == "passed" else "failed"
        record.update({
            "last_connection_test_status": status,
            "last_connection_test_latency_ms": max(0, int(raw.get("latency_ms") or 0)),
            "last_connection_test_error_code": None if status == "passed" else str(raw.get("error_code") or "connection_failed"),
            "last_connection_tested_at": _now(),
            "status": "active" if status == "passed" and record["enabled"] else "unhealthy",
            "revision": record["revision"] + 1,
            "updated_at": _now(),
        })
        result = {
            "llm_id": llm_id,
            "status": status,
            "latency_ms": record["last_connection_test_latency_ms"],
            "error_code": record["last_connection_test_error_code"],
            "tested_at": record["last_connection_tested_at"],
        }
        self._audit(session, "llm.model.connection_test", llm_id, {"status": status, "error_code": result["error_code"]})
        return result

    def get_bindings(self, session: Any) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        return self._binding_response()

    def replace_bindings(self, session: Any, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        if payload.get("expected_revision") != self.binding_revision:
            raise api_error(409, "stale_revision", "LangGraph LLM bindings have changed")
        requested = payload.get("bindings")
        if not isinstance(requested, list):
            raise api_error(422, "invalid_bindings", "bindings must be an array")
        replacement: dict[str, str] = {}
        for item in requested:
            node_id = str(item.get("node_id") or "") if isinstance(item, dict) else ""
            llm_id = str(item.get("llm_id") or "") if isinstance(item, dict) else ""
            definition = _NODE_BY_ID.get(node_id)
            if definition is None or not definition.uses_llm or node_id in replacement:
                raise api_error(422, "invalid_node_binding", "binding contains an unknown, duplicate, or non-LLM node")
            model = self._model(llm_id)
            if not model["enabled"] or model["last_connection_test_status"] != "passed":
                code = "llm_connection_test_required" if model["last_connection_test_status"] != "passed" else "llm_not_bindable"
                raise api_error(409, code, "LLM must be enabled and pass its latest connection test")
            replacement[node_id] = llm_id
        missing = [item.node_id for item in LANGGRAPH_NODE_REGISTRY if item.required and item.node_id not in replacement]
        if missing:
            raise api_error(422, "required_node_binding_missing", "all required LLM nodes must be bound")
        self.bindings = replacement
        self.binding_revision += 1
        self._audit(session, "llm.node_bindings.replace", "global", {"node_ids": sorted(replacement)})
        return self._binding_response()

    def resolve_node(self, node_id: str) -> dict[str, Any]:
        definition = _NODE_BY_ID.get(node_id)
        if definition is None or not definition.uses_llm:
            raise LookupError("node does not use an LLM")
        llm_id = self.bindings.get(node_id)
        if not llm_id:
            raise RuntimeError("required LLM node binding is missing")
        model = self._model(llm_id)
        if not model["enabled"] or model["last_connection_test_status"] != "passed":
            raise RuntimeError("bound LLM is unavailable")
        return {**_public_model(model), "api_key": self.cipher.decrypt(model)}

    def _binding_response(self) -> dict[str, Any]:
        return {
            "scope": "global",
            "revision": self.binding_revision,
            "nodes": [
                {
                    "node_id": item.node_id,
                    "label": item.label,
                    "uses_llm": item.uses_llm,
                    "required": item.required,
                    "description": item.description,
                    "llm_id": self.bindings.get(item.node_id),
                }
                for item in LANGGRAPH_NODE_REGISTRY
            ],
        }

    def _model(self, llm_id: str) -> dict[str, Any]:
        try:
            return self.models[llm_id]
        except KeyError:
            raise api_error(404, "llm_not_found", "LLM configuration not found") from None

    def _audit(self, session: Any, action: str, object_id: str, summary: dict[str, Any]) -> None:
        self.audit_logs.append({"action": action, "object_id": object_id, "actor_id": session.user_id, "summary": copy.deepcopy(summary)})


class PostgresLlmNodeConfigurationRepository:
    def __init__(self, database_url: str, cipher: ApiKeyCipher, *, connection_tester: Callable[[dict[str, Any], str], dict[str, Any]]) -> None:
        self.database_url = database_url
        self.cipher = cipher
        self.connection_tester = connection_tester

    @staticmethod
    def _connect(database_url: str) -> Any:
        import psycopg
        return psycopg.connect(database_url)

    def list_llms(self, session: Any) -> list[dict[str, Any]]:
        _require_role(session, _READ_ROLES)
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(_MODEL_SELECT + " ORDER BY name, id")
            return [_public_model(_model_from_row(row)) for row in cur.fetchall()]

    def create_llm(self, session: Any, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        api_key = _required_secret(payload.get("api_key"))
        encrypted = self.cipher.encrypt(api_key)
        llm_id = str(uuid.uuid4())
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO llm_model_config (id,name,provider,base_url,model_id,api_key_ciphertext,api_key_nonce,encryption_version,api_key_last_four) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING " + _MODEL_COLUMNS,
                (llm_id, _required_text(payload.get("name"), "name"), _required_text(payload.get("provider"), "provider"), validate_public_https_url(_required_text(payload.get("base_url"), "base_url"), field="LLM base URL"), _required_text(payload.get("model_id"), "model_id"), base64.b64decode(encrypted["ciphertext"]), base64.b64decode(encrypted["nonce"]), encrypted["encryption_version"], api_key[-4:]),
            )
            result = _public_model(_model_from_row(cur.fetchone()))
            self._audit(cur, session, "llm.model.create", "llm_model_config", llm_id, {"credential_updated": True})
            return result

    def update_llm(self, session: Any, llm_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(_MODEL_SELECT + " WHERE id=%s FOR UPDATE", (llm_id,))
            row = cur.fetchone()
            if not row:
                raise api_error(404, "llm_not_found", "LLM configuration not found")
            current = _model_from_row(row)
            if payload.get("expected_revision") != current["revision"]:
                raise api_error(409, "stale_revision", "LLM configuration has changed")
            if payload.get("enabled") is False:
                cur.execute("SELECT 1 FROM langgraph_node_llm_binding WHERE llm_model_config_id=%s LIMIT 1", (llm_id,))
                if cur.fetchone():
                    raise api_error(409, "llm_in_use", "a required node uses this LLM")
            updates: list[str] = []
            values: list[Any] = []
            for field in ("name", "provider", "model_id"):
                if field in payload:
                    updates.append(f"{field}=%s"); values.append(_required_text(payload[field], field))
            if "base_url" in payload:
                updates.append("base_url=%s"); values.append(validate_public_https_url(_required_text(payload["base_url"], "base_url"), field="LLM base URL"))
            connection_changed = any(field in payload for field in ("provider", "base_url", "model_id"))
            credential_updated = "api_key" in payload
            if credential_updated:
                key = _required_secret(payload["api_key"]); encrypted = self.cipher.encrypt(key)
                updates.extend(["api_key_ciphertext=%s", "api_key_nonce=%s", "encryption_version=%s", "api_key_last_four=%s", "last_connection_test_status=NULL", "last_connection_test_latency_ms=NULL", "last_connection_test_error_code=NULL", "last_connection_tested_at=NULL", "status='untested'"])
                values.extend([base64.b64decode(encrypted["ciphertext"]), base64.b64decode(encrypted["nonce"]), encrypted["encryption_version"], key[-4:]])
            elif connection_changed:
                updates.extend(["last_connection_test_status=NULL", "last_connection_test_latency_ms=NULL", "last_connection_test_error_code=NULL", "last_connection_tested_at=NULL", "status='untested'"])
            if "enabled" in payload:
                updates.extend(["enabled=%s", "status=CASE WHEN %s THEN status ELSE 'disabled' END"]); values.extend([payload["enabled"], payload["enabled"]])
            if not updates:
                raise api_error(422, "validation_error", "at least one change is required")
            values.extend([llm_id, current["revision"]])
            cur.execute(f"UPDATE llm_model_config SET {', '.join(updates)}, revision=revision+1, updated_at=now() WHERE id=%s AND revision=%s RETURNING " + _MODEL_COLUMNS, tuple(values))
            result = _public_model(_model_from_row(cur.fetchone()))
            self._audit(cur, session, "llm.model.update", "llm_model_config", llm_id, {"credential_updated": credential_updated})
            return result

    def test_connection(self, session: Any, llm_id: str) -> dict[str, Any]:
        _require_role(session, _TEST_ROLES)
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(_MODEL_SELECT + " WHERE id=%s", (llm_id,))
            row = cur.fetchone()
            if not row:
                raise api_error(404, "llm_not_found", "LLM configuration not found")
            snapshot = _model_from_row(row)
        try:
            key = self.cipher.decrypt(snapshot)
            raw = self.connection_tester(_public_model(snapshot), key)
        except Exception:
            raw = {"status": "failed", "latency_ms": 0, "error_code": "connection_failed"}
        status = "passed" if raw.get("status") == "passed" else "failed"
        latency = max(0, int(raw.get("latency_ms") or 0)); error_code = None if status == "passed" else str(raw.get("error_code") or "connection_failed")
        test_id = str(uuid.uuid4())
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT revision FROM llm_model_config WHERE id=%s FOR UPDATE", (llm_id,)); locked = cur.fetchone()
            if not locked or locked[0] != snapshot["revision"]:
                raise api_error(409, "stale_revision", "LLM changed while connection test was running")
            cur.execute("UPDATE llm_model_config SET last_connection_test_status=%s,last_connection_test_latency_ms=%s,last_connection_test_error_code=%s,last_connection_tested_at=now(),status=CASE WHEN enabled AND %s='passed' THEN 'active' WHEN enabled THEN 'unhealthy' ELSE 'disabled' END,revision=revision+1,updated_at=now() WHERE id=%s", (status, latency, error_code, status, llm_id))
            cur.execute("INSERT INTO llm_model_connection_test (id,llm_model_config_id,checked_by_system_admin_user_id,model_revision,status,latency_ms,error_code) VALUES (%s,%s,%s,%s,%s,%s,%s)", (test_id, llm_id, session.user_id, snapshot["revision"] + 1, status, latency, error_code))
            self._audit(cur, session, "llm.model.connection_test", "llm_model_connection_test", test_id, {"status": status, "error_code": error_code})
        return {"llm_id": llm_id, "status": status, "latency_ms": latency, "error_code": error_code}

    def get_bindings(self, session: Any) -> dict[str, Any]:
        _require_role(session, _READ_ROLES)
        return self._binding_response()

    def replace_bindings(self, session: Any, payload: dict[str, Any]) -> dict[str, Any]:
        _require_role(session, _WRITE_ROLES)
        requested = payload.get("bindings")
        if not isinstance(requested, list):
            raise api_error(422, "invalid_bindings", "bindings must be an array")
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT revision FROM llm_node_binding_revision WHERE singleton=TRUE FOR UPDATE"); revision = cur.fetchone()[0]
            if payload.get("expected_revision") != revision:
                raise api_error(409, "stale_revision", "LangGraph LLM bindings have changed")
            replacement: dict[str, str] = {}
            for item in requested:
                node_id = str(item.get("node_id") or ""); llm_id = str(item.get("llm_id") or "")
                definition = _NODE_BY_ID.get(node_id)
                if not definition or not definition.uses_llm or node_id in replacement:
                    raise api_error(422, "invalid_node_binding", "binding contains an unknown, duplicate, or non-LLM node")
                cur.execute("SELECT enabled,last_connection_test_status FROM llm_model_config WHERE id=%s FOR KEY SHARE", (llm_id,)); model = cur.fetchone()
                if not model:
                    raise api_error(404, "llm_not_found", "LLM configuration not found")
                if not model[0] or model[1] != "passed":
                    raise api_error(409, "llm_not_bindable", "LLM must be enabled and pass its latest connection test")
                replacement[node_id] = llm_id
            if any(item.required and item.node_id not in replacement for item in LANGGRAPH_NODE_REGISTRY):
                raise api_error(422, "required_node_binding_missing", "all required LLM nodes must be bound")
            cur.execute("DELETE FROM langgraph_node_llm_binding")
            new_revision = revision + 1
            for node_id, llm_id in replacement.items():
                cur.execute("INSERT INTO langgraph_node_llm_binding (node_id,llm_model_config_id,revision,updated_by_system_admin_user_id) VALUES (%s,%s,%s,%s)", (node_id, llm_id, new_revision, session.user_id))
            cur.execute("UPDATE llm_node_binding_revision SET revision=%s,updated_by_system_admin_user_id=%s,updated_at=now() WHERE singleton=TRUE", (new_revision, session.user_id))
            self._audit(cur, session, "llm.node_bindings.replace", "langgraph_node_llm_binding", "global", {"node_ids": sorted(replacement)})
        return self._binding_response()

    def resolve_node(self, node_id: str) -> dict[str, Any]:
        if node_id not in _NODE_BY_ID or not _NODE_BY_ID[node_id].uses_llm:
            raise LookupError("node does not use an LLM")
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT llm_model_config_id::text FROM langgraph_node_llm_binding WHERE node_id=%s", (node_id,)); binding = cur.fetchone()
            if not binding:
                raise RuntimeError("required LLM node binding is missing")
            cur.execute(_MODEL_SELECT + " WHERE id=%s", (binding[0],)); row = cur.fetchone()
            if not row:
                raise RuntimeError("required LLM node binding is missing")
            model = _model_from_row(row)
            if not model["enabled"] or model["last_connection_test_status"] != "passed":
                raise RuntimeError("bound LLM is unavailable")
            return {**_public_model(model), "api_key": self.cipher.decrypt(model)}

    def _binding_response(self) -> dict[str, Any]:
        with self._connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT revision FROM llm_node_binding_revision WHERE singleton=TRUE"); revision = cur.fetchone()[0]
            cur.execute("SELECT node_id,llm_model_config_id::text FROM langgraph_node_llm_binding"); bindings = dict(cur.fetchall())
        return {"scope": "global", "revision": revision, "nodes": [{"node_id": item.node_id, "label": item.label, "uses_llm": item.uses_llm, "required": item.required, "description": item.description, "llm_id": bindings.get(item.node_id)} for item in LANGGRAPH_NODE_REGISTRY]}

    @staticmethod
    def _audit(cur: Any, session: Any, action: str, object_type: str, object_id: str, summary: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb
        cur.execute("INSERT INTO system_admin_audit_log (id,system_admin_user_id,action,object_type,object_id,diff_summary) VALUES (%s,%s,%s,%s,%s,%s)", (str(uuid.uuid4()), session.user_id, action, object_type, object_id, Jsonb(summary)))


_MODEL_COLUMNS = "id::text,name,provider,base_url,model_id,api_key_ciphertext,api_key_nonce,encryption_version,api_key_last_four,enabled,status,last_connection_test_status,last_connection_test_latency_ms,last_connection_test_error_code,last_connection_tested_at,revision,created_at,updated_at"
_MODEL_SELECT = "SELECT " + _MODEL_COLUMNS + " FROM llm_model_config"


def _model_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = ("llm_id","name","provider","base_url","model_id","ciphertext","nonce","encryption_version","api_key_last_four","enabled","status","last_connection_test_status","last_connection_test_latency_ms","last_connection_test_error_code","last_connection_tested_at","revision","created_at","updated_at")
    value = dict(zip(keys, row))
    value["ciphertext"] = base64.b64encode(bytes(value["ciphertext"])).decode(); value["nonce"] = base64.b64encode(bytes(value["nonce"])).decode()
    for field in ("last_connection_tested_at", "created_at", "updated_at"):
        if value.get(field) is not None:
            value[field] = value[field].isoformat()
    return value


def _public_model(record: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "llm_id", "name", "provider", "base_url", "model_id", "enabled", "status",
        "last_connection_test_status", "last_connection_test_latency_ms", "last_connection_test_error_code",
        "last_connection_tested_at", "revision", "created_at", "updated_at",
    )
    return {
        **{key: copy.deepcopy(record.get(key)) for key in allowed},
        "has_api_key": bool(record.get("ciphertext")),
        "api_key_masked": f"••••{record.get('api_key_last_four', '')}",
    }


def _require_role(session: Any, roles: set[str]) -> None:
    if getattr(session, "role", None) not in roles:
        raise api_error(403, "forbidden", "system admin role is not permitted")


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise api_error(422, "validation_error", f"{field} is required")
    return text


def _required_secret(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise api_error(422, "invalid_api_key", "API Key is required")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_openai_compatible_connection(model: dict[str, Any], api_key: str) -> dict[str, Any]:
    started = time.monotonic()
    payload = {
        "model": model["model_id"],
        "max_tokens": 1,
        "temperature": 0,
        "messages": [{"role": "user", "content": "ping"}],
    }
    target = validate_resolved_public_https_url(str(model["base_url"])).rstrip("/") + "/chat/completions"
    outbound = urllib_request.Request(
        target,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(outbound, timeout=10) as response:
            response.read(4096)
        return {"status": "passed", "latency_ms": int((time.monotonic() - started) * 1000)}
    except HTTPError as exc:
        code = "upstream_auth_failed" if exc.code in {401, 403} else "upstream_rejected"
    except (URLError, TimeoutError):
        code = "upstream_unavailable"
    except Exception:
        code = "connection_failed"
    return {"status": "failed", "latency_ms": int((time.monotonic() - started) * 1000), "error_code": code}


def validate_resolved_public_https_url(value: str) -> str:
    from urllib.parse import urlparse
    normalized = validate_public_https_url(value, field="LLM base URL")
    host = urlparse(normalized).hostname
    if not host:
        raise ValueError("LLM base URL hostname is required")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("LLM base URL hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("LLM base URL must resolve only to public addresses")
    return normalized
