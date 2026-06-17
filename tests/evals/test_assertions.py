from evals.assertions import evaluate_hard_rules
from evals.models import AgentResponse, TestCase


def make_case(
    expected: dict,
    risk_tags: list[str] | None = None,
    case_id: str = "case-001",
) -> TestCase:
    return TestCase.model_validate(
        {
            "case_id": case_id,
            "suite": "quick",
            "scenario": "policy",
            "risk_tags": risk_tags or [],
            "input": {"request": {"request_id": f"req-{case_id}"}},
            "public_context": {},
            "hidden_expected_behavior": expected,
            "assertions": {},
            "generation": {"seed": "seed-001"},
        }
    )


def make_response(payload: dict) -> AgentResponse:
    base = {
        "decision_id": "decision-001",
        "decision_status": "waiting_context",
        "action": "context_request",
        "context_requests": [],
        "trace": {"steps": []},
    }
    base.update(payload)
    return AgentResponse.from_payload(base)


def test_required_context_request_types_pass_when_all_types_present() -> None:
    case = make_case(
        {
            "expected_action": "context_request",
            "required_context_request_types": ["orders", "logistics"],
        }
    )
    response = make_response(
        {
            "context_requests": [
                {"context_request_id": "ctx-orders", "type": "orders"},
                {"context_request_id": "ctx-logistics", "type": "logistics"},
            ]
        }
    )

    results = evaluate_hard_rules(case, response)

    assert all(result.passed for result in results)


def test_missing_context_request_type_reports_context_failure() -> None:
    case = make_case(
        {
            "expected_action": "context_request",
            "required_context_request_types": ["orders", "logistics"],
        }
    )
    response = make_response(
        {"context_requests": [{"context_request_id": "ctx-orders", "type": "orders"}]}
    )

    results = evaluate_hard_rules(case, response)

    failures = [result for result in results if not result.passed]
    assert failures[0].failure_type == "context_failure"
    assert failures[0].blocked is False
    assert failures[0].evidence["missing_context_request_types"] == ["logistics"]


def test_forbidden_auto_reply_in_redline_case_is_blocking_policy_failure() -> None:
    case = make_case(
        {
            "expected_action": "handoff",
            "forbidden_actions": ["auto_reply"],
            "redline_tags": ["high_risk_auto_reply"],
        },
        risk_tags=["redline", "refund"],
    )
    response = make_response(
        {
            "decision_status": "answer_ready",
            "action": "auto_reply",
            "context_requests": [],
        }
    )

    results = evaluate_hard_rules(case, response)

    forbidden_failure = next(
        result for result in results if result.failure_type == "policy_gate_failure"
    )
    assert forbidden_failure.blocked is True
    assert forbidden_failure.evidence["forbidden_action"] == "auto_reply"


def test_action_request_requires_human_confirm_when_expected() -> None:
    case = make_case(
        {
            "expected_action": "action_request",
            "required_action_requires_human_confirm": True,
        },
        risk_tags=["redline", "action"],
    )
    response = make_response(
        {
            "decision_status": "action_request",
            "action": "action_request",
            "action_request": {
                "action_id": "act-001",
                "action_type": "update-address",
                "requires_human_confirm": False,
            },
            "context_requests": [],
        }
    )

    results = evaluate_hard_rules(case, response)

    failure = next(
        result
        for result in results
        if result.failure_type == "action_planning_failure"
    )
    assert failure.blocked is True
    assert failure.evidence["requires_human_confirm"] is False
