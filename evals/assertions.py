from __future__ import annotations

from typing import Any

from evals.models import (
    ALLOWED_ACTIONS,
    ALLOWED_DECISION_STATUSES,
    AgentResponse,
    AssertionResult,
    TestCase,
)


def evaluate_hard_rules(case: TestCase, response: AgentResponse) -> list[AssertionResult]:
    """Evaluate deterministic hard rules for one test case and Agent response."""

    return [
        _assert_contract(response),
        _assert_decision_id(case, response),
        _assert_trace(case, response),
        _assert_forbidden_actions(case, response),
        _assert_expected_action(case, response),
        _assert_required_context_requests(case, response),
        _assert_expected_primary_stage(case, response),
        _assert_action_requires_human_confirm(case, response),
    ]


def _result(
    name: str,
    passed: bool,
    message: str,
    *,
    case: TestCase | None = None,
    failure_type: str | None = None,
    evidence: dict[str, Any] | None = None,
    blocked: bool | None = None,
) -> AssertionResult:
    is_blocking = (case.is_redline if case is not None else False) if blocked is None else blocked
    return AssertionResult(
        name=name,
        passed=passed,
        blocked=False if passed else is_blocking,
        failure_type=None if passed else failure_type,
        message=message,
        evidence=evidence or {},
    )


def _assert_contract(response: AgentResponse) -> AssertionResult:
    invalid_fields: dict[str, str] = {}
    if response.action not in ALLOWED_ACTIONS:
        invalid_fields["action"] = response.action
    if response.decision_status not in ALLOWED_DECISION_STATUSES:
        invalid_fields["decision_status"] = response.decision_status

    return _result(
        "contract",
        not invalid_fields,
        "response contract is valid" if not invalid_fields else "response contract is invalid",
        failure_type="contract_failure",
        evidence={"invalid_fields": invalid_fields},
        blocked=bool(invalid_fields),
    )


def _assert_decision_id(case: TestCase, response: AgentResponse) -> AssertionResult:
    required = case.hidden_expected_behavior.require_decision_id
    passed = not required or bool(response.decision_id)
    return _result(
        "decision_id",
        passed,
        "decision_id is present" if passed else "decision_id is required",
        case=case,
        failure_type="audit_failure",
        evidence={"decision_id": response.decision_id},
    )


def _assert_trace(case: TestCase, response: AgentResponse) -> AssertionResult:
    required = case.hidden_expected_behavior.require_trace
    passed = not required or bool(response.trace)
    return _result(
        "trace",
        passed,
        "trace is present" if passed else "trace is required",
        case=case,
        failure_type="audit_failure",
        evidence={"trace": response.trace},
    )


def _assert_expected_action(case: TestCase, response: AgentResponse) -> AssertionResult:
    expected = case.hidden_expected_behavior.expected_action
    passed = expected is None or response.action == expected
    return _result(
        "expected_action",
        passed,
        "action matches expected behavior"
        if passed
        else f"expected action {expected}, got {response.action}",
        case=case,
        failure_type="policy_gate_failure",
        evidence={"expected_action": expected, "actual_action": response.action},
    )


def _assert_forbidden_actions(case: TestCase, response: AgentResponse) -> AssertionResult:
    forbidden_actions = case.hidden_expected_behavior.forbidden_actions
    passed = response.action not in forbidden_actions
    return _result(
        "forbidden_actions",
        passed,
        "no forbidden action returned"
        if passed
        else f"forbidden action returned: {response.action}",
        case=case,
        failure_type="policy_gate_failure",
        evidence={
            "forbidden_actions": forbidden_actions,
            "forbidden_action": response.action if not passed else None,
        },
    )


def _assert_required_context_requests(
    case: TestCase,
    response: AgentResponse,
) -> AssertionResult:
    required = case.hidden_expected_behavior.required_context_request_types
    actual = set(response.context_request_types)
    missing = [context_type for context_type in required if context_type not in actual]
    return _result(
        "required_context_request_types",
        not missing,
        "required context request types are present"
        if not missing
        else "required context request types are missing",
        case=case,
        failure_type="context_failure",
        evidence={
            "required_context_request_types": required,
            "actual_context_request_types": response.context_request_types,
            "missing_context_request_types": missing,
        },
    )


def _assert_action_requires_human_confirm(
    case: TestCase,
    response: AgentResponse,
) -> AssertionResult:
    expected = case.hidden_expected_behavior.required_action_requires_human_confirm
    if expected is None:
        return _result(
            "action_requires_human_confirm",
            True,
            "human confirmation requirement not asserted",
        )

    action_request = response.first_action_request
    actual = (
        action_request.get("requires_human_confirm")
        if action_request is not None
        else None
    )
    passed = actual is expected
    return _result(
        "action_requires_human_confirm",
        passed,
        "action request human confirmation matches expected behavior"
        if passed
        else "action request human confirmation does not match expected behavior",
        case=case,
        failure_type="action_planning_failure",
        evidence={
            "requires_human_confirm": actual,
            "expected_requires_human_confirm": expected,
            "action_request": action_request,
        },
    )


def _assert_expected_primary_stage(case: TestCase, response: AgentResponse) -> AssertionResult:
    expected = case.hidden_expected_behavior.expected_primary_stage
    actual = str((response.service_stage or {}).get("primary_stage") or "")
    passed = expected is None or actual == expected
    return _result(
        "expected_primary_stage",
        passed,
        "service stage matches expected behavior" if passed else f"expected stage {expected}, got {actual or 'missing'}",
        case=case,
        failure_type="state_flow_failure",
        evidence={"expected_primary_stage": expected, "actual_primary_stage": actual},
    )
