from __future__ import annotations

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app


def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-agent-token"}


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
        "items": [{"external_order_id": "order-001", "status": "paid"}],
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

    action_payload = {
        "action_id": "action-001",
        "action_type": "update-note",
        "idempotency_key": "action-key-001",
        "status": "success",
        "external_result": {"external_ref": "ok"},
        "error": None,
        "executed_at": "2026-06-12T10:16:00+08:00",
    }
    action_first = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json=action_payload,
    )
    action_second = api.post(
        f"/v1/reply-decisions/{decision['decision_id']}/actions/results",
        headers=auth_headers(),
        json=action_payload,
    )

    assert action_first.status_code == 200
    assert action_second.json() == action_first.json()
    assert action_first.json()["accepted"] is True


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
        "items": [{"external_order_id": "order-001", "status": "paid"}],
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
        json={**payload, "items": [{"external_order_id": "order-002", "status": "paid"}]},
    )

    assert forbidden.status_code == 403
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
    assert trace.status_code == 200
    assert trace.json()["decision_id"] == decision["decision_id"]
    assert trace.json()["request_id"] == "req-feedback"


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
