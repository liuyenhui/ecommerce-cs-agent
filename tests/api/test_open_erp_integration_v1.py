from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app


INTEGRATION_HEADERS = {"Authorization": "Bearer test-open-erp-integration-token"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def billing_lease(
    *,
    connector_id: str,
    request_id: str,
    external_store_id: str = "mall-001",
    reservation_id: str = "usage-reservation-001",
    secret: str = "test-open-erp-billing-secret",
    exp: int | None = None,
) -> str:
    payload = {
        "iss": "open_erp_agent",
        "aud": "ecommerce-cs-agent",
        "connector_id": connector_id,
        "reservation_id": reservation_id,
        "request_id": request_id,
        "platform": "pdd",
        "external_store_id": external_store_id,
        "feature": "ai_cs.reply_decision",
        "quantity": 1,
        "exp": exp or int(time.time()) + 300,
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def provision_payload() -> dict[str, Any]:
    return {
        "request_id": "provision-001",
        "tenant_ref": "open_erp:org-001",
        "tenant_name": "测试商家",
        "platform": "pdd",
        "external_store_id": "mall-001",
        "external_store_name": "测试店铺",
        "platform_account_ref": "pdd-account-main",
        "machine_ref": "machine-hash-001",
    }


def reply_payload(connector_id: str, request_id: str = "req-ai-001") -> dict[str, Any]:
    return {
        "request_id": request_id,
        "platform": "pdd",
        "external_store_id": "mall-001",
        "platform_account_ref": "pdd-account-main",
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": "这个商品有哪些尺寸？",
            "sent_at": "2026-06-24T10:00:00+08:00",
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-hash-001",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {"orders": [], "logistics": [], "rules": []},
        "billing_lease": billing_lease(connector_id=connector_id, request_id=request_id),
    }


def provision(client: TestClient) -> dict[str, Any]:
    response = client.post("/v1/integrations/open-erp/provision", headers=INTEGRATION_HEADERS, json=provision_payload())
    assert response.status_code == 201
    return response.json()


def test_open_erp_provision_returns_one_time_connector_token_and_replays_without_secret() -> None:
    client = TestClient(create_app())

    first = provision(client)
    second = client.post("/v1/integrations/open-erp/provision", headers=INTEGRATION_HEADERS, json=provision_payload())

    assert first["status"] == "active"
    assert first["readiness_status"] == "knowledge_pending"
    assert first["connector_id"].startswith("connector-")
    assert first["connector_token"].startswith("csconn_")
    assert first["connector_token_prefix"] == first["connector_token"][:14]
    assert second.status_code == 200
    assert second.json()["connector_id"] == first["connector_id"]
    assert "connector_token" not in second.json()


def test_connector_token_cannot_access_customer_or_system_admin() -> None:
    client = TestClient(create_app())
    connector = provision(client)
    headers = {"Authorization": f"Bearer {connector['connector_token']}"}

    customer_admin = client.get("/v1/admin/auth/me", headers=headers)
    system_admin = client.get("/v1/system-admin/auth/me", headers=headers)

    assert customer_admin.status_code == 403
    assert system_admin.status_code == 403


def test_reply_decision_requires_valid_billing_lease_for_connector() -> None:
    client = TestClient(create_app())
    connector = provision(client)
    headers = {"Authorization": f"Bearer {connector['connector_token']}"}
    payload = reply_payload(connector["connector_id"])

    missing = client.post("/v1/reply-decisions", headers=headers, json={k: v for k, v in payload.items() if k != "billing_lease"})
    expired = client.post(
        "/v1/reply-decisions",
        headers=headers,
        json={**payload, "billing_lease": billing_lease(connector_id=connector["connector_id"], request_id="req-ai-001", exp=1)},
    )
    mismatch = client.post(
        "/v1/reply-decisions",
        headers=headers,
        json={**payload, "billing_lease": billing_lease(connector_id="connector-other", request_id="req-ai-001")},
    )

    assert missing.status_code == 402
    assert missing.json()["error"]["code"] == "billing_required"
    assert expired.status_code == 403
    assert expired.json()["error"]["code"] == "billing_lease_invalid"
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "billing_lease_scope_mismatch"


def test_valid_connector_and_billing_lease_create_decision_without_public_tenant_id() -> None:
    client = TestClient(create_app())
    connector = provision(client)
    headers = {"Authorization": f"Bearer {connector['connector_token']}"}

    response = client.post("/v1/reply-decisions", headers=headers, json=reply_payload(connector["connector_id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "context_request"
    assert body["context_requests"][0]["type"] == "products"
    assert body["trace"]["connector_id"] == connector["connector_id"]
    assert body["trace"]["billing_reservation_id"] == "usage-reservation-001"
    assert body["trace"]["tenant_id"] == connector["tenant_id"]


def test_context_refill_returns_candidate_when_required_context_is_complete() -> None:
    client = TestClient(create_app())
    connector = provision(client)
    headers = {"Authorization": f"Bearer {connector['connector_token']}"}
    decision = client.post("/v1/reply-decisions", headers=headers, json=reply_payload(connector["connector_id"])).json()

    refill = client.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/products",
        headers=headers,
        json={
            "context_request_id": decision["context_requests"][0]["context_request_id"],
            "idempotency_key": "ctx-products-001",
            "external_store_id": "mall-001",
            "items": [{"external_product_id": "pdd-product-001", "title": "测试商品", "attributes": {"size": "M/L"}}],
        },
    )

    assert refill.status_code == 200
    body = refill.json()
    assert body["decision_status"] == "candidate"
    assert body["action"] == "candidate"
    assert body["candidates"][0]["reply_text"]
