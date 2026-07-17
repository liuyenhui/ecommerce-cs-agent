from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

from fastapi.testclient import TestClient

from tests.admin_fixtures import create_test_app


class RecordingDecisionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.block_started = threading.Event()
        self.block_release = threading.Event()
        self.block_create = False

    def _record(self, name: str) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            on_event_loop = False
        else:
            on_event_loop = True
        self.calls.append((name, on_event_loop))

    def create_reply_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._record("create_reply_decision")
        if self.block_create:
            self.block_started.set()
            assert self.block_release.wait(timeout=2)
        return {"decision_id": payload.get("request_id", "decision-test")}

    def refill_context(
        self,
        decision_id: str,
        context_type: str,
        payload: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self._record("refill_context")
        return {"decision_id": decision_id, "context_type": context_type, "payload": payload}

    def submit_action_result(
        self,
        decision_id: str,
        payload: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self._record("submit_action_result")
        return {"decision_id": decision_id, "status": payload["status"]}


def _reply_payload() -> dict[str, Any]:
    return {
        "request_id": "concurrency-reply",
        "organization_id": "org-001",
        "store_id": "store-001",
        "platform": "pdd",
        "message": {
            "external_message_id": "message-concurrency-reply",
            "sender_type": "buyer",
            "content": "什么时候发货？",
            "sent_at": "2026-07-17T10:00:00+08:00",
        },
        "conversation": {
            "external_conversation_id": "conversation-concurrency-reply",
            "buyer_ref": "buyer-test",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {"products": [], "orders": [], "logistics": [], "rules": []},
    }


def test_decision_graph_entrypoints_run_outside_event_loop_thread() -> None:
    decisions = RecordingDecisionService()
    api = TestClient(create_test_app(decision_service_override=decisions))

    reply = api.post(
        "/v1/reply-decisions",
        headers={"Authorization": "Bearer test-agent-token"},
        json=_reply_payload(),
    )
    context = api.post(
        "/v1/reply-decisions/decision-test/contexts/products",
        headers={"Authorization": "Bearer test-agent-token"},
        json={
            "context_request_id": "context-request-test",
            "idempotency_key": "context-idempotency-test",
            "captured_at": "2026-07-17T10:01:00+08:00",
            "products": [],
        },
    )
    action = api.post(
        "/v1/reply-decisions/decision-test/actions/results",
        headers={"Authorization": "Bearer test-agent-token"},
        json={
            "action_id": "action-test",
            "action_type": "update-note",
            "idempotency_key": "action-idempotency-test",
            "status": "succeeded",
            "executed_at": "2026-07-17T10:02:00+08:00",
        },
    )
    simulation = api.post(
        "/v1/admin/message-simulations",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
        json={"store_id": "store-001", "content": "这个商品多重？"},
    )

    assert [reply.status_code, context.status_code, action.status_code, simulation.status_code] == [
        200,
        200,
        200,
        201,
    ]
    assert decisions.calls == [
        ("create_reply_decision", False),
        ("refill_context", False),
        ("submit_action_result", False),
        ("create_reply_decision", False),
    ]
    assert simulation.json()["external_send"] == {
        "attempted": False,
        "reason": "simulation_only",
    }


def test_async_health_remains_responsive_while_decision_worker_is_blocked() -> None:
    decisions = RecordingDecisionService()
    decisions.block_create = True
    app = create_test_app(decision_service_override=decisions)
    health_route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    assert inspect.iscoroutinefunction(health_route.endpoint)

    with TestClient(app) as api:
        reply_result: list[int] = []

        def request_reply() -> None:
            response = api.post(
                "/v1/reply-decisions",
                headers={"Authorization": "Bearer test-agent-token"},
                json=_reply_payload(),
            )
            reply_result.append(response.status_code)

        request_thread = threading.Thread(target=request_reply)
        request_thread.start()
        assert decisions.block_started.wait(timeout=1)

        started_at = time.monotonic()
        health = api.get("/health")
        elapsed = time.monotonic() - started_at

        decisions.block_release.set()
        request_thread.join(timeout=2)

    assert health.status_code == 200
    assert elapsed < 0.5
    assert reply_result == [200]
