from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from tests.admin_fixtures import create_test_app


def client() -> TestClient:
    app = create_test_app()
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-agent-token"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def billing_lease(request_id: str, external_store_id: str) -> str:
    payload = {
        "iss": "open_erp_agent",
        "aud": "ecommerce-cs-agent",
        "reservation_id": f"reservation-{request_id}",
        "request_id": request_id,
        "platform": "pdd",
        "external_store_id": external_store_id,
        "feature": "ai_cs.reply_decision",
        "quantity": 1,
        "exp": int(time.time()) + 300,
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(b"test-open-erp-billing-secret", encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def minimal_reply_request(request_id: str = "req-001", content: str = "这个订单什么时候发货？") -> dict:
    return {
        "request_id": request_id,
        "organization_id": "org-001",
        "store_id": "store-001",
        "platform": "pdd",
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": content,
            "sent_at": "2026-06-12T10:15:00+08:00",
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-hash-001",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {"products": [], "orders": [], "logistics": [], "rules": []},
        "billing_lease": billing_lease(request_id, "store-001"),
    }


def platform_listing_reply_request(request_id: str = "req-listing", content: str = "这个商品有哪些尺寸？") -> dict:
    return {
        "request_id": request_id,
        "platform": "pdd",
        "external_store_id": "pdd-store-001",
        "platform_account_ref": "pdd-account-main",
        "listing_ref": "pdd-listing-001",
        "external_product_id": "pdd-product-001",
        "external_sku_id": "pdd-sku-001",
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": content,
            "sent_at": "2026-06-12T10:15:00+08:00",
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-hash-001",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {"orders": [], "logistics": [], "rules": []},
        "billing_lease": billing_lease(request_id, "pdd-store-001"),
    }


def test_health_is_public_and_stateless():
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "ecommerce-cs-agent-api"


def test_reply_decision_requires_external_bearer_token():
    response = client().post("/v1/reply-decisions", json=minimal_reply_request())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_reply_decision_requests_missing_order_and_logistics_context_and_is_idempotent():
    first = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-shipping"),
    )
    second = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-shipping"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert second.json()["decision_id"] == body["decision_id"]
    assert body["action"] == "context_request"
    assert body["decision_status"] == "waiting_context"
    assert body["missing_context"] == ["orders", "logistics"]
    assert [item["type"] for item in body["context_requests"]] == ["orders", "logistics"]
    assert body["trace"]["graph_version"] == "reply-decision-graph-v1"
    assert body["trace"]["steps"]


def test_reply_decision_request_idempotency_is_scoped_by_store():
    api = client()
    first_payload = minimal_reply_request("req-shared-store-scope", "这个商品是什么材质？")
    second_payload = {
        **minimal_reply_request("req-shared-store-scope", "这个商品是什么材质？"),
        "store_id": "store-002",
        "billing_lease": billing_lease("req-shared-store-scope", "store-002"),
    }

    first = api.post("/v1/reply-decisions", headers=auth_headers(), json=first_payload)
    second = api.post("/v1/reply-decisions", headers=auth_headers(), json=second_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["decision_id"] != second.json()["decision_id"]
    assert first.json()["trace"]["thread_id"] == first.json()["decision_id"]
    assert second.json()["trace"]["thread_id"] == second.json()["decision_id"]


def test_reply_decision_accepts_platform_store_listing_context_without_public_organization_id():
    response = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=platform_listing_reply_request(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "context_request"
    assert body["missing_context"] == ["products"]
    assert body["context_requests"][0]["type"] == "products"
    assert body["context_requests"][0]["query"] == {
        "platform": "pdd",
        "external_store_id": "pdd-store-001",
        "platform_account_ref": "pdd-account-main",
        "listing_ref": "pdd-listing-001",
        "external_product_id": "pdd-product-001",
        "external_sku_id": "pdd-sku-001",
        "buyer_ref": "buyer-hash-001",
        "conversation_id": "conv-req-listing",
    }
    assert body["trace"]["tenant_id"].startswith("tenant-")


def test_reply_decision_trace_contains_replayable_graph_steps():
    response = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-graph", "这个商品有什么材质？"),
    )

    assert response.status_code == 200
    steps = response.json()["trace"]["steps"]
    names = [step["name"] for step in steps]
    assert names == [
        "normalize_request",
        "retrieve_context",
        "classify_service_stage",
        "classify_intent",
        "context_gate",
        "policy_gate",
        "persist_trace",
    ]
    assert all(step["status"] == "completed" for step in steps)
    assert all(step["outputs_ref"] for step in steps)
    graph = response.json()["trace"]["graph"]
    assert [node["id"] for node in graph["nodes"]] == [
        "normalize_request",
        "retrieve_context",
        "classify_service_stage",
        "classify_intent",
        "context_gate",
        "action_gate",
        "generate_candidate",
        "policy_gate",
        "persist_trace",
    ]
    assert next(node for node in graph["nodes"] if node["id"] == "action_gate")["status"] == "skipped"
    assert next(node for node in graph["nodes"] if node["id"] == "generate_candidate")["status"] == "skipped"
    assert graph["edges"]
    assert any(edge["condition"] == "context_request" and edge["taken"] for edge in graph["edges"])


def test_reply_decision_action_request_skips_candidate_generation():
    response = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-action-graph", "请帮我改备注：周末送达"),
    )

    assert response.status_code == 200
    payload = response.json()
    graph = payload["trace"]["graph"]
    assert payload["action"] == "action_request"
    assert next(node for node in graph["nodes"] if node["id"] == "action_gate")["status"] == "completed"
    assert next(node for node in graph["nodes"] if node["id"] == "generate_candidate")["status"] == "skipped"
    assert any(edge["condition"] == "action_request" and edge["taken"] for edge in graph["edges"])


def test_high_risk_message_is_not_auto_replied():
    response = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-risk", "你们必须退款赔偿，否则我投诉平台"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "handoff"
    assert body["decision_status"] == "handoff"
    assert body["auto_reply"] is None
    assert "refund_or_complaint" in body["risk_flags"]


def test_action_intent_returns_structured_action_request():
    response = client().post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-action", "帮我把订单备注改成红色包装"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "action_request"
    assert body["decision_status"] == "action_request"
    assert body["action_requests"][0]["action_type"] == "update-note"
    assert body["action_requests"][0]["requires_human_confirm"] is True


def test_context_refill_and_action_result_are_idempotent():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-refill"),
    ).json()

    refill_payload = {
        "context_request_id": decision["context_requests"][0]["context_request_id"],
        "idempotency_key": "ctx-key-001",
        "organization_id": "org-001",
        "store_id": "store-001",
        "source": "external-system",
        "captured_at": "2026-06-12T10:16:00+08:00",
        "orders": [{"external_order_id": "order-001", "status": "paid"}],
    }
    first_refill = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json=refill_payload,
    )
    second_refill = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json=refill_payload,
    )

    assert first_refill.status_code == 200
    assert second_refill.status_code == 200
    assert first_refill.json() == second_refill.json()
    assert first_refill.json()["accepted"] is True

    unknown_action = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json={
            "action_id": "action-unknown",
            "action_type": "update-note",
            "idempotency_key": "unknown-action-key",
            "status": "succeeded",
            "executed_at": "2026-06-12T10:16:00+08:00",
        },
    )

    action_decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-action-result-idempotent", "帮我把订单备注改成红色包装"),
    ).json()
    action_payload = {
        "action_id": action_decision["action_requests"][0]["action_id"],
        "action_type": "update-note",
        "idempotency_key": "action-key-001",
        "status": "succeeded",
        "external_result": {"external_ref": "ok"},
        "error": None,
        "executed_at": "2026-06-12T10:16:00+08:00",
    }
    action_first = api.post(
        f"/v1/reply-decisions/{action_decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json=action_payload,
    )
    action_second = api.post(
        f"/v1/reply-decisions/{action_decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json=action_payload,
    )

    assert unknown_action.status_code == 422
    assert action_first.status_code == 200
    assert action_second.json() == action_first.json()
    assert action_first.json()["accepted"] is True


def test_typed_context_refills_accept_openapi_payloads_and_resume_with_typed_arrays():
    api = client()
    captured_at = "2026-06-12T10:16:00+08:00"

    product_decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-openapi-products", "这个商品是什么材质？"),
    ).json()
    product_request = next(item for item in product_decision["context_requests"] if item["type"] == "products")
    product_refill = api.post(
        f"/v1/reply-decisions/{product_decision['decision_id']}/contexts/products",
        headers=auth_headers(),
        json={
            "context_request_id": product_request["context_request_id"],
            "idempotency_key": "ctx-openapi-products",
            "captured_at": captured_at,
            "products": [{"external_product_id": "product-001", "title": "测试商品"}],
        },
    )

    shipping_decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-openapi-shipping"),
    ).json()
    order_request = next(item for item in shipping_decision["context_requests"] if item["type"] == "orders")
    logistics_request = next(item for item in shipping_decision["context_requests"] if item["type"] == "logistics")
    order_refill = api.post(
        f"/v1/reply-decisions/{shipping_decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json={
            "context_request_id": order_request["context_request_id"],
            "idempotency_key": "ctx-openapi-orders",
            "captured_at": captured_at,
            "orders": [{"external_order_id": "order-001", "status": "paid"}],
        },
    )
    logistics_refill = api.post(
        f"/v1/reply-decisions/{shipping_decision['decision_id']}/contexts/logistics",
        headers=auth_headers(),
        json={
            "context_request_id": logistics_request["context_request_id"],
            "idempotency_key": "ctx-openapi-logistics",
            "captured_at": captured_at,
            "logistics": [{"external_order_id": "order-001", "status": "in_transit"}],
        },
    )

    rule_decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-openapi-rules", "退换货规则是什么？"),
    ).json()
    rule_request = next(item for item in rule_decision["context_requests"] if item["type"] == "rules")
    rule_refill = api.post(
        f"/v1/reply-decisions/{rule_decision['decision_id']}/contexts/rules",
        headers=auth_headers(),
        json={
            "context_request_id": rule_request["context_request_id"],
            "idempotency_key": "ctx-openapi-rules",
            "captured_at": captured_at,
            "rules": [{"rule_id": "rule-001", "rule_type": "returns", "version": "1"}],
        },
    )

    assert product_refill.status_code == 200
    assert product_refill.json()["missing_context"] == []
    assert order_refill.status_code == 200
    assert order_refill.json()["next_action"] == "wait_context"
    assert logistics_refill.status_code == 200
    assert logistics_refill.json()["missing_context"] == []
    assert rule_refill.status_code == 200
    assert rule_refill.json()["missing_context"] == []


def test_context_refill_requires_openapi_idempotency_key_and_captured_at():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-refill-required-fields", "这个商品是什么材质？"),
    ).json()
    context_request_id = decision["context_requests"][0]["context_request_id"]

    response = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/products",
        headers=auth_headers(),
        json={"context_request_id": context_request_id, "products": []},
    )

    assert response.status_code == 422


def test_continuations_return_not_found_for_unknown_decision():
    api = client()
    context_response = api.post(
        "/v1/reply-decisions/decision-missing/contexts/products",
        headers=auth_headers(),
        json={
            "context_request_id": "ctx-products-missing",
            "idempotency_key": "ctx-missing",
            "captured_at": "2026-06-12T10:16:00+08:00",
            "products": [],
        },
    )
    action_response = api.post(
        "/v1/reply-decisions/decision-missing/actions/results",
        headers=auth_headers(),
        json={
            "action_id": "action-missing",
            "action_type": "update-note",
            "idempotency_key": "action-missing",
            "status": "succeeded",
            "executed_at": "2026-06-12T10:16:00+08:00",
        },
    )

    assert context_response.status_code == 404
    assert action_response.status_code == 404


def test_action_result_uses_openapi_succeeded_status_and_rejects_success_alias():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-action-openapi-status", "帮我把订单备注改成红色包装"),
    ).json()
    action = decision["action_requests"][0]
    base_payload = {
        "action_id": action["action_id"],
        "action_type": action["action_type"],
        "executed_at": "2026-06-12T10:16:00+08:00",
    }

    invalid = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json={**base_payload, "idempotency_key": "action-invalid-success", "status": "success"},
    )
    succeeded = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json={**base_payload, "idempotency_key": "action-succeeded", "status": "succeeded"},
    )

    assert invalid.status_code == 422
    assert succeeded.status_code == 200
    assert succeeded.json()["decision_status"] == "answer_ready"
    assert succeeded.json()["next_action"] == "decide"


def test_context_refill_rejects_cross_tenant_and_idempotency_conflict():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-refill-conflict"),
    ).json()
    payload = {
        "context_request_id": decision["context_requests"][0]["context_request_id"],
        "idempotency_key": "ctx-key-conflict",
        "organization_id": "org-001",
        "store_id": "store-001",
        "source": "external-system",
        "captured_at": "2026-06-12T10:16:00+08:00",
        "orders": [{"external_order_id": "order-001", "status": "paid"}],
    }
    cross_tenant = {**payload, "organization_id": "org-other"}

    forbidden = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json=cross_tenant,
    )
    first = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json=payload,
    )
    conflict = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json={**payload, "orders": [{"external_order_id": "order-002", "status": "paid"}]},
    )

    assert forbidden.status_code == 403
    assert first.status_code == 200
    assert conflict.status_code == 409


def test_context_refill_rejects_payload_scope_aliases_for_platform_token():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-refill-scope-alias"),
    ).json()

    response = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json={
            "context_request_id": decision["context_requests"][0]["context_request_id"],
            "idempotency_key": "ctx-scope-alias",
            "captured_at": "2026-06-12T10:16:00+08:00",
            "tenant_id": "org-other",
            "external_store_id": "store-other",
            "orders": [{"external_order_id": "order-001", "status": "paid"}],
        },
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "scope",
    [
        {"tenant_id": "org-other"},
        {"organization_id": "org-other"},
        {"external_store_id": "store-other"},
        {"store_id": "store-other"},
        {"tenant_id": "org-001", "organization_id": "org-other"},
        {"external_store_id": "store-001", "store_id": "store-other"},
    ],
    ids=[
        "tenant-id-mismatch",
        "organization-id-mismatch",
        "external-store-id-mismatch",
        "store-id-mismatch",
        "tenant-alias-conflict",
        "store-alias-conflict",
    ],
)
def test_context_refill_rejects_each_declared_scope_alias_mismatch(scope: dict[str, str]):
    api = client()
    request_id = "req-scope-" + "-".join(scope)
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request(request_id),
    ).json()

    response = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers=auth_headers(),
        json={
                "context_request_id": decision["context_requests"][0]["context_request_id"],
                "idempotency_key": f"ctx-{request_id}",
                "captured_at": "2026-06-12T10:16:00+08:00",
                **scope,
                "orders": [{"external_order_id": "order-001", "status": "paid"}],
        },
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("planned_type", "endpoint_type", "content"),
    [
        ("orders", "products", "这个订单什么时候发货？"),
        ("products", "orders", "这个商品是什么材质？"),
        ("products", "logistics", "这个商品是什么材质？"),
        ("products", "rules", "这个商品是什么材质？"),
    ],
)
def test_typed_context_refill_rejects_endpoint_type_mismatch(
    planned_type: str,
    endpoint_type: str,
    content: str,
):
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request(f"req-context-type-{endpoint_type}", content),
    ).json()
    planned_request = next(item for item in decision["context_requests"] if item["type"] == planned_type)

    response = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/{endpoint_type}",
        headers=auth_headers(),
        json={
            "context_request_id": planned_request["context_request_id"],
            "idempotency_key": f"ctx-type-{endpoint_type}",
            "captured_at": "2026-06-12T10:16:00+08:00",
            endpoint_type: [],
        },
    )

    assert response.status_code == 422


def test_action_result_rejects_unknown_action_and_idempotency_conflict():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-action-result-rejections", "帮我把订单备注改成红色包装"),
    ).json()
    action_id = decision["action_requests"][0]["action_id"]
    payload = {
        "action_id": action_id,
        "action_type": "update-note",
        "idempotency_key": "action-result-rejection-key",
        "status": "succeeded",
        "external_result": {"external_ref": "ok"},
        "executed_at": "2026-06-12T10:16:00+08:00",
    }

    unknown_action = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json={**payload, "action_id": "action-unknown"},
    )
    wrong_action_type = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json={**payload, "action_type": "change-address", "idempotency_key": "wrong-action-type"},
    )
    first = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json=payload,
    )
    conflict = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json={**payload, "status": "failed"},
    )

    assert unknown_action.status_code == 422
    assert wrong_action_type.status_code == 422
    assert first.status_code == 200
    assert conflict.status_code == 409


def test_feedback_and_message_trace_round_trip():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-feedback", "这个商品有什么材质？"),
    ).json()

    feedback = api.post(
        "/v1/feedback/human-replies",
        headers=auth_headers(),
        json={
            "decision_id": decision["decision_id"],
            "message_id": "msg-req-feedback",
            "human_reply": "这款商品材质以商品详情页为准，我帮您再确认。",
            "used_candidate": False,
            "resolution_status": "resolved",
            "labels": [],
        },
    )
    trace = api.get(
        f"/v1/message-traces/{decision['decision_id']}",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )

    assert feedback.status_code == 200
    assert feedback.json()["accepted"] is True
    assert feedback.json()["knowledge_candidate_id"] is None
    assert trace.status_code == 200
    assert trace.json()["decision_id"] == decision["decision_id"]
    assert trace.json()["request_id"] == "req-feedback"
    assert trace.json()["trace"]["graph"]["nodes"]
    assert trace.json()["trace"]["graph"]["edges"]


def test_human_reply_feedback_requires_auth():
    api = client()
    decision = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-feedback-rejections", "这个商品有什么材质？"),
    ).json()
    payload = {
        "decision_id": decision["decision_id"],
        "message_id": "msg-req-feedback-rejections",
        "human_reply": "这款商品材质以商品详情页为准。",
        "used_candidate": False,
        "resolution_status": "resolved",
        "labels": [],
    }

    unauthenticated = api.post("/v1/feedback/human-replies", json=payload)
    assert unauthenticated.status_code == 401


def test_customer_admin_message_traces_are_scoped_to_session_store():
    api = client()
    visible = api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-customer-visible", "这个商品有什么材质？"),
    ).json()
    api.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json={**minimal_reply_request("req-customer-hidden", "这个商品有什么材质？"), "store_id": "store-other"},
    )

    response = api.get(
        "/v1/admin/message-traces",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["decision_id"] for item in body["items"]] == [visible["decision_id"]]
    assert body["items"][0]["store_id"] == "store-001"
    assert body["items"][0]["customer_message"] == "这个商品有什么材质？"
    assert body["items"][0]["service_stage"]["primary_stage"] == "pre_sale"
    assert body["items"][0]["trace"]["graph"]["nodes"]


def test_customer_admin_simulation_creates_trace_without_external_send():
    api = client()

    response = api.post(
        "/v1/admin/message-simulations",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
        json={"message": {"content": "这个商品有哪些尺寸？"}, "platform": "pdd"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "simulation"
    assert body["decision"]["decision_id"]
    assert body["decision"]["trace"]["steps"]
    assert body["external_send"] == {"attempted": False, "reason": "simulation_only"}

    traces = api.get(
        "/v1/admin/message-traces?source=simulation",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )
    assert traces.status_code == 200
    assert traces.json()["items"][0]["decision_id"] == body["decision"]["decision_id"]
    assert traces.json()["items"][0]["source"] == "simulation"


def test_future_contract_routes_return_explicit_501():
    response = client().post(
        "/v1/events/messages",
        headers=auth_headers(),
        json={
            "request_id": "event-001",
            "organization_id": "org-001",
            "store_id": "store-001",
            "platform": "pdd",
            "message": {"content": "hello"},
        },
    )

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"
