from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.services import open_erp_integration as open_erp_module


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


def provision_payload(
    *,
    request_id: str = "provision-001",
    tenant_ref: str = "open_erp:org-001",
    external_store_id: str = "mall-001",
    platform_account_ref: str = "pdd-account-main",
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "tenant_ref": tenant_ref,
        "tenant_name": "测试商家",
        "platform": "pdd",
        "external_store_id": external_store_id,
        "external_store_name": "测试店铺",
        "platform_account_ref": platform_account_ref,
        "machine_ref": "machine-hash-001",
    }


def reply_payload(
    connector_id: str,
    request_id: str = "req-ai-001",
    *,
    external_store_id: str = "mall-001",
    platform_account_ref: str = "pdd-account-main",
    content: str = "这个商品有哪些尺寸？",
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "platform": "pdd",
        "external_store_id": external_store_id,
        "platform_account_ref": platform_account_ref,
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": content,
            "sent_at": "2026-06-24T10:00:00+08:00",
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-hash-001",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {"orders": [], "logistics": [], "rules": []},
        "billing_lease": billing_lease(
            connector_id=connector_id,
            request_id=request_id,
            external_store_id=external_store_id,
        ),
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


def test_open_erp_provision_refreshes_existing_store_display_name() -> None:
    client = TestClient(create_app())

    initial = client.post(
        "/v1/integrations/open-erp/provision",
        headers=INTEGRATION_HEADERS,
        json={**provision_payload(), "external_store_name": ""},
    )
    refreshed = client.post(
        "/v1/integrations/open-erp/provision",
        headers=INTEGRATION_HEADERS,
        json={**provision_payload(), "request_id": "provision-refresh-name", "external_store_name": "宠萌洗护用品店"},
    )
    ticket = client.post(
        "/v1/integrations/open-erp/admin-launch-tickets",
        headers=INTEGRATION_HEADERS,
        json={
            "request_id": "launch-refresh-name",
            "platform": "pdd",
            "external_store_id": "mall-001",
            "platform_account_ref": "pdd-account-main",
        },
    )

    assert initial.status_code == 201
    assert initial.json()["external_store_name"] == ""
    assert refreshed.status_code == 200
    assert refreshed.json()["external_store_name"] == "宠萌洗护用品店"
    assert ticket.status_code == 201
    assert ticket.json()["external_store_name"] == "宠萌洗护用品店"


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

    refill_payload = {
        "context_request_id": decision["context_requests"][0]["context_request_id"],
        "idempotency_key": "ctx-products-001",
        "captured_at": "2026-06-24T10:01:00+08:00",
        "external_store_id": "mall-001",
        "products": [{"external_product_id": "pdd-product-001", "title": "测试商品", "attributes": {"size": "M/L"}}],
    }
    refill = client.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/products",
        headers=headers,
        json=refill_payload,
    )
    retry = client.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/products",
        headers=headers,
        json=refill_payload,
    )

    assert refill.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == refill.json()
    body = refill.json()
    assert body["decision_status"] == "candidate"
    assert body["action"] == "candidate"
    assert body["candidates"][0]["reply_text"]


def test_connector_scope_rejects_cross_store_continuations_without_payload_scope() -> None:
    client = TestClient(create_app())
    first = provision(client)
    second_response = client.post(
        "/v1/integrations/open-erp/provision",
        headers=INTEGRATION_HEADERS,
        json=provision_payload(
            request_id="provision-002",
            tenant_ref="open_erp:org-002",
            external_store_id="mall-002",
            platform_account_ref="pdd-account-second",
        ),
    )
    assert second_response.status_code == 201
    second = second_response.json()
    first_headers = {"Authorization": f"Bearer {first['connector_token']}"}
    second_headers = {"Authorization": f"Bearer {second['connector_token']}"}
    decision = client.post(
        "/v1/reply-decisions",
        headers=first_headers,
        json=reply_payload(
            first["connector_id"],
            "req-connector-scope",
            content="帮我把订单备注改成红色包装",
        ),
    ).json()
    action_id = decision["action_requests"][0]["action_id"]
    context_decision = client.post(
        "/v1/reply-decisions",
        headers=first_headers,
        json=reply_payload(first["connector_id"], "req-connector-context-scope"),
    ).json()

    context_refill = client.post(
        f"/v1/reply-decisions/{context_decision['decision_id']}/contexts/products",
        headers=second_headers,
        json={
            "context_request_id": context_decision["context_requests"][0]["context_request_id"],
            "idempotency_key": "cross-store-context-refill",
            "captured_at": "2026-06-24T10:01:00+08:00",
            "products": [{"external_product_id": "pdd-product-001", "title": "测试商品"}],
        },
    )
    action_result = client.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=second_headers,
        json={
            "action_id": action_id,
            "action_type": "update-note",
            "idempotency_key": "cross-store-action-result",
            "status": "succeeded",
            "executed_at": "2026-06-24T10:01:00+08:00",
        },
    )
    feedback = client.post(
        "/v1/feedback/human-replies",
        headers=second_headers,
        json={
            "decision_id": decision["decision_id"],
            "message_id": "msg-req-connector-scope",
            "human_reply": "人工回复",
            "used_candidate": False,
            "resolution_status": "resolved",
            "labels": [],
        },
    )

    assert context_refill.status_code == 403
    assert action_result.status_code == 403
    assert feedback.status_code == 403


def test_open_erp_launch_ticket_exchanges_to_customer_admin_session() -> None:
    client = TestClient(create_app())
    connector = provision(client)

    ticket = client.post(
        "/v1/integrations/open-erp/admin-launch-tickets",
        headers=INTEGRATION_HEADERS,
        json={
            "request_id": "launch-001",
            "platform": "pdd",
            "external_store_id": "mall-001",
            "platform_account_ref": "pdd-account-main",
        },
    )
    assert ticket.status_code == 201
    body = ticket.json()
    assert body["launch_token"].startswith("cslaunch_")
    assert body["tenant_id"] == connector["tenant_id"]
    assert body["store_id"] == "mall-001"
    assert body["external_store_name"] == "测试店铺"

    exchange = client.post("/v1/admin/auth/launch/exchange", json={"launch_token": body["launch_token"]})

    assert exchange.status_code == 200
    assert "agent_admin_session=" in exchange.headers["set-cookie"]
    content = exchange.json()
    assert content["active_organization_id"] == connector["tenant_id"]
    assert content["active_store_id"] == "mall-001"
    assert content["stores"][0]["name"] == "测试店铺"
    assert content["stores"][0]["platform"] == "pdd"

    replay = client.post("/v1/admin/auth/launch/exchange", json={"launch_token": body["launch_token"]})
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "launch_token_consumed"
    assert replay.json()["errorId"] == "ECS-LAUNCH-001"


def test_open_erp_launch_ticket_rejects_unbound_or_unauthorized_store() -> None:
    client = TestClient(create_app())
    provision(client)

    missing = client.post(
        "/v1/integrations/open-erp/admin-launch-tickets",
        headers=INTEGRATION_HEADERS,
        json={
            "request_id": "launch-missing",
            "platform": "pdd",
            "external_store_id": "mall-other",
            "platform_account_ref": "pdd-account-main",
        },
    )
    bad_auth = client.post(
        "/v1/integrations/open-erp/admin-launch-tickets",
        headers={"Authorization": "Bearer wrong"},
        json={
            "request_id": "launch-bad",
            "platform": "pdd",
            "external_store_id": "mall-001",
            "platform_account_ref": "pdd-account-main",
        },
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "connector_not_bound"
    assert missing.json()["errorId"] == "ECS-OE-002"
    assert bad_auth.status_code == 401
    assert bad_auth.json()["errorId"] == "ECS-OE-001"


def test_open_erp_provision_errors_have_stable_error_ids() -> None:
    client = TestClient(create_app())

    missing_auth = client.post("/v1/integrations/open-erp/provision", json=provision_payload())
    invalid_payload = client.post(
        "/v1/integrations/open-erp/provision",
        headers=INTEGRATION_HEADERS,
        json={k: v for k, v in provision_payload().items() if k != "platform"},
    )

    assert missing_auth.status_code == 401
    assert missing_auth.json()["error"]["code"] == "unauthorized"
    assert missing_auth.json()["errorId"] == "ECS-OE-001"
    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["error"]["code"] == "validation_error"
    assert invalid_payload.json()["errorId"] == "ECS-OE-003"


def test_launch_exchange_failures_have_stable_error_ids(monkeypatch) -> None:
    client = TestClient(create_app())
    provision(client)
    monkeypatch.setattr(open_erp_module.time, "time", lambda: 100)
    ticket = client.post(
        "/v1/integrations/open-erp/admin-launch-tickets",
        headers=INTEGRATION_HEADERS,
        json={
            "request_id": "launch-expiring",
            "platform": "pdd",
            "external_store_id": "mall-001",
            "platform_account_ref": "pdd-account-main",
            "ttl_seconds": 1,
        },
    ).json()
    monkeypatch.setattr(open_erp_module.time, "time", lambda: 102)

    missing = client.post("/v1/admin/auth/launch/exchange", json={})
    not_found = client.post("/v1/admin/auth/launch/exchange", json={"launch_token": "cslaunch_missing"})
    expired = client.post("/v1/admin/auth/launch/exchange", json={"launch_token": ticket["launch_token"]})

    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "validation_error"
    assert missing.json()["errorId"] == "ECS-LAUNCH-004"
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "launch_token_not_found"
    assert not_found.json()["errorId"] == "ECS-LAUNCH-003"
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "launch_token_expired"
    assert expired.json()["errorId"] == "ECS-LAUNCH-002"
