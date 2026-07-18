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
    summary = json.loads((tmp_path / "sim-1-summary.json").read_text())
    assert summary["snapshot_sha256"] == fixture.generation.snapshot_sha256
    assert summary["all_messages_passed"] is True


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

    assert fixture.generation.snapshot_sha256 == "7e9b0144a81624a93521d0b5"
    assert len(fixture.snapshot["products"]) == 17
    assert len(fixture.snapshot["orders"]) == 8
    assert len(fixture.snapshot["logistics"]) == 5
    assert sum(len(item.turns) for item in fixture.conversations) == 30
