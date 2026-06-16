from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import httpx

from evals.assertions import evaluate_hard_rules
from evals.judge import judge_response
from evals.models import (
    AgentResponse,
    ContextRequest,
    TestCase,
    TestCaseResult,
    TestRunResult,
)


DEFAULT_REPORTS_DIR = Path("reports/evals")


def load_cases(path: Path, *, suite: str | None = None) -> list[TestCase]:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    cases: list[TestCase] = []
    for case_path in paths:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        case = TestCase.model_validate(payload)
        if suite is None or case.suite == suite:
            cases.append(case)
    return cases


class MockAgentClient:
    def create_decision(self, case: TestCase) -> AgentResponse:
        expected = case.hidden_expected_behavior
        action = expected.expected_action or (
            "context_request" if expected.required_context_request_types else "candidate"
        )
        decision_status = _status_for_action(action)
        payload: dict[str, Any] = {
            "decision_id": f"mock-{case.case_id}",
            "decision_status": decision_status,
            "action": action,
            "candidates": [],
            "auto_reply": None,
            "context_requests": [],
            "action_request": None,
            "trace": {
                "mock": True,
                "case_id": case.case_id,
                "scenario": case.scenario,
                "steps": [{"name": "mock_decision", "status": "completed"}],
            },
        }
        if action == "context_request":
            payload["context_requests"] = [
                {
                    "context_request_id": f"ctx-{case.case_id}-{context_type}",
                    "type": context_type,
                    "endpoint": f"/v1/reply-decisions/mock-{case.case_id}/contexts/{context_type}",
                    "reason": "mock context gap",
                }
                for context_type in expected.required_context_request_types
            ]
        if action == "action_request":
            payload["action_request"] = {
                "action_id": f"act-{case.case_id}",
                "action_type": "mock-action",
                "payload": {},
                "requires_human_confirm": bool(
                    expected.required_action_requires_human_confirm
                ),
            }
        return AgentResponse.from_payload(payload)

    def refill_context(
        self,
        case: TestCase,
        response: AgentResponse,
        context_request: ContextRequest,
    ) -> AgentResponse:
        return AgentResponse.from_payload(
            {
                "decision_id": response.decision_id,
                "decision_status": "partial_context",
                "action": "context_request",
                "context_requests": [],
                "remaining_context_requests": [],
                "trace": {
                    "mock": True,
                    "case_id": case.case_id,
                    "refilled_context_type": context_request.type,
                },
            }
        )


class LiveAgentClient:
    def __init__(self, target_url: str, *, auth_token: str | None = None) -> None:
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        self._client = httpx.Client(
            base_url=target_url.rstrip("/"),
            headers=headers,
            timeout=30.0,
        )

    def create_decision(self, case: TestCase) -> AgentResponse:
        response = self._client.post("/v1/reply-decisions", json=case.request_payload)
        response.raise_for_status()
        return AgentResponse.from_payload(response.json())

    def refill_context(
        self,
        case: TestCase,
        response: AgentResponse,
        context_request: ContextRequest,
    ) -> AgentResponse:
        endpoint = context_request.endpoint or (
            f"/v1/reply-decisions/{response.decision_id}/contexts/{context_request.type}"
        )
        payload = {
            "context_request_id": context_request.context_request_id,
            context_request.type: _public_context_for(case, context_request.type),
        }
        refill_response = self._client.post(endpoint, json=payload)
        refill_response.raise_for_status()
        return AgentResponse.from_payload(refill_response.json())


def run_cases(
    *,
    cases: Iterable[TestCase],
    suite: str,
    target: str,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    run_id: str | None = None,
    target_url: str | None = None,
    auth_token: str | None = None,
) -> TestRunResult:
    run_id = run_id or f"{suite}-{uuid4().hex[:12]}"
    client = _make_client(target=target, target_url=target_url, auth_token=auth_token)
    run = TestRunResult.start(run_id=run_id, suite=suite, target=target)

    for case in cases:
        run.results.append(_run_case(case, client))

    run.complete()
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{run_id}.jsonl"
    with report_path.open("w", encoding="utf-8") as report_file:
        for result in run.results:
            report_file.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
            report_file.write("\n")
    return run


def _run_case(case: TestCase, client: MockAgentClient | LiveAgentClient) -> TestCaseResult:
    response = client.create_decision(case)
    context_refill_calls: list[str] = []
    for context_request in response.context_requests:
        client.refill_context(case, response, context_request)
        context_refill_calls.append(context_request.type)

    assertion_results = evaluate_hard_rules(case, response)
    judge_result = judge_response(case, response, assertion_results)
    failed_assertions = [result for result in assertion_results if not result.passed]
    blocked = any(result.blocked for result in assertion_results)
    failure_types = _failure_types(failed_assertions, judge_result.failure_type)
    passed = not failed_assertions and judge_result.passed and not blocked

    return TestCaseResult(
        case_id=case.case_id,
        suite=case.suite,
        scenario=case.scenario,
        passed=passed,
        blocked=blocked,
        failure_types=failure_types,
        assertion_results=assertion_results,
        judge_result=judge_result,
        agent_response=response.raw,
        context_refill_calls=context_refill_calls,
        evidence={
            "risk_tags": case.risk_tags,
            "expected_behavior": case.hidden_expected_behavior.model_dump(mode="json"),
        },
    )


def _make_client(
    *,
    target: str,
    target_url: str | None,
    auth_token: str | None,
) -> MockAgentClient | LiveAgentClient:
    if target == "mock":
        return MockAgentClient()
    url = target_url or os.environ.get("TARGET_BASE_URL")
    if not url:
        raise ValueError("target_url or TARGET_BASE_URL is required for live target")
    token = auth_token or os.environ.get("AGENT_API_TOKEN")
    return LiveAgentClient(url, auth_token=token)


def _status_for_action(action: str) -> str:
    return {
        "auto_reply": "answer_ready",
        "candidate": "candidate",
        "handoff": "handoff",
        "context_request": "waiting_context",
        "action_request": "action_request",
    }.get(action, "failed")


def _public_context_for(case: TestCase, context_type: str) -> Any:
    if context_type in case.public_context:
        return case.public_context[context_type]
    prefixed_key = f"known_{context_type}"
    if prefixed_key in case.public_context:
        return case.public_context[prefixed_key]
    return []


def _failure_types(
    failed_assertions: list[Any],
    judge_failure_type: str | None,
) -> list[str]:
    ordered: list[str] = []
    for assertion in failed_assertions:
        if assertion.failure_type and assertion.failure_type not in ordered:
            ordered.append(assertion.failure_type)
    if judge_failure_type and judge_failure_type not in ordered:
        ordered.append(judge_failure_type)
    return ordered
