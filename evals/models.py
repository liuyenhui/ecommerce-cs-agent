from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AllowedAction = Literal[
    "auto_reply",
    "candidate",
    "handoff",
    "context_request",
    "action_request",
]

AllowedDecisionStatus = Literal[
    "received",
    "waiting_context",
    "partial_context",
    "ready_to_decide",
    "answer_ready",
    "candidate",
    "action_request",
    "handoff",
    "failed",
]

FailureType = Literal[
    "contract_failure",
    "state_flow_failure",
    "permission_failure",
    "context_failure",
    "retrieval_failure",
    "generation_failure",
    "policy_gate_failure",
    "action_planning_failure",
    "audit_failure",
    "judge_uncertain",
    "test_data_issue",
]

ALLOWED_ACTIONS = set(AllowedAction.__args__)
ALLOWED_DECISION_STATUSES = set(AllowedDecisionStatus.__args__)


class ExpectedBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_action: str | None = None
    required_context_request_types: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    redline_tags: list[str] = Field(default_factory=list)
    required_action_requires_human_confirm: bool | None = None
    require_decision_id: bool = True
    require_trace: bool = True
    min_judge_score: float | None = None
    expected_primary_stage: Literal["pre_sale", "in_sale", "after_sale", "unknown"] | None = None


class TestCase(BaseModel):
    __test__ = False

    model_config = ConfigDict(extra="forbid")

    case_id: str
    suite: str = "quick"
    scenario: str
    risk_tags: list[str] = Field(default_factory=list)
    input: dict[str, Any]
    public_context: dict[str, Any] = Field(default_factory=dict)
    hidden_expected_behavior: ExpectedBehavior
    assertions: dict[str, Any] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_redline(self) -> bool:
        tags = {tag.lower() for tag in self.risk_tags}
        tags.update(tag.lower() for tag in self.hidden_expected_behavior.redline_tags)
        return "redline" in tags or bool(self.hidden_expected_behavior.redline_tags)

    @property
    def request_payload(self) -> dict[str, Any]:
        request = self.input.get("request")
        if not isinstance(request, dict):
            return {}
        return request


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    context_request_id: str | None = None
    type: str
    endpoint: str | None = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision_id: str | None = None
    decision_status: str
    action: str
    candidates: list[Any] = Field(default_factory=list)
    auto_reply: Any = None
    context_requests: list[ContextRequest] = Field(default_factory=list)
    remaining_context_requests: list[ContextRequest] = Field(default_factory=list)
    action_request: dict[str, Any] | None = None
    action_requests: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] | None = None
    service_stage: dict[str, Any] | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AgentResponse":
        normalized = dict(payload)
        if not normalized.get("action") and normalized.get("decision_status") == "partial_context":
            normalized["action"] = "context_request"
        response = cls.model_validate(normalized)
        response.raw = normalized
        return response

    @property
    def context_request_types(self) -> list[str]:
        return [request.type for request in self.context_requests]

    @property
    def first_action_request(self) -> dict[str, Any] | None:
        if self.action_request is not None:
            return self.action_request
        if self.action_requests:
            return self.action_requests[0]
        return None


class AssertionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    blocked: bool = False
    failure_type: FailureType | None = None
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    passed: bool
    reason: str
    failure_type: FailureType | None = None
    needs_review: bool = False


class TestCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    suite: str
    scenario: str
    passed: bool
    blocked: bool
    failure_types: list[str] = Field(default_factory=list)
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    judge_result: JudgeResult
    agent_response: dict[str, Any]
    context_refill_calls: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class TestRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    suite: str
    target: str
    started_at: datetime
    completed_at: datetime | None = None
    results: list[TestCaseResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def start(cls, run_id: str, suite: str, target: str) -> "TestRunResult":
        return cls(
            run_id=run_id,
            suite=suite,
            target=target,
            started_at=datetime.now(UTC),
        )

    def complete(self) -> None:
        self.completed_at = datetime.now(UTC)
        total = len(self.results)
        passed = sum(1 for result in self.results if result.passed)
        blocked = sum(1 for result in self.results if result.blocked)
        average_score = (
            sum(result.judge_result.score for result in self.results) / total
            if total
            else 0.0
        )
        self.summary = {
            "total": total,
            "passed": passed,
            "blocked": blocked,
            "pass_rate": passed / total if total else 0.0,
            "average_score": average_score,
        }
