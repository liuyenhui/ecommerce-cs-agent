from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app


def make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AGENT_API_TOKEN", "dev-token")
    monkeypatch.setenv("APP_ENV", "test")
    return TestClient(create_app())


def base_request(content: str, context: dict | None = None) -> dict:
    return {
        "request_id": "req-001",
        "organization_id": "org-a",
        "store_id": "store-a-1",
        "platform": "pdd",
        "message": {
            "external_message_id": "msg-001",
            "sender_type": "buyer",
            "content": content,
            "sent_at": "2026-06-14T10:00:00+08:00",
        },
        "conversation": {
            "external_conversation_id": "conv-001",
            "buyer_ref": "buyer-a",
            "messages": [],
        },
        "mode": "auto_when_safe",
        "context": context or {},
    }


def test_health_does_not_require_auth(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ecommerce-cs-agent-api",
        "environment": "test",
    }


def test_reply_decision_requires_bearer_token(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.post(
        "/v1/reply-decisions",
        json=base_request("我这单怎么还没发货？"),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "missing bearer token"


def test_missing_order_logistics_returns_parallel_context_requests(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.post(
        "/v1/reply-decisions",
        headers={"Authorization": "Bearer dev-token"},
        json=base_request("我这单怎么还没发货？"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_status"] == "waiting_context"
    assert payload["action"] == "context_request"
    assert [request["type"] for request in payload["context_requests"]] == [
        "orders",
        "logistics",
    ]
    assert [step["name"] for step in payload["trace"]["steps"][:3]] == [
        "normalize_request",
        "retrieve_context",
        "classify_intent",
    ]
    assert payload["trace"]["graph"]["nodes"][0]["id"] == "normalize_request"


def test_redline_complaint_returns_handoff(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.post(
        "/v1/reply-decisions",
        headers={"Authorization": "Bearer dev-token"},
        json=base_request("不给我赔付我就投诉平台处罚你们。"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_status"] == "handoff"
    assert payload["action"] == "handoff"
    assert payload["handoff_reason"] == "high_risk_request"


def test_address_change_returns_action_request_with_human_confirm(monkeypatch) -> None:
    client = make_client(monkeypatch)

    response = client.post(
        "/v1/reply-decisions",
        headers={"Authorization": "Bearer dev-token"},
        json=base_request(
            "帮我把收货地址改掉，直接操作就行。",
            context={"orders": [{"external_order_id": "order-a-002"}]},
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_status"] == "action_request"
    assert payload["action"] == "action_request"
    assert payload["action_request"]["action_type"] == "change_shipping_address"
    assert payload["action_request"]["requires_human_confirm"] is True


def test_context_refill_returns_partial_context(monkeypatch) -> None:
    client = make_client(monkeypatch)
    decision = client.post(
        "/v1/reply-decisions",
        headers={"Authorization": "Bearer dev-token"},
        json=base_request("我这单怎么还没发货？"),
    ).json()
    order_request = next(item for item in decision["context_requests"] if item["type"] == "orders")

    response = client.post(
        f"/v1/reply-decisions/{decision['decision_id']}/contexts/orders",
        headers={"Authorization": "Bearer dev-token"},
        json={
            "context_request_id": order_request["context_request_id"],
            "idempotency_key": "ctx-orders-partial",
            "captured_at": "2026-06-14T10:01:00+08:00",
            "orders": [{"external_order_id": "order-a-001"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_id"] == decision["decision_id"]
    assert payload["decision_status"] == "partial_context"
    assert payload["next_action"] == "wait_context"
