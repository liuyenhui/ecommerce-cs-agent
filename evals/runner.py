from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    status: int | None
    message: str
    summary: dict[str, Any]


def load_cases(path: Path, *, suite: str | None = None) -> list[TestCase]:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    cases: list[TestCase] = []
    for case_path in paths:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        case = TestCase.model_validate(payload)
        if suite is None or case.suite == suite:
            cases.append(case)
    return cases


class LiveAgentClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 10.0,
        *,
        auth_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.token = auth_token or token
        self.timeout = timeout
        headers = {
            "Accept": "application/json",
            "User-Agent": "ecommerce-cs-agent-evals/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    def get_json(self, path: str) -> tuple[int, Any]:
        try:
            response = self._client.get(path)
            return response.status_code, _parse_response(response)
        except httpx.TimeoutException as exc:
            raise RuntimeError("network failure: request timed out") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"network failure: {exc}") from exc

    def post_json(self, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        try:
            response = self._client.post(path, json=payload)
            return response.status_code, _parse_response(response)
        except httpx.TimeoutException as exc:
            raise RuntimeError("network failure: request timed out") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"network failure: {exc}") from exc

    def create_decision(self, case: TestCase) -> AgentResponse:
        response = self._client.post("/v1/reply-decisions", json=_unique_live_request_payload(case))
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
            "idempotency_key": f"eval-{case.case_id}-{context_request.type}",
            "organization_id": case.request_payload.get("organization_id", "org-eval"),
            "store_id": case.request_payload.get("store_id", "store-eval"),
            "source": case.request_payload.get("source", "eval"),
            context_request.type: _public_context_for(case, context_request.type),
        }
        refill_response = self._client.post(endpoint, json=payload)
        refill_response.raise_for_status()
        return AgentResponse.from_payload(refill_response.json())


class MockAgentClient:
    def get_json(self, path: str) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"status": "ok", "service": "mock-agent"}
        return 404, {"error": "not_found"}

    def post_json(self, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        if path != "/v1/reply-decisions":
            return 404, {"error": "not_found"}
        decision_id = f"mock-{payload.get('request_id', 'decision')}"
        return 200, {
            "decision_id": decision_id,
            "action": "candidate",
            "decision_status": "candidate",
        }

    def create_decision(self, case: TestCase) -> AgentResponse:
        expected = case.hidden_expected_behavior
        action = expected.expected_action or (
            "context_request" if expected.required_context_request_types else "candidate"
        )
        payload: dict[str, Any] = {
            "decision_id": f"mock-{case.case_id}",
            "decision_status": _status_for_action(action),
            "action": action,
            "candidates": [],
            "auto_reply": None,
            "context_requests": [],
            "action_requests": [],
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
            payload["action_requests"] = [payload["action_request"]]
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


class QuickLiveSuite:
    def __init__(self, client: LiveAgentClient | MockAgentClient):
        self.client = client

    def run(self) -> list[CheckResult]:
        results = [self.check_health()]
        if results[-1].passed:
            results.append(self.check_reply_decision())
        else:
            results.append(
                CheckResult(
                    name="reply-decisions",
                    passed=False,
                    status=None,
                    message="skipped because health check failed",
                    summary={},
                )
            )
        return results

    def check_health(self) -> CheckResult:
        try:
            status, body = self.client.get_json("/health")
        except RuntimeError as exc:
            return CheckResult("health", False, None, str(exc), {})
        passed = 200 <= status < 300
        return CheckResult(
            name="health",
            passed=passed,
            status=status,
            message="ok" if passed else "contract/runtime failure: non-2xx response",
            summary=_body_summary(body),
        )

    def check_reply_decision(self) -> CheckResult:
        try:
            status, body = self.client.post_json(
                "/v1/reply-decisions",
                build_minimal_reply_decision_request(),
            )
        except RuntimeError as exc:
            return CheckResult("reply-decisions", False, None, str(exc), {})

        summary = _decision_summary(body)
        passed = 200 <= status < 300 and bool(summary.get("decision_id"))
        if passed:
            message = "ok"
        elif 200 <= status < 300:
            message = "contract/runtime failure: response missing decision_id"
        else:
            message = "contract/runtime failure: non-2xx response"
        return CheckResult("reply-decisions", passed, status, message, summary)


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
    run_id = run_id or f"{suite}-{uuid.uuid4().hex[:12]}"
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


def build_minimal_reply_decision_request() -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    request_id = f"eval-quick-{uuid.uuid4().hex}"
    return {
        "request_id": request_id,
        "organization_id": "org-eval",
        "platform": "pdd",
        "store_id": "store-eval",
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": "When will this order ship?",
            "sent_at": now,
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-eval",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {
            "products": [],
            "orders": [],
            "logistics": [],
            "rules": [],
        },
    }


def format_result(result: CheckResult) -> str:
    status = f" status={result.status}" if result.status is not None else " status=unavailable"
    prefix = "PASS" if result.passed else "FAIL"
    details = _format_summary(result.summary)
    if details:
        return f"{prefix} {result.name}{status} {details}"
    return f"{prefix} {result.name}{status} {result.message}"


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


def _unique_live_request_payload(case: TestCase) -> dict[str, Any]:
    payload = copy.deepcopy(case.request_payload)
    suffix = uuid.uuid4().hex[:12]
    payload["request_id"] = f"{payload.get('request_id') or case.case_id}-{suffix}"

    message = payload.get("message")
    if isinstance(message, dict):
        original_message_id = message.get("external_message_id") or f"msg-{case.case_id}"
        message["external_message_id"] = f"{original_message_id}-{suffix}"

    conversation = payload.get("conversation")
    if isinstance(conversation, dict):
        original_conversation_id = conversation.get("external_conversation_id") or f"conv-{case.case_id}"
        if payload.get("source") != "simulation":
            conversation["external_conversation_id"] = f"{original_conversation_id}-{suffix}"

    return payload


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


def _format_summary(summary: dict[str, Any]) -> str:
    fields = []
    for key in ("decision_id", "action", "decision_status"):
        value = summary.get(key)
        if value is not None:
            fields.append(f"{key}={value}")
    return " ".join(fields)


def _decision_summary(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    return {
        "decision_id": body.get("decision_id"),
        "action": body.get("action"),
        "decision_status": body.get("decision_status"),
    }


def _body_summary(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        return {key: body.get(key) for key in ("status", "service", "environment") if key in body}
    return {}


def _parse_response(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text[:200]
