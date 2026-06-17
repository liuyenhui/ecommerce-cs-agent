from __future__ import annotations

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app
from tests.api.test_v1_api import auth_headers, minimal_reply_request


def test_system_admin_message_traces_list_reads_real_decisions() -> None:
    client = TestClient(create_app())
    decision = client.post(
        "/v1/reply-decisions",
        headers=auth_headers(),
        json=minimal_reply_request("req-system-trace", "什么时候发货？"),
    ).json()

    traces = client.get(
        "/v1/system-admin/message-traces?organization_id=org-001&store_id=store-001",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    assert traces.status_code == 200
    assert traces.json()["items"][0]["decision_id"] == decision["decision_id"]
    assert traces.json()["items"][0]["request_id"] == "req-system-trace"
    assert traces.json()["page"]["total"] >= 1


def test_system_admin_task_retry_rejects_unknown_or_non_retryable_task() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/system-admin/tasks/task-missing/retry",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
        json={"reason": "manual retry"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
