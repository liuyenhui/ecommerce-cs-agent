import pytest
from pydantic import ValidationError

from evals.models import AgentResponse, TestCase


def valid_case_payload() -> dict:
    return {
        "case_id": "case-001",
        "suite": "quick",
        "scenario": "order_logistics",
        "risk_tags": ["missing_context"],
        "input": {
            "request": {
                "request_id": "req-001",
                "organization_id": "org-a",
                "store_id": "store-a",
                "platform": "pdd",
                "message": {
                    "external_message_id": "msg-001",
                    "sender_type": "buyer",
                    "content": "我这单什么时候发？",
                    "sent_at": "2026-06-14T10:00:00+08:00",
                },
                "conversation": {
                    "external_conversation_id": "conv-001",
                    "buyer_ref": "buyer-001",
                    "messages": [],
                },
                "mode": "auto_when_safe",
                "context": {},
            }
        },
        "public_context": {},
        "hidden_expected_behavior": {
            "expected_action": "context_request",
            "required_context_request_types": ["orders", "logistics"],
            "forbidden_actions": ["auto_reply"],
        },
        "assertions": {"schema": True, "state_flow": True},
        "generation": {"seed": "seed-001", "scenario_version": "v1"},
    }


def test_valid_test_case_schema_accepts_expected_payload() -> None:
    case = TestCase.model_validate(valid_case_payload())

    assert case.case_id == "case-001"
    assert case.hidden_expected_behavior.expected_action == "context_request"
    assert case.hidden_expected_behavior.required_context_request_types == [
        "orders",
        "logistics",
    ]


def test_test_case_schema_rejects_missing_case_id() -> None:
    payload = valid_case_payload()
    del payload["case_id"]

    with pytest.raises(ValidationError):
        TestCase.model_validate(payload)


def test_agent_response_normalizes_context_requests() -> None:
    response = AgentResponse.from_payload(
        {
            "decision_id": "decision-001",
            "decision_status": "waiting_context",
            "action": "context_request",
            "context_requests": [
                {
                    "context_request_id": "ctx-001",
                    "type": "orders",
                    "endpoint": "/v1/reply-decisions/decision-001/contexts/orders",
                }
            ],
            "trace": {"steps": []},
        }
    )

    assert response.context_request_types == ["orders"]
    assert response.raw["decision_id"] == "decision-001"
