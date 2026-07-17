from __future__ import annotations

from typing import Any

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.llm import (
    DeterministicReplyProvider,
    NodeBoundReplyProvider,
    OpenAICompatibleReplyProvider,
    reply_provider_for,
)


class _CapturingOpenAIProvider(OpenAICompatibleReplyProvider):
    def __init__(self) -> None:
        super().__init__(base_url="https://llm.example.test/v1", api_key="test-key", model="test-model")
        self.system_prompt = ""

    def _chat_json(self, *, system: str, user: str) -> dict[str, str]:
        self.system_prompt = system
        return {"reply_text": "测试回复"}


class _ClassificationOpenAIProvider(OpenAICompatibleReplyProvider):
    def __init__(self, classification: dict[str, Any]) -> None:
        super().__init__(base_url="https://llm.example.test/v1", api_key="test-key", model="test-model")
        self.classification = classification

    def _chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        return self.classification


class _FailingClassificationProvider(DeterministicReplyProvider):
    def classify_service_stage(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("safe_llm_failure")


def test_reply_provider_factory_uses_openai_compatible_provider_when_configured() -> None:
    provider = reply_provider_for(
        Settings(
            environment="development",
            llm_base_url="https://llm.example.test/v1",
            llm_api_key="test-key",
            llm_model="test-model",
        )
    )

    assert isinstance(provider, OpenAICompatibleReplyProvider)


def test_reply_provider_factory_keeps_tests_deterministic() -> None:
    provider = reply_provider_for(
        Settings(
            environment="test",
            llm_base_url="https://llm.example.test/v1",
            llm_api_key="test-key",
            llm_model="test-model",
        )
    )

    assert isinstance(provider, DeterministicReplyProvider)


def test_unknown_stage_fallback_asks_a_neutral_clarifying_question() -> None:
    provider = DeterministicReplyProvider()

    reply = provider.generate_candidate(
        message="这个怎么办",
        knowledge=[],
        service_stage={
            "primary_stage": "unknown",
            "secondary_stages": [],
            "confidence": 0.45,
            "reason_code": "insufficient_context",
            "evidence_refs": [],
            "needs_context": [],
        },
        context={},
    )

    assert "购买" in reply
    assert "订单物流" in reply
    assert "售后" in reply


def test_candidate_prompt_declares_json_output_for_compatible_providers() -> None:
    provider = _CapturingOpenAIProvider()

    reply = provider.generate_candidate(
        message="这款重量是多少",
        knowledge=[{"content": "商品净重 2.5 千克。"}],
        service_stage={
            "primary_stage": "pre_sale",
            "secondary_stages": [],
            "confidence": 0.92,
            "reason_code": "purchase_intent",
            "evidence_refs": ["product-1"],
            "needs_context": [],
        },
        context={"products": [{"external_product_id": "product-1"}]},
    )

    assert reply == "测试回复"
    assert "JSON" in provider.system_prompt
    assert "reply_text" in provider.system_prompt


def test_classifier_preserves_deterministic_primary_and_secondary_stages() -> None:
    provider = _ClassificationOpenAIProvider(
        {
            "primary_stage": "pre_sale",
            "secondary_stages": [],
            "confidence": 0.8,
            "reason_code": "repurchase_intent",
            "evidence_refs": [],
            "needs_context": ["products"],
        }
    )

    result = provider.classify_service_stage(
        message="现在这单还在运输中，我还想再买一个蓝色的，有货吗？",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "in_sale"
    assert result["secondary_stages"] == ["pre_sale"]
    assert result["reason_code"] == "mixed_intent"
    assert result["_classifier_source"] == "llm_hybrid"


def test_classifier_invalid_output_falls_back_to_full_deterministic_result() -> None:
    provider = _ClassificationOpenAIProvider({})

    result = provider.classify_service_stage(
        message="收到的尺寸不合适想退掉，同时再买一个大号的。",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "after_sale"
    assert result["secondary_stages"] == ["pre_sale"]
    assert result["reason_code"] == "mixed_intent"
    assert result["_classifier_source"] == "fallback"
    assert result["_classifier_error"] == "invalid_or_unavailable_output"


def test_classifier_rejects_unknown_as_a_secondary_stage() -> None:
    provider = _ClassificationOpenAIProvider(
        {
            "primary_stage": "pre_sale",
            "secondary_stages": ["unknown"],
            "confidence": 0.8,
            "reason_code": "mixed_intent",
            "evidence_refs": [],
            "needs_context": ["products"],
        }
    )

    result = provider.classify_service_stage(
        message="现在有现货吗？",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "pre_sale"
    assert result["secondary_stages"] == []
    assert result["_classifier_source"] == "fallback"


def test_node_bound_classifier_failure_returns_deterministic_result_and_records_failure() -> None:
    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "model-a"},
        provider_factory=lambda _config: _FailingClassificationProvider(),
    )

    result = provider.classify_service_stage(
        message="订单还没发货，我想把收货地址改成公司。",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "in_sale"
    assert result["reason_code"] == "awaiting_fulfillment"
    assert result["_classifier_source"] == "fallback"
    assert result["_classifier_error"] == "llm_call_failed"
    assert provider.last_invocation is not None
    assert {key: value for key, value in provider.last_invocation.items() if key != "latency_ms"} == {
        "node_id": "classify_service_stage",
        "llm_id": "llm-a",
        "model_id": "model-a",
        "status": "failed",
        "error_code": "llm_call_failed",
    }
    assert provider.last_invocation["latency_ms"] >= 0
