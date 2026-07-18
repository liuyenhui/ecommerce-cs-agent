from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from evals.assertions import evaluate_hard_rules
from evals.judge import judge_response
from evals.models import AgentResponse, AssertionResult, ExpectedBehavior, TestCase


ALLOWED_CONTEXT_TYPES = {"products", "orders", "logistics"}
PRIVATE_FIELD_NAMES = {
    "buyer_name", "receiver_name", "phone", "mobile", "address",
    "receiver_address", "full_address",
}
TRACKING_FIELD_NAMES = {"tracking_no", "tracking_number", "waybill_no"}
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SimulationGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{24,64}$")
    generated_at: str | None = None
    steps: list[str] = Field(default_factory=list)


class SimulationExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_action: str | None = None
    required_context_request_types: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=lambda: ["auto_reply"])
    handoff_required: bool = False
    fact_refs: list[str] = Field(default_factory=list)
    required_answer_terms: list[str] = Field(default_factory=list)
    forbidden_answer_terms: list[str] = Field(default_factory=list)
    referenced_entity_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_context_types(self) -> "SimulationExpected":
        unsupported = set(self.required_context_request_types) - ALLOWED_CONTEXT_TYPES
        if unsupported:
            raise ValueError(f"unsupported simulation context types: {sorted(unsupported)}")
        return self


class SimulationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    expected: SimulationExpected


class SimulationConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1)
    turns: list[SimulationTurn] = Field(min_length=3, max_length=5)


class SimulationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_version: str
    suite: str
    generation: SimulationGeneration
    snapshot: dict[str, Any]
    conversations: list[SimulationConversation]

    @model_validator(mode="after")
    def validate_fixed_fixture(self, info: ValidationInfo) -> "SimulationFixture":
        allow_partial = bool(info.context and info.context.get("allow_partial"))
        if not allow_partial and len(self.conversations) != 10:
            raise ValueError("simulation fixture must contain exactly 10 conversations")
        total = sum(len(item.turns) for item in self.conversations)
        if not allow_partial and total < 30:
            raise ValueError("simulation fixture must contain at least 30 turns")
        actual_hash = str(self.snapshot.get("snapshot_hash") or snapshot_sha256(self.snapshot))
        if actual_hash != self.generation.snapshot_sha256:
            raise ValueError("snapshot hash does not match fixed fixture metadata")
        _validate_privacy(self.snapshot)
        _validate_privacy([item.model_dump(mode="json") for item in self.conversations])
        for conversation in self.conversations:
            for turn in conversation.turns:
                for fact_ref in turn.expected.fact_refs:
                    _resolve_fact_ref(self.snapshot, fact_ref)
        return self


class SimulationRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    started_at: datetime
    completed_at: datetime
    rows: list[dict[str, Any]]
    summary: dict[str, Any]


class SimulationRunner:
    def __init__(self, client: Any, *, reports_dir: Path = Path("reports/evals")) -> None:
        self.client = client
        self.reports_dir = reports_dir

    def run(self, fixture: SimulationFixture, *, run_id: str) -> SimulationRunResult:
        started_at = datetime.now(UTC)
        rows: list[dict[str, Any]] = []
        for conversation in fixture.conversations:
            history: list[dict[str, Any]] = []
            for turn_index, turn in enumerate(conversation.turns):
                case = _turn_case(fixture, conversation, turn, turn_index, history)
                initial = self.client.create_decision(case)
                final = initial
                refill_calls: list[str] = []
                for context_request in initial.context_requests:
                    if context_request.type not in ALLOWED_CONTEXT_TYPES:
                        continue
                    final = self.client.refill_context(case, final, context_request)
                    refill_calls.append(context_request.type)
                final.raw.setdefault(
                    "external_send", {"attempted": False, "reason": "simulation_runner_has_no_send_path"}
                )
                base_assertions = evaluate_hard_rules(case, initial)
                simulation_assertions = assert_simulation_response(turn, final, fixture.snapshot)
                assertions = base_assertions + simulation_assertions
                judge = judge_response(case, final, assertions)
                failed = [item for item in assertions if not item.passed]
                blocked = any(item.blocked for item in failed)
                passed = not failed and judge.passed and not judge.needs_review and not blocked
                assistant_content = _response_text(final) or "[no candidate response]"
                rows.append(
                    {
                        "case_id": case.case_id,
                        "conversation_id": conversation.conversation_id,
                        "turn_id": turn.turn_id,
                        "turn_index": turn_index,
                        "scenario": turn.scenario,
                        "passed": passed,
                        "blocked": blocked,
                        "needs_review": judge.needs_review,
                        "context_refill_calls": refill_calls,
                        "assertion_results": [item.model_dump(mode="json") for item in assertions],
                        "judge_result": judge.model_dump(mode="json"),
                        "agent_response": final.raw,
                        "fixture": {
                            "generation_model": fixture.generation.model,
                            "generated_at": fixture.generation.generated_at,
                            "generation_steps": fixture.generation.steps,
                            "snapshot_sha256": fixture.generation.snapshot_sha256,
                        },
                    }
                )
                history.extend(
                    [
                        _history_message("buyer", turn.message, turn.turn_id),
                        _history_message("assistant", assistant_content, f"reply-{turn.turn_id}"),
                    ]
                )
        completed_at = datetime.now(UTC)
        passed_count = sum(row["passed"] is True for row in rows)
        blocked_count = sum(row["blocked"] is True for row in rows)
        needs_review_count = sum(row["needs_review"] is True for row in rows)
        summary = {
            "run_id": run_id,
            "suite": fixture.suite,
            "generation_model": fixture.generation.model,
            "generated_at": fixture.generation.generated_at,
            "generation_steps": fixture.generation.steps,
            "snapshot_sha256": fixture.generation.snapshot_sha256,
            "conversations": len(fixture.conversations),
            "total_messages": len(rows),
            "passed": passed_count,
            "blocked": blocked_count,
            "needs_review": needs_review_count,
            "all_messages_passed": bool(rows) and passed_count == len(rows) and blocked_count == 0 and needs_review_count == 0,
        }
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.reports_dir / f"{run_id}.jsonl"
        report_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        (self.reports_dir / f"{run_id}-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return SimulationRunResult(
            run_id=run_id, started_at=started_at, completed_at=completed_at, rows=rows, summary=summary
        )


def load_simulation_fixture(snapshot_path: Path, conversations_path: Path) -> SimulationFixture:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    definition = json.loads(conversations_path.read_text(encoding="utf-8"))
    declared_hash = str(definition.pop("snapshot_hash"))
    generation_model = str(definition.pop("generation_model"))
    generated_at = definition.pop("generated_at", None)
    generation_steps = definition.pop("generation_steps", [])
    return SimulationFixture.model_validate(
        {
            **definition,
            "generation": {
                "model": generation_model,
                "snapshot_sha256": declared_hash,
                "generated_at": generated_at,
                "steps": generation_steps,
            },
            "snapshot": snapshot,
        }
    )


def assert_simulation_response(
    turn: SimulationTurn, response: AgentResponse, snapshot: dict[str, Any]
) -> list[AssertionResult]:
    trace = response.trace or {}
    graph_complete = all(
        trace.get(field) for field in ("thread_id", "graph_version", "langgraph_checkpoint_id", "steps")
    )
    external_send = response.raw.get("external_send") or trace.get("external_send", {})
    no_external_send = external_send.get("attempted") is False
    text = _response_text(response)
    expected_terms = list(turn.expected.required_answer_terms)
    expected_terms.extend(str(_resolve_fact_ref(snapshot, ref)) for ref in turn.expected.fact_refs)
    missing_terms = [term for term in expected_terms if term not in text]
    forbidden_terms = [term for term in turn.expected.forbidden_answer_terms if term in text]
    missing_entities = [entity for entity in turn.expected.referenced_entity_ids if entity not in text]
    handoff_ok = not turn.expected.handoff_required or response.action == "handoff"
    return [
        _sim_result("trace_complete", graph_complete, "LangGraph trace is complete", "audit_failure"),
        _sim_result("no_external_send", no_external_send, "simulation did not attempt external send", "policy_gate_failure", blocked=True),
        _sim_result("snapshot_facts", not missing_terms and not forbidden_terms, "answer is grounded in snapshot expectations", "generation_failure", evidence={"missing_terms": missing_terms, "forbidden_terms": forbidden_terms}),
        _sim_result("multi_turn_reference", not missing_entities, "multi-turn reference resolved to expected entities", "context_failure", evidence={"missing_entity_ids": missing_entities}),
        _sim_result("handoff_policy", handoff_ok, "handoff policy matches expectation", "policy_gate_failure", blocked=turn.expected.handoff_required),
    ]


def _turn_case(
    fixture: SimulationFixture,
    conversation: SimulationConversation,
    turn: SimulationTurn,
    turn_index: int,
    history: list[dict[str, Any]],
) -> TestCase:
    snapshot = fixture.snapshot
    store = snapshot.get("store", snapshot)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expected_action = "handoff" if turn.expected.handoff_required else turn.expected.expected_action
    return TestCase.model_validate(
        {
            "case_id": f"{conversation.conversation_id}-{turn.turn_id}",
            "suite": fixture.suite,
            "scenario": turn.scenario,
            "risk_tags": ["simulation"],
            "input": {
                "request": {
                    "request_id": f"sim-{conversation.conversation_id}-{turn.turn_id}",
                    "organization_id": store.get("organization_id", "org-simulation"),
                    "platform": store.get("platform", "mall"),
                    "store_id": store.get("store_id", store.get("external_store_id", "store-simulation")),
                    "source": "simulation",
                    "message": {
                        "external_message_id": f"msg-{conversation.conversation_id}-{turn.turn_id}",
                        "sender_type": "buyer",
                        "content": turn.message,
                        "sent_at": now,
                    },
                    "conversation": {
                        "external_conversation_id": conversation.conversation_id,
                        "buyer_ref": f"sim-buyer-{conversation.conversation_id}",
                        "messages": list(history),
                    },
                    "mode": "assist_first",
                    "context": {key: [] for key in ("products", "orders", "logistics", "rules")},
                }
            },
            "public_context": {key: snapshot.get(key, []) for key in ALLOWED_CONTEXT_TYPES},
            "hidden_expected_behavior": ExpectedBehavior(
                expected_action=expected_action,
                required_context_request_types=turn.expected.required_context_request_types,
                forbidden_actions=turn.expected.forbidden_actions,
                require_trace=True,
            ).model_dump(mode="json"),
            "generation": {
                "model": fixture.generation.model,
                "snapshot_sha256": fixture.generation.snapshot_sha256,
                "turn_index": turn_index,
            },
        }
    )


def _history_message(sender_type: str, content: str, message_id: str) -> dict[str, Any]:
    return {"external_message_id": message_id, "sender_type": sender_type, "content": content}


def _response_text(response: AgentResponse) -> str:
    values: list[str] = []
    if isinstance(response.auto_reply, str):
        values.append(response.auto_reply)
    elif isinstance(response.auto_reply, dict):
        values.extend(str(response.auto_reply.get(key, "")) for key in ("content", "text", "reply_text"))
    for candidate in response.candidates:
        if isinstance(candidate, str):
            values.append(candidate)
        elif isinstance(candidate, dict):
            values.extend(str(candidate.get(key, "")) for key in ("content", "text", "reply", "reply_text"))
    return "\n".join(value for value in values if value)


def _sim_result(
    name: str,
    passed: bool,
    message: str,
    failure_type: str,
    *,
    evidence: dict[str, Any] | None = None,
    blocked: bool = False,
) -> AssertionResult:
    return AssertionResult(
        name=name,
        passed=passed,
        blocked=blocked and not passed,
        failure_type=None if passed else failure_type,
        message=message if passed else f"{message} failed",
        evidence=evidence or {},
    )


def _resolve_fact_ref(snapshot: Any, reference: str) -> Any:
    current = snapshot
    for part in reference.split("."):
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"fact ref is absent from snapshot: {reference}") from exc
    if isinstance(current, (dict, list)):
        raise ValueError(f"fact ref must point to a scalar snapshot value: {reference}")
    return current


def _validate_privacy(value: Any, path: str = "fixture") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if normalized in PRIVATE_FIELD_NAMES:
                raise ValueError(f"private field is forbidden in simulation fixture: {path}.{key}")
            if normalized in TRACKING_FIELD_NAMES and (not isinstance(child, str) or "*" not in child):
                raise ValueError(f"unmasked tracking field is forbidden in simulation fixture: {path}.{key}")
            _validate_privacy(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_privacy(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if PHONE_RE.search(value):
            raise ValueError(f"private phone-like value is forbidden in simulation fixture: {path}")
