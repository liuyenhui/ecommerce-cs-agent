from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.decision import DecisionService
from ecommerce_cs_agent.services.decision_graph import _context_grounded_reply, _missing_context
from ecommerce_cs_agent.services.llm import DeterministicReplyProvider, NodeBoundReplyProvider
from ecommerce_cs_agent.services.repository import InMemoryDecisionRepository, PostgresDecisionRepository
from ecommerce_cs_agent.services.service_stage import classify_service_stage


SIMULATION_REGRESSION_CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "service_stage_simulation_regression.json").read_text(
        encoding="utf-8"
    )
)
SIMULATION_CONTEXT_EXPECTATIONS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "service_stage_simulation_context_expectations.json").read_text(
        encoding="utf-8"
    )
)


class _CapturingReplyProvider:
    model_version = "capturing-reply-v1"

    def __init__(self) -> None:
        self.generated_with: dict[str, Any] | None = None

    def classify_service_stage(self, *, message: str, conversation: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return classify_service_stage(message=message, conversation=conversation, context=context)

    def generate_candidate(
        self,
        *,
        message: str,
        knowledge: list[dict[str, Any]],
        service_stage: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        self.generated_with = {
            "message": message,
            "knowledge": knowledge,
            "service_stage": service_stage,
            "context": context,
        }
        return "阶段感知回复"


def test_decision_graph_classifies_stage_and_passes_it_to_reply_provider() -> None:
    provider = _CapturingReplyProvider()
    service = DecisionService(Settings(environment="test"), reply_provider=provider)
    request = _request("req-stage-provider", "已经收到了，怎么安装")
    request["context"] = {
        "orders": [{"external_order_id": "order-stage", "status": "delivered"}],
        "products": [{"external_product_id": "product-001"}],
    }

    response = service.create_reply_decision(request)

    assert response["service_stage"]["primary_stage"] == "after_sale"
    assert provider.generated_with is not None
    assert provider.generated_with["service_stage"] == response["service_stage"]
    assert provider.generated_with["context"] == request["context"]
    graph = response["trace"]["graph"]
    assert next(node for node in graph["nodes"] if node["id"] == "classify_service_stage")["status"] == "completed"
    assert response["trace"]["service_stage"] == response["service_stage"]
    assert response["trace"]["service_stage_classifier"] == {
        "source": "rules",
        "rule_version": "service-stage-rules-v1",
        "model_version": "capturing-reply-v1",
        "prompt_version": "service-stage-prompt-v1",
        "error_code": None,
    }


@pytest.mark.parametrize("case", SIMULATION_REGRESSION_CASES, ids=lambda case: case["id"])
def test_decision_graph_simulation_regression(case: dict[str, Any]) -> None:
    service = DecisionService(Settings(environment="test"))
    request = _request(f"req-{case['id']}", case["message"])
    request["source"] = "simulation"

    response = service.create_reply_decision(request)

    assert response["service_stage"]["primary_stage"] == case["expected_primary_stage"]
    assert response["service_stage"]["secondary_stages"] == case["expected_secondary_stages"]
    assert response["service_stage"]["reason_code"] == case["expected_reason_code"]
    assert response["action"] == case["expected_action"]
    assert response["missing_context"] == SIMULATION_CONTEXT_EXPECTATIONS[case["id"]]
    assert response["auto_reply"] is None
    expected_gate_reason = "simulation_only" if response["action"] == "candidate" else "non_candidate_route"
    assert expected_gate_reason in response["trace"]["auto_reply_gate"]["reasons"]


def test_simulation_context_expectations_cover_every_regression_case() -> None:
    assert set(SIMULATION_CONTEXT_EXPECTATIONS) == {case["id"] for case in SIMULATION_REGRESSION_CASES}


def test_product_attribute_stage_requests_products_before_candidate_generation() -> None:
    service = DecisionService(Settings(environment="test"))

    response = service.create_reply_decision(_request("req-stage-weight", "这个重量是多少"))

    assert response["service_stage"]["primary_stage"] == "pre_sale"
    assert response["missing_context"] == ["products"]
    assert [request["type"] for request in response["context_requests"]] == ["products"]
    assert response["action"] == "context_request"
    assert response["candidates"] == []


def test_context_detection_covers_price_inventory_order_and_conversation_reference() -> None:
    empty = {"context": {}, "conversation": {"messages": []}}
    shipping_history = {"context": {}, "conversation": {"messages": [{"content": "我的订单什么时候到？"}]}}

    assert _missing_context(empty, "活动价呢", "活动价呢") == ["products"]
    assert _missing_context(empty, "是多少毫升", "是多少毫升") == ["products"]
    assert _missing_context(empty, "这个订单买了什么", "这个订单买了什么") == ["orders"]
    assert _missing_context(shipping_history, "查到了吗", "查到了吗") == ["orders", "logistics"]
    assert _missing_context(shipping_history, "帮我改备注", "帮我改备注") == []


def test_context_grounded_reply_uses_safe_typed_fields_and_omits_raw_source_refs() -> None:
    reply = _context_grounded_reply(
        {
            "products": [{"external_product_id": "p-1", "title": "宠物香波", "price": 75, "attributes": {"stock_total": 4}}],
            "orders": [{"external_order_id": "pdd-order-abc", "items": [{"external_product_id": "p-1"}], "raw_payload": {"status_text": "已收货", "source_ref": "private-source"}}],
            "logistics": [{"external_order_id": "pdd-order-abc", "status": "已收货", "carrier": "中通快递", "tracking_no": "******0156"}],
        }
    )

    assert all(term in reply for term in ("宠物香波", "75", "4", "已收货", "中通快递"))
    assert "private-source" not in reply


def test_decision_graph_uses_approved_knowledge_for_safe_auto_reply() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-001",
                "product_id": "product-001",
                "scope": "product",
                "content": "这款商品材质为棉，建议冷水洗涤。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req-knowledge", "这个商品是什么材质？"))

    assert response["action"] == "auto_reply"
    assert response["decision_status"] == "answer_ready"
    assert response["auto_reply"]["reply_text"] == response["candidates"][0]["reply_text"]
    assert response["auto_reply"]["approved_by_policy_gate"] is True
    assert response["confidence"] >= 0.85
    assert response["trace"]["langgraph_checkpoint_id"]
    assert response["missing_context"] == []
    assert response["candidates"][0]["evidence"][0]["knowledge_entry_id"] == "knowledge-001"
    assert "材质为棉" in response["candidates"][0]["reply_text"]
    assert response["trace"]["matched_knowledge_ids"] == ["knowledge-001"]
    assert "knowledge:knowledge-001" in response["trace"]["steps"][1]["outputs_ref"]
    graph = response["trace"]["graph"]
    assert next(node for node in graph["nodes"] if node["id"] == "generate_candidate")["status"] == "completed"
    assert any(edge["condition"] == "candidate" and edge["taken"] for edge in graph["edges"])
    assert any(edge["condition"] == "persist" and edge["taken"] for edge in graph["edges"])


def test_decision_graph_does_not_auto_reply_from_unrelated_approved_knowledge() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-unrelated",
                "product_id": "product-001",
                "scope": "product",
                "content": "包装盒是蓝色的。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req-unrelated-knowledge", "儿童安全认证？"))

    assert response["action"] == "candidate"
    assert response["decision_status"] == "candidate"
    assert response["auto_reply"] is None
    assert response["confidence"] < 0.85
    assert response["candidates"][0]["evidence"] == []
    assert response["trace"]["matched_knowledge_ids"] == []
    assert response["trace"]["knowledge_relevance"] == [
        {
            "knowledge_entry_id": "knowledge-unrelated",
            "relevant": False,
            "text_relevant": False,
            "binding_eligible": True,
            "binding_reason": "product_match",
            "matched_terms": [],
            "matched_core_terms": [],
            "matched_phrases": [],
            "query_core_terms": ["安全", "认证"],
            "score": 0.0,
            "threshold": 0.7,
            "method": "deterministic_intent_overlap_v2",
        }
    ]


def test_decision_graph_rejects_single_broad_chinese_safety_term() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-shipping-safety",
                "product_id": "product-001",
                "scope": "product",
                "content": "物流包装符合运输安全要求。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req-broad-safety-zh", "这个商品通过儿童安全认证了吗？"))

    assert response["action"] != "auto_reply"
    assert response["auto_reply"] is None
    assert response["trace"]["matched_knowledge_ids"] == []
    assert response["trace"]["knowledge_relevance"][0]["matched_terms"] == ["安全"]
    assert response["trace"]["knowledge_relevance"][0]["relevant"] is False


def test_decision_graph_auto_replies_for_matching_chinese_certification_phrase() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-child-certification",
                "product_id": "product-001",
                "scope": "product",
                "content": "本商品已通过儿童安全认证，认证编号可在说明书核验。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req-child-certification-zh", "这个商品通过儿童安全认证了吗？"))

    assert response["action"] == "auto_reply"
    assert response["trace"]["knowledge_relevance"][0]["relevant"] is True
    assert "安全认证" in response["trace"]["knowledge_relevance"][0]["matched_phrases"]


def test_decision_graph_rejects_single_broad_english_safety_term() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-shipping-safe-en",
                "product_id": "product-001",
                "scope": "product",
                "content": "Shipping packaging is safe for transport.",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(
        _request("req-broad-safety-en", "Is this product certified safe for children?")
    )

    assert response["action"] != "auto_reply"
    assert response["auto_reply"] is None
    assert response["trace"]["matched_knowledge_ids"] == []
    assert response["trace"]["knowledge_relevance"][0]["relevant"] is False


def test_decision_graph_auto_replies_for_matching_english_certification_intent() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-child-safe-en",
                "product_id": "product-001",
                "scope": "product",
                "content": "This product is certified safe for children.",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(
        _request("req-child-safety-en", "Is this product certified safe for children?")
    )

    assert response["action"] == "auto_reply"
    assert response["trace"]["knowledge_relevance"][0]["relevant"] is True
    assert response["trace"]["knowledge_relevance"][0]["score"] >= 0.7


def test_decision_graph_rejects_knowledge_bound_to_another_product() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-product-b",
                "product_id": "product-b",
                "external_product_id": "product-b",
                "scope": "product",
                "content": "本商品已通过儿童安全认证。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)
    request = _request("req-product-binding-mismatch", "这个商品通过儿童安全认证了吗？")
    request["external_product_id"] = "product-a"
    request["listing_ref"] = "listing-a"

    response = service.create_reply_decision(request)

    assert response["action"] != "auto_reply"
    assert response["auto_reply"] is None
    assert response["trace"]["matched_knowledge_ids"] == []
    signal = response["trace"]["knowledge_relevance"][0]
    assert signal["text_relevant"] is True
    assert signal["binding_eligible"] is False
    assert signal["binding_reason"] == "product_mismatch"


def test_decision_graph_auto_replies_for_knowledge_bound_to_requested_product() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-product-a",
                "product_id": "product-a",
                "external_product_id": "product-a",
                "scope": "product",
                "content": "本商品已通过儿童安全认证。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)
    request = _request("req-product-binding-match", "这个商品通过儿童安全认证了吗？")
    request["external_product_id"] = "product-a"
    request["listing_ref"] = "listing-a"

    response = service.create_reply_decision(request)

    assert response["action"] == "auto_reply"
    assert response["trace"]["matched_knowledge_ids"] == ["knowledge-product-a"]
    assert response["trace"]["knowledge_relevance"][0]["binding_reason"] == "product_match"


def test_decision_graph_does_not_auto_reply_product_knowledge_without_product_binding() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-unbound-product",
                "product_id": "product-a",
                "external_product_id": "product-a",
                "scope": "product",
                "content": "本商品已通过儿童安全认证。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)
    request = _request("req-product-binding-missing", "这个商品通过儿童安全认证了吗？")
    request.pop("external_product_id")
    request.pop("listing_ref")

    response = service.create_reply_decision(request)

    assert response["action"] != "auto_reply"
    assert response["auto_reply"] is None
    assert response["trace"]["knowledge_relevance"][0]["binding_reason"] == "missing_request_product_binding"


def test_decision_graph_allows_explicit_store_scope_knowledge_without_product_binding() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-store-policy",
                "product_id": None,
                "external_product_id": None,
                "scope": "store",
                "content": "本店所有儿童商品均要求通过儿童安全认证。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req-store-scope-knowledge", "儿童商品要求安全认证吗？"))

    assert response["action"] == "auto_reply"
    assert response["trace"]["knowledge_relevance"][0]["binding_reason"] == "explicit_store_scope"


def test_decision_graph_labels_explicit_tenant_scope_knowledge_accurately() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-tenant-policy",
                "product_id": None,
                "external_product_id": None,
                "scope": "tenant",
                "content": "本组织所有儿童商品均要求通过儿童安全认证。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req-tenant-scope-knowledge", "儿童商品要求安全认证吗？"))

    assert response["action"] == "auto_reply"
    assert response["trace"]["knowledge_relevance"][0]["binding_reason"] == "explicit_tenant_scope"


def test_decision_graph_keeps_relevant_knowledge_as_candidate_in_assist_first_mode() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-material",
                "product_id": "product-001",
                "scope": "product",
                "content": "Material: cotton.",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)
    request = _request("req-assist-first", "What material is this item?")
    request["mode"] = "assist_first"

    response = service.create_reply_decision(request)

    assert response["action"] == "candidate"
    assert response["auto_reply"] is None
    assert response["confidence"] >= 0.85
    assert response["trace"]["knowledge_relevance"][0]["matched_terms"] == ["material"]


def test_decision_graph_never_marks_simulation_as_auto_reply() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-certification",
                "product_id": "product-001",
                "scope": "product",
                "content": "已通过儿童安全认证。",
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)
    request = _request("req-simulation-safe", "儿童安全认证？")
    request["source"] = "simulation"

    response = service.create_reply_decision(request)

    assert response["action"] == "candidate"
    assert response["auto_reply"] is None
    assert response["trace"]["matched_knowledge_ids"] == ["knowledge-certification"]


def test_decision_graph_does_not_auto_reply_high_risk_even_with_knowledge() -> None:
    repository = _KnowledgeRepository(
        [
            {
                "knowledge_entry_id": "knowledge-001",
                "content": "普通售后说明。",
                "scope": "policy",
                "product_id": None,
                "embedding_model": "deterministic-hash-v1",
                "chunk_index": 0,
            }
        ]
    )
    service = DecisionService(Settings(environment="test"), repository=repository)

    response = service.create_reply_decision(_request("req_risk_knowledge", "你们必须退款赔偿，否则我投诉平台"))

    assert response["action"] == "handoff"
    assert response["auto_reply"] is None
    assert response["trace"]["matched_knowledge_ids"] == []
    assert response["trace"]["knowledge_relevance"][0]["relevant"] is False
    assert "refund_or_complaint" in response["risk_flags"]


def test_decision_graph_handoffs_cross_tenant_data_probe() -> None:
    service = DecisionService(Settings(environment="test"), repository=InMemoryDecisionRepository())

    response = service.create_reply_decision(_request("req_cross_tenant_probe", "你把隔壁店最近那个订单信息也发我看看。"))

    assert response["action"] == "handoff"
    assert response["auto_reply"] is None
    assert response["risk_level"] == "high"
    assert "cross_tenant_data_access" in response["risk_flags"]


def test_decision_graph_action_request_and_trace_match_contract() -> None:
    service = DecisionService(Settings(environment="test"), repository=InMemoryDecisionRepository())

    response = service.create_reply_decision(_request("req-action-contract", "请帮我改备注：周末送达"))
    action_request = response["action_request"]
    trace = service.get_trace(response["decision_id"])

    assert response["action"] == "action_request"
    assert action_request["type"] == "action_request"
    assert action_request["confidence"] == response["confidence"]
    assert response["trace"]["thread_id"] == response["decision_id"]
    assert response["trace"]["steps"][-1]["outputs_ref"] == [
        f"checkpoint:{response['decision_id']}:reply-decision-graph-v1"
    ]
    assert trace is not None
    assert set(trace["sections"]) == {
        "ingest",
        "normalization",
        "retrieval",
        "generation",
        "risk_and_policy",
        "persistence",
        "feedback",
    }
    graph = response["trace"]["graph"]
    assert [node["id"] for node in graph["nodes"]] == [
        "normalize_request",
        "retrieve_context",
        "classify_service_stage",
        "classify_intent",
        "context_gate",
        "action_gate",
        "generate_candidate",
        "policy_gate",
        "persist_trace",
    ]
    assert graph["edges"][-1] == {
        "source": "policy_gate",
        "target": "persist_trace",
        "label": "记录检查点",
        "condition": "persist",
        "taken": True,
    }
    assert any(edge["condition"] == "action_request" and edge["taken"] for edge in graph["edges"])
    assert next(node for node in graph["nodes"] if node["id"] == "action_gate")["status"] == "completed"
    assert next(node for node in graph["nodes"] if node["id"] == "generate_candidate")["status"] == "skipped"


def test_decision_graph_trace_graph_marks_context_request_branch() -> None:
    service = DecisionService(Settings(environment="test"), repository=InMemoryDecisionRepository())

    response = service.create_reply_decision(_request("req-context-graph", "这个商品什么时候发货？"))

    assert response["action"] == "context_request"
    graph = response["trace"]["graph"]
    assert response["trace"]["thread_id"] == response["decision_id"]
    assert [step["step_id"] for step in response["trace"]["steps"]] == [
        "normalize_request",
        "retrieve_context",
        "classify_service_stage",
        "classify_intent",
        "context_gate",
        "policy_gate",
        "persist_trace",
    ]
    assert any(edge["condition"] == "context_request" and edge["taken"] for edge in graph["edges"])
    assert any(edge["condition"] == "candidate" and not edge["taken"] for edge in graph["edges"])
    context_gate = next(node for node in graph["nodes"] if node["id"] == "context_gate")
    assert any(item.startswith("context_request:") for item in context_gate["outputs_ref"])
    action_gate = next(node for node in graph["nodes"] if node["id"] == "action_gate")
    generate_candidate = next(node for node in graph["nodes"] if node["id"] == "generate_candidate")
    assert action_gate["status"] == "skipped"
    assert generate_candidate["status"] == "skipped"


def test_llm_node_failure_enters_safe_handoff_without_switching_provider() -> None:
    class FailedProvider(_CapturingReplyProvider):
        model_version = "failed-bound-model"
        last_invocation = {"node_id": "classify_service_stage", "llm_id": "llm-a", "model_id": "model-a", "status": "failed", "error_code": "llm_call_failed"}

        def classify_service_stage(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("safe_llm_failure")

    service = DecisionService(Settings(environment="test"), repository=InMemoryDecisionRepository(), reply_provider=FailedProvider())

    response = service.create_reply_decision(_request("req-llm-failure", "我想买这款商品"))

    assert response["action"] == "handoff"
    assert "llm_unavailable" in response["risk_flags"]
    step = next(item for item in response["trace"]["steps"] if item["step_id"] == "classify_service_stage")
    assert step["status"] == "failed"
    assert step["error"] == {"code": "llm_call_failed"}
    assert step["llm"] == {"llm_id": "llm-a", "model_id": "model-a", "status": "failed", "error_code": "llm_call_failed"}


@pytest.mark.parametrize(
    ("message", "expected_stage", "expected_action"),
    [
        ("订单还没发货，我想把收货地址改成公司。", "in_sale", "action_request"),
        ("我付款成功了但页面看不到订单，是什么情况？", "in_sale", "context_request"),
        ("怎么处理比较好？", "unknown", "candidate"),
    ],
)
def test_node_bound_classifier_failure_uses_rules_without_bypassing_decision_gates(
    message: str,
    expected_stage: str,
    expected_action: str,
) -> None:
    class FailedClassificationProvider(DeterministicReplyProvider):
        def classify_service_stage(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("safe_llm_failure")

    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "model-a"},
        provider_factory=lambda _config: FailedClassificationProvider(),
    )
    service = DecisionService(
        Settings(environment="test"),
        repository=InMemoryDecisionRepository(),
        reply_provider=provider,
    )

    response = service.create_reply_decision(_request(f"req-fallback-{expected_stage}-{expected_action}", message))

    assert response["service_stage"]["primary_stage"] == expected_stage
    assert response["action"] == expected_action
    assert "llm_unavailable" not in response["risk_flags"]
    assert response["trace"]["service_stage_classifier"]["source"] == "fallback"
    assert response["trace"]["service_stage_classifier"]["error_code"] == "llm_call_failed"
    step = next(item for item in response["trace"]["steps"] if item["step_id"] == "classify_service_stage")
    assert step["status"] == "completed"
    assert step["error"] is None
    assert step["llm"]["status"] == "failed"
    assert step["llm"]["error_code"] == "llm_call_failed"


def test_context_refill_resumes_same_thread_and_completes_graph() -> None:
    repository = InMemoryDecisionRepository()
    service = DecisionService(Settings(environment="test"), repository=repository)
    response = service.create_reply_decision(_request("req-refill-graph", "什么时候发货？"))
    decision_id = response["decision_id"]

    first = service.refill_context(
        decision_id,
        "orders",
        {
            "context_request_id": response["context_requests"][0]["context_request_id"],
            "idempotency_key": "ctx-orders",
            "organization_id": "org-001",
            "store_id": "store-001",
            "captured_at": "2026-07-10T10:00:00Z",
            "orders": [{"external_order_id": "order-001", "status": "paid"}],
        },
    )
    second = service.refill_context(
        decision_id,
        "logistics",
        {
            "context_request_id": response["context_requests"][1]["context_request_id"],
            "idempotency_key": "ctx-logistics",
            "organization_id": "org-001",
            "store_id": "store-001",
            "captured_at": "2026-07-10T10:01:00Z",
            "logistics": [{"external_logistics_id": "ship-001", "status": "in_transit"}],
        },
    )
    second_retry = service.refill_context(
        decision_id,
        "logistics",
        {
            "context_request_id": response["context_requests"][1]["context_request_id"],
            "idempotency_key": "ctx-logistics",
            "organization_id": "org-001",
            "store_id": "store-001",
            "captured_at": "2026-07-10T10:01:00Z",
            "logistics": [{"external_logistics_id": "ship-001", "status": "in_transit"}],
        },
    )

    assert first is not None
    assert first["next_action"] == "wait_context"
    assert second is not None
    assert second_retry == second
    assert second["decision_id"] == decision_id
    assert second["trace"]["thread_id"] == decision_id
    assert second["trace"]["resumed_from_checkpoint"] is True
    assert second["trace"]["langgraph_checkpoint_id"]
    assert second["action"] == "candidate"
    assert second["missing_context"] == []
    assert any(edge["condition"] == "candidate" and edge["taken"] for edge in second["trace"]["graph"]["edges"])


def test_continuations_use_atomic_repository_mutation_and_keep_idempotent_replay() -> None:
    repository = _AtomicMutationOnlyRepository()
    service = DecisionService(Settings(environment="test"), repository=repository)
    response = service.create_reply_decision(_request("req-atomic-refill", "这个商品什么时候发货？"))
    decision_id = response["decision_id"]
    payload = {
        "context_request_id": response["context_requests"][0]["context_request_id"],
        "idempotency_key": "ctx-orders-atomic",
        "organization_id": "org-001",
        "store_id": "store-001",
        "captured_at": "2026-07-10T10:00:00Z",
        "orders": [{"external_order_id": "order-001", "status": "paid"}],
    }

    first = service.refill_context(decision_id, "orders", payload)
    replay = service.refill_context(decision_id, "orders", payload)
    repository._by_decision_id[decision_id].response["action_requests"] = [
        {"action_id": "action-atomic", "action_type": "lookup-logistics"}
    ]
    action = service.submit_action_result(
        decision_id,
        {
            "action_id": "action-atomic",
            "action_type": "lookup-logistics",
            "idempotency_key": "action-atomic-idem",
            "status": "succeeded",
        },
    )
    feedback = service.submit_feedback(
        {
            "decision_id": decision_id,
            "human_reply": "已人工处理",
            "resolution_status": "resolved",
        }
    )

    assert replay == first
    assert action is not None
    assert action["decision_status"] == "answer_ready"
    assert feedback is not None
    assert repository.mutation_calls == [decision_id, decision_id, decision_id, decision_id]


def test_legacy_completed_context_refill_replays_only_on_original_typed_endpoint() -> None:
    repository = InMemoryDecisionRepository()
    service = DecisionService(Settings(environment="test"), repository=repository)
    response = service.create_reply_decision(_request("req-legacy-context", "这个商品是什么材质？"))
    decision_id = response["decision_id"]
    context_request_id = response["context_requests"][0]["context_request_id"]
    payload = {
        "context_request_id": context_request_id,
        "idempotency_key": "ctx-legacy-products",
        "organization_id": "org-001",
        "store_id": "store-001",
        "captured_at": "2026-07-10T10:00:00Z",
        "products": [{"external_product_id": "product-001", "title": "测试商品"}],
    }
    completed = service.refill_context(decision_id, "products", payload)
    state = repository.get_by_decision_id(decision_id)
    assert state is not None
    state.context_refills[(context_request_id, "ctx-legacy-products")].pop("_context_type")

    replay = service.refill_context(decision_id, "products", payload)

    assert replay == completed
    with pytest.raises(ValueError, match="URL context type"):
        service.refill_context(decision_id, "orders", payload)
    with pytest.raises(FileExistsError, match="idempotency conflict"):
        service.refill_context(
            decision_id,
            "products",
            {**payload, "products": [{"external_product_id": "product-other"}]},
        )


def test_decision_graph_uses_run_scoped_native_checkpointers() -> None:
    service = DecisionService(Settings(environment="test"), repository=InMemoryDecisionRepository())

    first = service.create_reply_decision(_request("req-run-checkpoint-1", "这个商品什么时候发货？"))
    second = service.create_reply_decision(_request("req-run-checkpoint-2", "这个商品什么时候发货？"))

    assert not hasattr(service.graph, "_checkpointer")
    assert not hasattr(service.graph, "_compiled_stategraph")
    assert first["trace"]["langgraph_checkpoint_id"]
    assert second["trace"]["langgraph_checkpoint_id"]


def test_postgres_decision_repository_recalls_only_approved_accepted_knowledge() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            [
                (
                    "knowledge-001",
                    "product-001",
                    "product-001",
                    "product",
                    "材质为棉。",
                    "deterministic-hash-v1",
                    0,
                )
            ]
        ]
    )
    repository = PostgresDecisionRepository("postgresql://example")
    repository._connect = lambda _url: connection

    entries = repository.recall_knowledge(
        "org-001",
        "store-001",
        "商品 材质",
        limit=3,
        external_product_id="product-001",
        listing_ref="listing-001",
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert entries[0]["knowledge_entry_id"] == "knowledge-001"
    assert "entry.status = 'approved'" in executed_sql
    assert "candidate.review_status = 'accepted'" in executed_sql
    assert "st.id::text = entry.store_id::text" in executed_sql
    assert "st.organization_id = org.id" in executed_sql
    assert "product.organization_id = entry.organization_id" in executed_sql
    assert "product.store_id::text = entry.store_id::text" in executed_sql
    assert "candidate.organization_id = entry.organization_id" in executed_sql
    assert "candidate.store_id::text = entry.store_id::text" in executed_sql
    assert "embedding.organization_id = entry.organization_id" in executed_sql
    assert "embedding.store_id::text = entry.store_id::text" in executed_sql
    assert "product.external_product_id = %s" in executed_sql
    assert "entry.scope IN ('store', 'tenant')" in executed_sql
    assert connection.executed[0][1] == (
        "org-001",
        "store-001",
        "product-001",
        "product-001",
        "product-001",
        ["商品", "材质"],
        ["商品", "材质"],
        3,
    )


def test_decision_graph_recall_query_uses_keywords_not_full_message() -> None:
    repository = _KnowledgeRepository([])
    service = DecisionService(Settings(environment="test"), repository=repository)

    service.create_reply_decision(_request("req-recall-query", "这个商品是什么材质？"))

    assert repository.queries == ["商品 材质"]
    assert repository.bindings == [("product-001", "listing-001")]


class _AtomicMutationOnlyRepository(InMemoryDecisionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.mutation_calls: list[str] = []

    def get_by_decision_id(self, decision_id: str) -> DecisionState | None:
        raise AssertionError("continuations must use mutate_state")

    def mutate_state(self, decision_id: str, mutation: Any) -> Any:
        self.mutation_calls.append(decision_id)
        return mutation(self._by_decision_id.get(decision_id))


class _KnowledgeRepository(InMemoryDecisionRepository):
    def __init__(self, knowledge: list[dict[str, Any]]) -> None:
        super().__init__()
        self.knowledge = knowledge
        self.queries: list[str] = []
        self.bindings: list[tuple[str | None, str | None]] = []

    def recall_knowledge(
        self,
        organization_id: str,
        store_id: str,
        query: str,
        limit: int = 5,
        *,
        external_product_id: str | None = None,
        listing_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        self.queries.append(query)
        self.bindings.append((external_product_id, listing_ref))
        return self.knowledge[:limit]


class _FakeConnection:
    def __init__(self, fetch_rows: list[list[tuple[Any, ...]]]) -> None:
        self.fetch_rows = fetch_rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.connection.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        if self.connection.fetch_rows:
            return self.connection.fetch_rows.pop(0)
        return []


def _request(request_id: str, content: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "organization_id": "org-001",
        "store_id": "store-001",
        "platform": "pdd",
        "external_product_id": "product-001",
        "listing_ref": "listing-001",
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": content,
            "sent_at": "2026-06-18T00:00:00Z",
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-001",
            "messages": [],
        },
        "mode": "auto_when_safe",
        "context": {},
    }
