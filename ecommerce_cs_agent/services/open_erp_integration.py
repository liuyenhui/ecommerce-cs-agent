from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

from ecommerce_cs_agent.core.config import Settings


@dataclass(frozen=True)
class OpenErpConnector:
    connector_id: str
    tenant_id: str
    store_id: str
    platform_account_id: str
    platform: str
    external_store_id: str
    external_store_name: str
    platform_account_ref: str
    token_hash: str
    token_prefix: str
    status: str
    readiness_status: str
    machine_ref: str


@dataclass
class OpenErpAdminLaunchTicket:
    launch_token: str
    nonce: str
    expires_at: int
    external_system_id: str
    platform: str
    external_store_id: str
    external_store_name: str
    platform_account_ref: str
    tenant_id: str
    store_id: str
    connector_id: str
    consumed_at: int | None = None


class BillingLeaseError(ValueError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class OpenErpIntegrationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._connectors_by_key: dict[tuple[str, str, str], OpenErpConnector] = {}
        self._connectors_by_id: dict[str, OpenErpConnector] = {}
        self._launch_tickets: dict[str, OpenErpAdminLaunchTicket] = {}

    def require_service_auth(self, authorization: str | None) -> None:
        expected = f"Bearer {self.settings.open_erp_integration_token}"
        if not authorization:
            raise PermissionError("missing open_erp integration token")
        if authorization != expected:
            raise PermissionError("invalid open_erp integration token")

    def provision(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        platform = _required_text(payload, "platform")
        external_store_id = _required_text(payload, "external_store_id")
        external_store_name = _text(payload.get("external_store_name"))
        platform_account_ref = _required_text(payload, "platform_account_ref")
        key = (platform, external_store_id, platform_account_ref)
        existing = self._connectors_by_key.get(key)
        if existing:
            if external_store_name and external_store_name != existing.external_store_name:
                existing = OpenErpConnector(**{**existing.__dict__, "external_store_name": external_store_name})
                self._save(existing)
            return 200, self._public_connector(existing)

        tenant_ref = _text(payload.get("tenant_ref")) or f"open_erp:{platform}:{external_store_id}"
        tenant_id = _stable_id("tenant", tenant_ref)
        store_id = _stable_id("store", f"{tenant_id}:{platform}:{external_store_id}")
        platform_account_id = _stable_id("platform-account", f"{store_id}:{platform_account_ref}")
        connector_id = _stable_id("connector", f"{platform_account_id}:{_text(payload.get('machine_ref'))}")
        connector_token = _new_connector_token()
        connector = OpenErpConnector(
            connector_id=connector_id,
            tenant_id=tenant_id,
            store_id=store_id,
            platform_account_id=platform_account_id,
            platform=platform,
            external_store_id=external_store_id,
            external_store_name=external_store_name,
            platform_account_ref=platform_account_ref,
            token_hash=_hash_token(connector_token),
            token_prefix=connector_token[:14],
            status="active",
            readiness_status="knowledge_pending",
            machine_ref=_text(payload.get("machine_ref")),
        )
        self._save(connector)
        response = self._public_connector(connector)
        response["connector_token"] = connector_token
        return 201, response

    def patch_connector(self, connector_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        connector = self._connectors_by_id.get(connector_id)
        if not connector:
            raise KeyError(connector_id)
        status = _text(payload.get("status")) or connector.status
        if status not in {"active", "paused", "revoked"}:
            raise ValueError("status must be active, paused, or revoked")
        readiness_status = _text(payload.get("readiness_status")) or connector.readiness_status
        connector_token = _new_connector_token() if payload.get("rotate_token") is True else None
        updated = OpenErpConnector(
            **{
                **connector.__dict__,
                "status": status,
                "readiness_status": readiness_status,
                "token_hash": _hash_token(connector_token) if connector_token else connector.token_hash,
                "token_prefix": connector_token[:14] if connector_token else connector.token_prefix,
            }
        )
        self._save(updated)
        response = self._public_connector(updated)
        if connector_token:
            response["connector_token"] = connector_token
        return response

    def issue_admin_launch_ticket(self, payload: dict[str, Any]) -> dict[str, Any]:
        platform = _required_text(payload, "platform")
        external_store_id = _required_text(payload, "external_store_id")
        platform_account_ref = _required_text(payload, "platform_account_ref")
        connector = self._connectors_by_key.get((platform, external_store_id, platform_account_ref))
        if not connector or connector.status != "active":
            raise KeyError("connector_not_bound")
        external_store_name = connector.external_store_name or _text(payload.get("external_store_name"))
        now = int(time.time())
        ttl_seconds = _positive_int(payload.get("ttl_seconds"), default=90, maximum=120)
        token = f"cslaunch_{secrets.token_urlsafe(32)}"
        ticket = OpenErpAdminLaunchTicket(
            launch_token=token,
            nonce=f"nonce-{uuid.uuid4().hex}",
            expires_at=now + ttl_seconds,
            external_system_id="open_erp_agent",
            platform=connector.platform,
            external_store_id=connector.external_store_id,
            external_store_name=external_store_name,
            platform_account_ref=connector.platform_account_ref,
            tenant_id=connector.tenant_id,
            store_id=connector.external_store_id,
            connector_id=connector.connector_id,
        )
        self._launch_tickets[token] = ticket
        return self._public_launch_ticket(ticket)

    def consume_admin_launch_ticket(self, launch_token: str) -> OpenErpAdminLaunchTicket:
        token = _text(launch_token)
        ticket = self._launch_tickets.get(token)
        if not ticket:
            raise KeyError("launch_token_not_found")
        now = int(time.time())
        if ticket.consumed_at is not None:
            raise FileExistsError("launch_token_consumed")
        if ticket.expires_at <= now:
            raise TimeoutError("launch_token_expired")
        ticket.consumed_at = now
        return ticket

    def authenticate_connector(self, authorization: str | None) -> OpenErpConnector:
        token = _bearer_token(authorization)
        if not token:
            raise PermissionError("missing bearer token")
        token_hash = _hash_token(token)
        for connector in self._connectors_by_id.values():
            if hmac.compare_digest(connector.token_hash, token_hash):
                if connector.status != "active":
                    raise PermissionError(f"connector status is {connector.status}")
                return connector
        raise PermissionError("invalid connector token")

    def get_connector(self, connector_id: str | None) -> OpenErpConnector | None:
        return self._connectors_by_id.get(connector_id or "")

    def verify_billing_lease(self, connector: OpenErpConnector | None, payload: dict[str, Any]) -> dict[str, Any]:
        raw = _text(payload.get("billing_lease"))
        if not raw:
            raise BillingLeaseError(402, "billing_required", "billing_lease is required")
        try:
            encoded_payload, encoded_signature = raw.split(".", 1)
            expected = _sign(encoded_payload, self.settings.open_erp_billing_lease_secret)
            if not hmac.compare_digest(expected, encoded_signature):
                raise ValueError("signature mismatch")
            lease = json.loads(_b64decode(encoded_payload).decode("utf-8"))
        except Exception as exc:
            raise BillingLeaseError(403, "billing_lease_invalid", "billing_lease is invalid") from exc

        now = int(time.time())
        if int(lease.get("exp") or 0) <= now:
            raise BillingLeaseError(403, "billing_lease_invalid", "billing_lease is expired")
        if lease.get("iss") != "open_erp_agent" or lease.get("aud") != "ecommerce-cs-agent":
            raise BillingLeaseError(403, "billing_lease_invalid", "billing_lease issuer or audience is invalid")
        if lease.get("feature") != "ai_cs.reply_decision":
            raise BillingLeaseError(403, "billing_lease_invalid", "billing_lease feature is invalid")

        expected_scope = {
            "request_id": _text(payload.get("request_id")),
            "platform": _text(payload.get("platform")),
            "external_store_id": _text(payload.get("external_store_id") or payload.get("store_id")),
        }
        if connector:
            expected_scope["connector_id"] = connector.connector_id
        for key, expected_value in expected_scope.items():
            if _text(lease.get(key)) != expected_value:
                raise BillingLeaseError(403, "billing_lease_scope_mismatch", f"billing_lease {key} does not match request")
        return lease

    def enrich_reply_payload(
        self,
        connector: OpenErpConnector | None,
        payload: dict[str, Any],
        lease: dict[str, Any],
    ) -> dict[str, Any]:
        enriched = dict(payload)
        if connector:
            enriched.setdefault("tenant_id", connector.tenant_id)
            enriched.setdefault("organization_id", connector.tenant_id)
            enriched.setdefault("store_id", connector.external_store_id)
            enriched.setdefault("external_store_id", connector.external_store_id)
            enriched.setdefault("platform_account_ref", connector.platform_account_ref)
            enriched["connector_id"] = connector.connector_id
            enriched["agent_store_id"] = connector.store_id
            enriched["agent_platform_account_id"] = connector.platform_account_id
        enriched["billing_reservation_id"] = _text(lease.get("reservation_id"))
        return enriched

    def _save(self, connector: OpenErpConnector) -> None:
        key = (connector.platform, connector.external_store_id, connector.platform_account_ref)
        self._connectors_by_key[key] = connector
        self._connectors_by_id[connector.connector_id] = connector

    def _public_connector(self, connector: OpenErpConnector) -> dict[str, Any]:
        return {
            "tenant_id": connector.tenant_id,
            "store_id": connector.store_id,
            "platform_account_id": connector.platform_account_id,
            "connector_id": connector.connector_id,
            "connector_token_prefix": connector.token_prefix,
            "status": connector.status,
            "readiness_status": connector.readiness_status,
            "platform": connector.platform,
            "external_store_id": connector.external_store_id,
            "external_store_name": connector.external_store_name,
            "platform_account_ref": connector.platform_account_ref,
        }

    def _public_launch_ticket(self, ticket: OpenErpAdminLaunchTicket) -> dict[str, Any]:
        return {
            "launch_token": ticket.launch_token,
            "nonce": ticket.nonce,
            "expires_at": ticket.expires_at,
            "external_system_id": ticket.external_system_id,
            "platform": ticket.platform,
            "external_store_id": ticket.external_store_id,
            "external_store_name": ticket.external_store_name,
            "platform_account_ref": ticket.platform_account_ref,
            "tenant_id": ticket.tenant_id,
            "store_id": ticket.store_id,
            "connector_id": ticket.connector_id,
        }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = _text(payload.get(key))
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))


def _stable_id(prefix: str, raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _new_connector_token() -> str:
    return f"csconn_{secrets.token_urlsafe(32)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    if not authorization.lower().startswith("bearer "):
        return ""
    return authorization.split(" ", 1)[1].strip()


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(encoded_payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
