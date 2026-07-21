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
    fixture = SimulationFixture.model_validate(payload, context={"allow_partial": True})
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


@pytest.mark.parametrize(
    "reply",
    [
        "您的订单已发货，目前状态是待收货。",
        "已发货，当前待收货，物流为中通快递。",
    ],
)
def test_simulation_accepts_ordered_equivalent_compound_status_phrase(reply: str) -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0].model_copy(
        update={
            "expected": fixture.conversations[0].turns[0].expected.model_copy(
                update={"fact_refs": [], "required_answer_terms": ["已发货，待收货"]}
            )
        }
    )
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-status-equivalent",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": reply}],
            "trace": {
                "thread_id": "d-status-equivalent",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-status-equivalent",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
            },
        }
    )

    assertions = {item.name: item for item in assert_simulation_response(turn, response, fixture.snapshot)}

    assert assertions["snapshot_facts"].passed
    assert assertions["answers_current_question"].passed


def test_simulation_accepts_more_affordable_as_lower_price_with_exact_prices_preserved() -> None:
    payload = fixture_payload()
    fixture = SimulationFixture.model_validate(payload)
    turn = fixture.conversations[0].turns[0].model_copy(
        update={
            "expected": fixture.conversations[0].turns[0].expected.model_copy(
                update={
                    "fact_refs": [],
                    "required_answer_terms": ["75", "125", "价格更低"],
                }
            )
        }
    )
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-price-equivalent",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": "宠物喷雾活动价75元，狗碗活动价125元，宠物喷雾价格更实惠。"}],
            "trace": {
                "thread_id": "d-price-equivalent",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-price-equivalent",
                "steps": [{"name": "generate_candidate", "status": "completed"}],
                "external_send": {"attempted": False},
            },
        }
    )

    assertions = {item.name: item for item in assert_simulation_response(turn, response, fixture.snapshot)}

    assert assertions["snapshot_facts"].passed
    assert assertions["answers_current_question"].passed


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
    assert sum(len(item.turns) for item in fixture.conversations) == 50


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


def test_fixed_fixture_preserves_thirty_baseline_turns_and_adds_twenty_approved_tone_cases() -> None:
    payload = json.loads(
        Path("evals/cases/simulation/store-972824439-conversations.json").read_text(encoding="utf-8")
    )
    turns = [turn for conversation in payload["conversations"] for turn in conversation["turns"]]
    baseline_ids = [turn["turn_id"] for turn in turns if not turn["turn_id"].startswith("tone-")]
    tone_turns = [turn for turn in turns if turn["turn_id"].startswith("tone-")]

    assert baseline_ids == [
        "pa-1", "pa-2", "pa-3", "su-1", "su-2", "su-3", "pp-1", "pp-2", "pp-3",
        "ss-1", "ss-2", "ss-3", "co-1", "co-2", "co-3", "os-1", "os-2", "os-3",
        "ld-1", "ld-2", "ld-3", "lt-1", "lt-2", "lt-3", "rs-1", "rs-2", "rs-3",
        "mc-1", "mc-2", "mc-3",
    ]
    assert [turn["turn_id"] for turn in tone_turns] == [f"tone-{index:02d}" for index in range(1, 21)]
    assert len(turns) == 50
    assert payload["snapshot_hash"] == "9128f2ef13710e6b826e271f"
    assert payload["generation_model"] == "deepseek-v4-pro"
    assert payload["generated_at"]
    assert all(turn["coverage"] for turn in tone_turns)
    assert all(turn["style_assertions"] for turn in tone_turns)
    assert all(turn["human_review"]["approved"] is True for turn in tone_turns)
    assert all(turn["human_review"]["approved_at"] for turn in tone_turns)


def test_baseline_product_audience_turns_use_direct_audience_style_gate() -> None:
    payload = json.loads(
        Path("evals/cases/simulation/store-972824439-conversations.json").read_text(encoding="utf-8")
    )
    turns = {
        turn["turn_id"]: turn
        for conversation in payload["conversations"]
        for turn in conversation["turns"]
    }

    assert "style.direct_product_audience_answer" in turns["pa-1"]["style_assertions"]
    assert "style.direct_product_audience_answer" in turns["pa-2"]["style_assertions"]
    assert "style.direct_product_audience_answer" not in turns["pa-3"].get("style_assertions", [])


def test_tone_fixture_rejects_unapproved_or_unasserted_turn() -> None:
    payload = fixture_payload()
    tone = payload["conversations"][0]["turns"][0]
    tone.update(
        {
            "turn_id": "tone-01",
            "coverage": ["short_follow_up"],
            "style_assertions": ["style.direct_answer_first"],
            "human_review": {"approved": False, "approved_at": "2026-07-20T10:00:00+08:00"},
        }
    )
    with pytest.raises(ValidationError, match="approved"):
        SimulationFixture.model_validate(payload)

    tone["human_review"]["approved"] = True
    tone["style_assertions"] = []
    with pytest.raises(ValidationError, match="style assertions"):
        SimulationFixture.model_validate(payload)


def test_fixture_generation_requires_model_and_timestamp_for_tone_cases() -> None:
    payload = fixture_payload()
    payload["conversations"][0]["turns"][0].update(
        {
            "turn_id": "tone-01",
            "coverage": ["short_follow_up"],
            "style_assertions": ["style.direct_answer_first"],
            "human_review": {"approved": True, "approved_at": "2026-07-20T10:00:00+08:00"},
        }
    )
    payload["generation"]["generated_at"] = None

    with pytest.raises(ValidationError, match="generated_at"):
        SimulationFixture.model_validate(payload)


def _tone_assertions(message: str, reply: str, style_assertions: list[str]) -> dict[str, object]:
    payload = fixture_payload()
    turn = payload["conversations"][0]["turns"][0]
    turn.update(
        {
            "turn_id": "tone-01",
            "message": message,
            "coverage": ["tone"],
            "style_assertions": style_assertions,
            "human_review": {"approved": True, "approved_at": "2026-07-20T10:00:00+08:00"},
        }
    )
    payload["generation"]["generated_at"] = "2026-07-20T09:00:00+08:00"
    fixture = SimulationFixture.model_validate(payload, context={"allow_partial": True})
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-tone",
            "decision_status": "candidate",
            "action": "candidate",
            "candidates": [{"reply_text": reply}],
            "trace": {
                "thread_id": "d-tone",
                "graph_version": "reply-decision-graph-v1",
                "langgraph_checkpoint_id": "cp-tone",
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
    return {item.name: item for item in assert_simulation_response(fixture.conversations[0].turns[0], response, fixture.snapshot)}


@pytest.mark.parametrize(
    ("assertion_id", "message", "reply"),
    [
        ("style.sentence_count_1_to_2", "多少钱？", "第一句。第二句。第三句。"),
        ("style.direct_answer_first", "多少钱？", "根据您提供的信息，我将为您查询。当前价格39.90元。"),
        ("style.no_unnecessary_repetition", "多少钱？", "您问的是这款商品多少钱。这款当前39.90元。"),
        ("style.natural_customer_service_chinese", "多少钱？", "系统显示如下：price=39.90。"),
        ("style.no_excessive_cuteness", "多少钱？", "亲亲，39.90元哒！！！"),
        ("style.calm_under_pressure", "到底多少钱？", "你不是已经问过了吗？39.90元。"),
        ("style.boundary_with_next_step", "今天能到吗？", "这个无法确认。"),
        ("style.concise_entity_reference", "还有货吗？", "超长完整商品标题宠物用品清洁护理喷雾当前库存为4件。"),
        ("style.concise_entity_reference", "还有货吗？", "这款宠物用品清洁护理喷雾…当前库存为4件。"),
    ],
)
def test_tone_style_assertions_are_explainable(
    assertion_id: str, message: str, reply: str
) -> None:
    assertions = _tone_assertions(message, reply, [assertion_id])

    assert assertion_id in assertions
    result = assertions[assertion_id]
    assert result.passed is False
    assert result.evidence


def test_boundary_next_step_accepts_contacting_named_carrier() -> None:
    assertions = _tone_assertions(
        "把完整运单号发我。",
        "为保障信息安全，目前只能提供脱敏运单号：**********0156。如需追踪物流，可联系中通快递。",
        ["style.boundary_with_next_step"],
    )

    assert assertions["style.boundary_with_next_step"].passed


def test_boundary_next_step_accepts_checking_latest_logistics() -> None:
    assertions = _tone_assertions(
        "今天能到吗？",
        "已发货待收货，目前无法确认今天能否送达，您可以查看最新物流或联系中通快递核实。",
        ["style.boundary_with_next_step"],
    )

    assert assertions["style.boundary_with_next_step"].passed


def test_boundary_next_step_accepts_r17_realtime_carrier_logistics_query() -> None:
    assertions = _tone_assertions(
        "把完整运单号发我。",
        "理解您急用，但为保障信息安全，只能提供脱敏运单号：**********0156。您可用该号码在中通快递官网查询实时物流。",
        ["style.boundary_with_next_step"],
    )

    assert assertions["style.boundary_with_next_step"].passed


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("目前无法确认送达时间，您可以查看物流。", True),
        ("目前无法确认送达时间，您可以查看当前物流。", True),
        ("目前只能提供脱敏运单号，您可在官网查物流。", True),
        ("目前只能提供脱敏运单号，请不要查询物流。", False),
        ("目前只能提供脱敏运单号，不可以查看物流。", False),
        ("目前只能提供脱敏运单号，官网查询物流是承运商提供的功能。", False),
    ],
)
def test_boundary_next_step_logistics_query_requires_actionable_non_negated_pattern(
    reply: str, expected: bool
) -> None:
    assertions = _tone_assertions(
        "今天能到吗？", reply, ["style.boundary_with_next_step"]
    )

    assert assertions["style.boundary_with_next_step"].passed is expected


def test_boundary_next_step_accepts_querying_logistics_on_official_site() -> None:
    assertions = _tone_assertions(
        "把完整运单号发我。",
        "为保护信息安全，目前只能提供脱敏运单号：**********0156。您可以用它在官网查询物流详情。",
        ["style.boundary_with_next_step"],
    )

    assert assertions["style.boundary_with_next_step"].passed


def test_tracking_privacy_boundary_without_actionable_next_step_still_fails() -> None:
    assertions = _tone_assertions(
        "把完整运单号发我。",
        "脱敏运单号：**********0156。为保护信息安全，完整运单号无法直接发送。",
        ["style.boundary_with_next_step"],
    )

    result = assertions["style.boundary_with_next_step"]
    assert result.evidence["has_boundary"] is True
    assert result.evidence["has_next_step"] is False
    assert result.passed is False


def test_concise_entity_reference_counts_prefix_before_capacity_fact() -> None:
    assertions = _tone_assertions(
        "这玩意儿多大一瓶？",
        "这款容量是145ml，也就是145毫升。",
        ["style.concise_entity_reference"],
    )

    result = assertions["style.concise_entity_reference"]
    assert result.passed
    assert result.evidence["entity_prefix_length"] == 2


def test_concise_entity_reference_detects_is_followed_by_numeric_specification() -> None:
    assertions = _tone_assertions(
        "这玩意儿多大一瓶？",
        "这瓶宠物喷雾是145ml，也就是145毫升。",
        ["style.concise_entity_reference"],
    )

    result = assertions["style.concise_entity_reference"]
    assert result.passed
    assert result.evidence["entity_prefix_length"] == 6


def test_boundary_next_step_accepts_checking_logistics_on_carrier_site() -> None:
    assertions = _tone_assertions(
        "把完整运单号发我。",
        "为保障信息安全，只能提供脱敏运单号：**********0156。您可凭此号在中通快递官网查物流。",
        ["style.boundary_with_next_step"],
    )

    assert assertions["style.boundary_with_next_step"].passed


@pytest.mark.parametrize(
    "reply",
    [
        "从商品名称来看，这款是适合比熊使用的，如果宠物有特殊皮肤情况，建议先咨询专业人士。",
        "根据现有信息，可以给小猫使用，建议先咨询专业人士。",
    ],
)
def test_product_audience_style_rejects_source_explanation_and_unrelated_disclaimer(reply: str) -> None:
    assertions = _tone_assertions(
        "这款适合比熊吗？", reply, ["style.direct_product_audience_answer"]
    )

    assert assertions["style.direct_product_audience_answer"].passed is False


@pytest.mark.parametrize(
    "reply",
    [
        "作为一个 AI，我只能提供39.90元这个信息。",
        "系统显示如下：当前价格39.90元。",
        "请您耐心等待，当前价格39.90元。",
        "亲亲，很高兴为您服务，当前价格39.90元。",
        "具体以实际为准，当前价格39.90元。",
    ],
)
def test_tone_style_assertions_record_banned_template_rule_and_short_snippet(reply: str) -> None:
    result = _tone_assertions("多少钱？", reply, ["style.natural_customer_service_chinese"])[
        "style.banned_template"
    ]

    assert result.passed is False
    assert result.evidence["rule_id"].startswith("template.")
    assert 0 < len(result.evidence["snippet"]) <= 24


def test_tone_report_contains_safe_style_and_review_distributions(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["conversations"] = payload["conversations"][:1]
    payload["generation"]["generated_at"] = "2026-07-20T09:00:00+08:00"
    payload["conversations"][0]["turns"][0].update(
        {
            "turn_id": "tone-01",
            "coverage": ["short_follow_up"],
            "style_assertions": ["style.sentence_count_1_to_2"],
            "human_review": {"approved": True, "approved_at": "2026-07-20T10:00:00+08:00"},
        }
    )
    fixture = SimulationFixture.model_validate(payload, context={"allow_partial": True})

    result = SimulationRunner(RecordingClient(), reports_dir=tmp_path).run(fixture, run_id="tone-report")

    assert result.summary["external_send"] == 0
    assert result.summary["style_assertions"]["style.sentence_count_1_to_2"]["passed"] == 1
    assert result.summary["sentence_count"]
    assert result.summary["banned_templates"] == {}
    safe_rows = json.loads((tmp_path / "tone-report-conversations.json").read_text(encoding="utf-8"))
    assert safe_rows[0]["source"] == "simulation"
    assert safe_rows[0]["human_review"]["approved"] is True
    assert safe_rows[0]["primary_failure_category"] is None


def test_runner_consumes_remaining_typed_context_requests(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["conversations"] = payload["conversations"][:1]
    fixture = SimulationFixture.model_validate(payload, context={"allow_partial": True})

    class SequentialContextClient(RecordingClient):
        def create_decision(self, case):
            response = super().create_decision(case)
            response.context_requests = [
                __import__("evals.models", fromlist=["ContextRequest"]).ContextRequest(
                    context_request_id="ctx-orders", type="orders"
                )
            ]
            return response

        def refill_context(self, case, response, context_request):
            self.requests.append({"refill": context_request.type})
            if context_request.type == "orders":
                return AgentResponse.from_payload(
                    {
                        "decision_id": response.decision_id, "decision_status": "partial_context",
                        "remaining_context_requests": [{"context_request_id": "ctx-logistics", "type": "logistics"}],
                        "trace": response.trace,
                    }
                )
            final = super().create_decision(case)
            final.context_requests = []
            return final

    client = SequentialContextClient()
    result = SimulationRunner(client, reports_dir=tmp_path).run(fixture, run_id="sequential-context")

    assert result.rows[0]["context_refill_calls"] == ["orders", "logistics"]
