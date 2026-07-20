import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.models import AgentResponse
from evals.simulation import (
    SimulationFixture,
    SimulationRunner,
    assert_simulation_response,
    load_simulation_fixture,
    snapshot_sha256,
)


def fixture_payload() -> dict:
    snapshot = {
        "store": {"platform": "mall", "external_store_id": "972824439"},
        "products": [{"external_product_id": "p-1", "title": "宠物香波", "price": "39.90"}],
        "orders": [{"external_order_id": "order-mask-1", "status": "paid"}],
        "logistics": [{"external_order_id": "order-mask-1", "status": "in_transit", "tracking_no_masked": "SF****7890"}],
    }
    digest = snapshot_sha256(snapshot)
    conversations = []
    for conversation_index in range(10):
        turns = []
        for turn_index in range(3):
            turns.append(
                {
                    "turn_id": f"t-{conversation_index}-{turn_index}",
                    "message": f"第 {turn_index + 1} 个问题",
                    "scenario": "product" if turn_index < 2 else "logistics",
                    "expected": {
                        "expected_action": "candidate",
                        "required_context_request_types": [],
                        "fact_refs": ["products.0.title"],
                        "required_answer_terms": ["宠物香波"],
                    },
                }
            )
        conversations.append({"conversation_id": f"c-{conversation_index}", "turns": turns})
    return {
        "fixture_version": "1",
        "suite": "acs-simulation",
        "generation": {"model": "configured-model", "snapshot_sha256": digest},
        "snapshot": snapshot,
        "conversations": conversations,
    }


def test_fixture_requires_fixed_ten_conversations_and_thirty_turns() -> None:
    fixture = SimulationFixture.model_validate(fixture_payload())
    assert len(fixture.conversations) == 10
    assert sum(len(item.turns) for item in fixture.conversations) == 30

    invalid = fixture_payload()
    invalid["conversations"] = invalid["conversations"][:9]
    with pytest.raises(ValidationError):
        SimulationFixture.model_validate(invalid)


def test_fixture_rejects_snapshot_hash_mismatch_and_private_buyer_data() -> None:
    mismatch = fixture_payload()
    mismatch["generation"]["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="snapshot hash"):
        SimulationFixture.model_validate(mismatch)

    private = fixture_payload()
    private["snapshot"]["orders"][0]["buyer_name"] = "张三"
    private["generation"]["snapshot_sha256"] = snapshot_sha256(private["snapshot"])
    with pytest.raises(ValidationError, match="private field"):
        SimulationFixture.model_validate(private)


class RecordingClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def create_decision(self, case):
        self.requests.append(case.request_payload)
        return AgentResponse.from_payload(
            {
                "decision_id": f"d-{case.case_id}",
                "decision_status": "candidate",
                "action": "candidate",
                "candidates": [{"content": "宠物香波"}],
                "context_requests": [],
                "trace": {
                    "thread_id": f"d-{case.case_id}",
                    "graph_version": "reply-decision-graph-v1",
                    "langgraph_checkpoint_id": "cp-1",
                    "steps": [{"name": "normalize_request", "status": "completed"}],
                    "external_send": {"attempted": False},
                    "model": {
                        "model_version": "configured-model", "route_role": "primary",
                        "status": "succeeded", "fallback_used": False,
                        "validation_status": "passed",
                    },
                },
            }
        )

    def refill_context(self, case, response, context_request):
        raise AssertionError("no refill expected")


def test_runner_accumulates_history_and_forces_simulation_source(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["conversations"] = payload["conversations"][:1]
    fixture = SimulationFixture.model_validate(payload, context={"allow_partial": True})
    client = RecordingClient()

    result = SimulationRunner(client, reports_dir=tmp_path).run(fixture, run_id="sim-1")

    assert result.summary["total_messages"] == 3
    assert result.summary["passed"] == 3
    assert all(request["source"] == "simulation" for request in client.requests)
    assert len(client.requests[0]["conversation"]["messages"]) == 0
    assert len(client.requests[1]["conversation"]["messages"]) == 2
    assert len(client.requests[2]["conversation"]["messages"]) == 4
    assert (tmp_path / "sim-1.jsonl").exists()
    assert (tmp_path / "sim-1-conversations.json").exists()
    safe_rows = json.loads((tmp_path / "sim-1-conversations.json").read_text())
    assert safe_rows[0]["model"] == {
        "model_version": "configured-model", "route_role": "primary",
        "status": "succeeded", "fallback_used": False, "validation_status": "passed",
    }
    summary = json.loads((tmp_path / "sim-1-summary.json").read_text())
    assert summary["snapshot_sha256"] == fixture.generation.snapshot_sha256
    assert summary["all_messages_passed"] is True


def test_turn_case_expects_initial_context_request_before_final_handoff() -> None:
    payload = fixture_payload()
    payload["conversations"] = payload["conversations"][:1]
    payload["conversations"][0]["turns"][0]["expected"].update(
        {"handoff_required": True, "required_context_request_types": ["products"]}
    )
    fixture = SimulationFixture.model_validate(payload, context={"allow_partial": True})
    from evals.simulation import _turn_case

    case = _turn_case(fixture, fixture.conversations[0], fixture.conversations[0].turns[0], 0, [])

    assert case.hidden_expected_behavior.expected_action == "context_request"


def test_simulation_assertions_reject_external_send_and_missing_trace() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0]
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-1",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"content": "宠物香波"}],
            "trace": {"external_send": {"attempted": True}},
        }
    )

    assertions = assert_simulation_response(turn, response, fixture.snapshot)

    failures = {item.name for item in assertions if not item.passed}
    assert "trace_complete" in failures
    assert "no_external_send" in failures


def test_simulation_assertions_check_final_handoff_action() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0].model_copy(
        update={
            "expected": fixture.conversations[0].turns[0].expected.model_copy(
                update={"handoff_required": True, "required_answer_terms": []}
            )
        }
    )
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-handoff",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": "需要人工客服进一步核实。"}],
            "trace": {
                "thread_id": "d-handoff",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-handoff",
                "steps": [{"name": "policy_gate", "status": "completed"}],
                "external_send": {"attempted": False},
            },
        }
    )

    failures = {item.name for item in assert_simulation_response(turn, response, fixture.snapshot) if not item.passed}

    assert "final_action" in failures


def test_simulation_rejects_deterministic_fallback_as_model_success() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0]
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-fallback",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": "宠物香波"}],
            "trace": {
                "thread_id": "d-fallback", "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-fallback",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
                "model": {
                    "model_version": "deterministic-reply-v1", "route_role": None,
                    "status": "failed", "fallback_used": True, "validation_status": "rejected",
                },
            },
        }
    )

    failures = {item.name for item in assert_simulation_response(turn, response, fixture.snapshot) if not item.passed}

    assert "model_generation_succeeded" in failures


def test_simulation_accepts_successful_node_binding_model_evidence() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0]
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-node-binding",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": "宠物香波"}],
            "context_requests": [],
            "trace": {
                "thread_id": "d-node-binding",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-node-binding",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
                "model": {
                    "model_version": "deepseek-v4-pro",
                    "route_role": "node_binding",
                    "status": "succeeded",
                    "fallback_used": False,
                    "validation_status": "passed",
                },
            },
        }
    )

    assertions = assert_simulation_response(turn, response, fixture.snapshot)

    assert next(item for item in assertions if item.name == "model_generation_succeeded").passed


def test_simulation_rejects_context_dump_as_customer_reply() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0]
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-json-dump",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [
                {
                    "reply_text": '{"products":[{"external_product_id":"p-1","title":"宠物香波"},'
                    '{"external_product_id":"p-2","title":"无关商品"}]}'
                }
            ],
            "trace": {
                "thread_id": "d-json-dump",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-json-dump",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
            },
        }
    )

    assertions = assert_simulation_response(turn, response, fixture.snapshot)
    failures = {item.name for item in assertions if not item.passed}

    assert {"natural_language", "answers_current_question", "single_relevant_entity"} <= failures


@pytest.mark.parametrize(
    ("message", "reply", "expected_failure"),
    [
        ("这款商品是什么？", '{"products":[{"title":"宠物香波"}]}', "natural_language"),
        ("这款商品多少钱？", "请以商品详情页为准。", "answers_current_question"),
        (
            "商品 p-1 多少钱？",
            "商品p-1、商品p-2、商品p-3、商品p-4全部信息如下……",
            "single_relevant_entity",
        ),
        ("明天能到吗？", "明天肯定送到。", "safe_uncertainty"),
    ],
)
def test_simulation_quality_assertions_reject_bad_customer_replies(
    message: str, reply: str, expected_failure: str
) -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0].model_copy(
        update={
            "message": message,
            "expected": fixture.conversations[0].turns[0].expected.model_copy(
                update={
                    "fact_refs": [],
                    "required_answer_terms": ["39.90"] if "多少钱" in message else [],
                    "referenced_entity_ids": ["p-1"] if "p-1" in message else [],
                }
            ),
        }
    )
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-bad-reply",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": reply}],
            "trace": {
                "thread_id": "d-bad-reply",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-bad-reply",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
            },
        }
    )

    assertions = assert_simulation_response(turn, response, fixture.snapshot)

    assert any(item.name == expected_failure and not item.passed for item in assertions)


def test_simulation_quality_assertions_accept_concise_grounded_chinese_reply() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0].model_copy(
        update={
            "message": "商品 p-1 多少钱？",
            "expected": fixture.conversations[0].turns[0].expected.model_copy(
                update={"fact_refs": [], "required_answer_terms": ["39.90"], "referenced_entity_ids": ["p-1"]}
            ),
        }
    )
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-good-reply",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": "商品 p-1 当前价格为39.90元。"}],
            "trace": {
                "thread_id": "d-good-reply",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-good-reply",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
            },
        }
    )

    quality = {
        item.name: item.passed
        for item in assert_simulation_response(turn, response, fixture.snapshot)
        if item.name in {"natural_language", "answers_current_question", "single_relevant_entity", "safe_uncertainty"}
    }

    assert quality == {
        "natural_language": True,
        "answers_current_question": True,
        "single_relevant_entity": True,
        "safe_uncertainty": True,
    }


def test_real_redacted_snapshot_and_fixed_conversations_form_valid_fixture() -> None:
    snapshot_path = Path(
        "/Users/huiliu/.config/superpowers/worktrees/open_erp_agent/acs-context-simulation/"
        "artifacts/acs-evals/store-972824439-snapshot.json"
    )
    if not snapshot_path.exists():
        pytest.skip("delegated redacted snapshot artifact is not available")

    fixture = load_simulation_fixture(
        snapshot_path,
        Path("evals/cases/simulation/store-972824439-conversations.json"),
    )

    assert fixture.generation.snapshot_sha256 == "9128f2ef13710e6b826e271f"
    assert len(fixture.snapshot["products"]) == 17
    assert len(fixture.snapshot["orders"]) == 8
    assert len(fixture.snapshot["logistics"]) == 5
    assert sum(len(item.turns) for item in fixture.conversations) == 30


def test_fixed_missing_order_cases_require_actionable_order_reference_prompt() -> None:
    payload = json.loads(
        Path("evals/cases/simulation/store-972824439-conversations.json").read_text(encoding="utf-8")
    )
    turns = {
        turn["turn_id"]: turn
        for conversation in payload["conversations"]
        for turn in conversation["turns"]
    }

    for turn_id in ("mc-1", "mc-2"):
        terms = turns[turn_id]["expected"]["required_answer_terms"]
        assert "请提供订单尾号" in terms
        assert "信息不足" not in terms
