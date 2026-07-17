from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecommerce_cs_agent.services.service_stage import classify_service_stage


CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "service_stage_conversations.json").read_text(encoding="utf-8")
)
SIMULATION_REGRESSION_CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "service_stage_simulation_regression.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_service_stage_corpus(case: dict) -> None:
    result = classify_service_stage(
        message=case["message"],
        conversation=case.get("conversation", {}),
        context=case.get("context", {}),
    )

    assert result["primary_stage"] == case["expected_primary_stage"]
    assert result["secondary_stages"] == case.get("expected_secondary_stages", [])
    assert result["reason_code"] == case["expected_reason_code"]
    assert result["needs_context"] == case.get("expected_needs_context", [])
    assert 0 <= result["confidence"] <= 1
    assert isinstance(result["evidence_refs"], list)


def test_service_stage_corpus_has_sixteen_cases_per_group() -> None:
    groups = {group: 0 for group in ("pre", "mid", "after", "unknown")}
    for case in CASES:
        groups[case["id"].split("-", 1)[0]] += 1

    assert groups == {"pre": 16, "mid": 16, "after": 16, "unknown": 16}


@pytest.mark.parametrize("case", SIMULATION_REGRESSION_CASES, ids=lambda case: case["id"])
def test_service_stage_simulation_regression(case: dict) -> None:
    result = classify_service_stage(
        message=case["message"],
        conversation=case.get("conversation", {}),
        context=case.get("context", {}),
    )

    assert result["primary_stage"] == case["expected_primary_stage"]
    assert result["secondary_stages"] == case["expected_secondary_stages"]
    assert result["reason_code"] == case["expected_reason_code"]


def test_simulation_regression_corpus_freezes_30_base_and_nearby_cases() -> None:
    base = [case for case in SIMULATION_REGRESSION_CASES if case["kind"] == "base"]
    nearby = [case for case in SIMULATION_REGRESSION_CASES if case["kind"] == "nearby"]

    assert len(base) == 30
    assert len(nearby) >= 16


def test_repurchase_is_pre_sale_even_with_delivered_order_history() -> None:
    result = classify_service_stage(
        message="上次买的很好用，我想再买一个新型号",
        conversation={},
        context={"orders": [{"external_order_id": "old-1", "status": "delivered"}]},
    )

    assert result["primary_stage"] == "pre_sale"
    assert result["secondary_stages"] == []
    assert result["reason_code"] == "repurchase_intent"


def test_mixed_request_uses_current_requested_action_as_primary() -> None:
    result = classify_service_stage(
        message="上次买的坏了，这次想换个新型号",
        conversation={},
        context={"orders": [{"external_order_id": "old-1", "status": "delivered"}]},
    )

    assert result["primary_stage"] == "pre_sale"
    assert result["secondary_stages"] == ["after_sale"]
    assert result["reason_code"] == "mixed_intent"


def test_mixed_request_collects_context_for_secondary_pre_sale_intent() -> None:
    result = classify_service_stage(
        message="现在这单还在运输中，我还想再买一个蓝色的，有货吗？",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "in_sale"
    assert result["secondary_stages"] == ["pre_sale"]
    assert result["needs_context"] == ["orders", "logistics", "products"]


def test_pre_sale_inventory_dispatch_question_does_not_request_logistics() -> None:
    result = classify_service_stage(
        message="黑色款还有库存吗，今天能安排出库吗？",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "pre_sale"
    assert result["needs_context"] == ["products"]


def test_delivered_return_and_rebuy_keeps_product_context_for_secondary_stage() -> None:
    result = classify_service_stage(
        message="收货后发现太小准备退掉，还想改买大号。",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "after_sale"
    assert result["secondary_stages"] == ["pre_sale"]
    assert result["needs_context"] == ["products", "rules"]
