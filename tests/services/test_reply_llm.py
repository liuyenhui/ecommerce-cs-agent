from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from typing import Any

import pytest

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.llm import (
    DeterministicReplyProvider,
    NodeBoundReplyProvider,
    OpenAICompatibleReplyProvider,
    reply_provider_for,
)
from ecommerce_cs_agent.services.reply_generation import GroundedFactManifest


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


class _GroundedMessageProvider(DeterministicReplyProvider):
    def __init__(self, reply: str = "可以的，从商品名称看，这款适合比熊使用。") -> None:
        self.reply = reply
        self.messages: list[dict[str, str]] = []

    def generate_from_messages(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return self.reply


class _SequencedGroundedMessageProvider(DeterministicReplyProvider):
    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.messages: list[list[dict[str, str]]] = []

    def generate_from_messages(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _grounded_manifest() -> GroundedFactManifest:
    return GroundedFactManifest(
        required_terms=("比熊",),
        allowed_numbers=(),
        allowed_entities=("这款商品",),
        prohibited_claims=("治疗", "保证送达"),
    )


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


def test_openai_compatible_chat_retries_transient_connection_failure_with_bounded_backoff(monkeypatch) -> None:
    provider = OpenAICompatibleReplyProvider(
        base_url="https://llm.example.test/v1", api_key="test-key", model="test-model"
    )
    calls: list[object] = []
    sleeps: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": '{"reply_text":"恢复成功"}'}}]}
            ).encode()

    def urlopen(*_args, **_kwargs):
        calls.append(object())
        if len(calls) == 1:
            raise URLError("temporary connection failure")
        return Response()

    monkeypatch.setattr("ecommerce_cs_agent.services.llm.urllib_request.urlopen", urlopen)
    monkeypatch.setattr("ecommerce_cs_agent.services.llm.time.sleep", sleeps.append)

    result = provider.generate_from_messages(
        [{"role": "system", "content": "safe"}, {"role": "user", "content": "safe"}]
    )

    assert result == "恢复成功"
    assert len(calls) == 2
    assert sleeps == [0.2]
    assert provider.last_chat_attempts == 2


def test_openai_compatible_chat_does_not_retry_non_transient_4xx(monkeypatch) -> None:
    provider = OpenAICompatibleReplyProvider(
        base_url="https://llm.example.test/v1", api_key="test-key", model="test-model"
    )
    calls: list[object] = []
    sleeps: list[float] = []

    def urlopen(*_args, **_kwargs):
        calls.append(object())
        raise HTTPError("https://llm.example.test", 400, "bad request", {}, None)

    monkeypatch.setattr("ecommerce_cs_agent.services.llm.urllib_request.urlopen", urlopen)
    monkeypatch.setattr("ecommerce_cs_agent.services.llm.time.sleep", sleeps.append)

    try:
        provider.generate_from_messages(
            [{"role": "system", "content": "safe"}, {"role": "user", "content": "safe"}]
        )
    except RuntimeError as exc:
        assert str(exc) == "safe_llm_failure"
    else:
        raise AssertionError("non-transient 4xx must fail safely")

    assert len(calls) == 1
    assert sleeps == []
    assert provider.last_chat_attempts == 1


@pytest.mark.parametrize(
    "error",
    [
        URLError("temporary connection failure"),
        TimeoutError("temporary timeout"),
        HTTPError("https://llm.example.test", 429, "rate limited", {}, None),
        HTTPError("https://llm.example.test", 503, "unavailable", {}, None),
    ],
)
def test_openai_compatible_chat_caps_repeated_transient_failures_at_three(monkeypatch, error) -> None:
    provider = OpenAICompatibleReplyProvider(
        base_url="https://llm.example.test/v1", api_key="test-key", model="test-model"
    )
    calls: list[object] = []
    sleeps: list[float] = []

    def urlopen(*_args, **_kwargs):
        calls.append(object())
        raise error

    monkeypatch.setattr("ecommerce_cs_agent.services.llm.urllib_request.urlopen", urlopen)
    monkeypatch.setattr("ecommerce_cs_agent.services.llm.time.sleep", sleeps.append)

    try:
        provider.generate_from_messages(
            [{"role": "system", "content": "safe"}, {"role": "user", "content": "safe"}]
        )
    except RuntimeError as exc:
        assert str(exc) == "safe_llm_failure"
    else:
        raise AssertionError("exhausted transient retries must fail safely")

    assert len(calls) == 3
    assert sleeps == [0.2, 0.4]
    assert provider.last_chat_attempts == 3


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


def test_classifier_does_not_expand_typed_context_beyond_deterministic_rules() -> None:
    provider = _ClassificationOpenAIProvider(
        {
            "primary_stage": "pre_sale",
            "secondary_stages": [],
            "confidence": 0.8,
            "reason_code": "purchase_intent",
            "evidence_refs": [],
            "needs_context": ["products", "logistics"],
        }
    )

    result = provider.classify_service_stage(
        message="黑色款还有库存吗，今天能安排出库吗？",
        conversation={},
        context={},
    )

    assert result["primary_stage"] == "pre_sale"
    assert result["needs_context"] == ["products"]


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


def test_node_bound_grounded_rewrite_uses_generate_candidate_binding_and_safe_messages() -> None:
    resolved: list[str] = []
    bound = _GroundedMessageProvider()
    provider = NodeBoundReplyProvider(
        resolver=lambda node_id: resolved.append(node_id) or {
            "llm_id": "llm-a", "model_id": "deepseek-v4-pro",
        },
        provider_factory=lambda _config: bound,
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1", store_id="store-1",
        question="这款适合比熊吗？", history=[{"content": "还是刚才这款"}],
        deterministic="从商品名称看，这款适合比熊使用。", facts=_grounded_manifest(),
    )

    assert resolved == ["generate_candidate"]
    assert outcome.reply_text == "可以的，从商品名称看，这款适合比熊使用。"
    assert outcome.model_metadata == {
        "model_version": "deepseek-v4-pro", "route_role": "node_binding",
        "status": "succeeded", "fallback_used": False, "validation_status": "passed",
    }
    flattened = json.dumps(bound.messages, ensure_ascii=False)
    assert "只润色" in flattened
    assert "这款适合比熊吗" in flattened
    assert "先直接回答当前问题" in flattened
    assert "1至2句" in flattened
    assert "真实电商客服" in flattened
    assert "不要重复买家问题" in flattened
    assert "不要说明自己是AI" in flattened
    assert "不要空泛安抚" in flattened
    assert "不要卖萌" in flattened
    assert "隐私边界" in flattened
    assert "明确下一步" in flattened
    assert "商品适用对象问题直接回答" in flattened
    assert provider.last_invocation is not None
    assert set(provider.last_invocation) == {
        "node_id", "llm_id", "model_id", "status", "error_code", "latency_ms",
    }


def test_node_bound_grounded_rewrite_rejects_unsafe_model_output() -> None:
    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "deepseek-v4-pro"},
        provider_factory=lambda _config: _GroundedMessageProvider("每天使用3次即可。"),
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1", store_id="store-1", question="这款适合比熊吗？",
        history=[], deterministic="从商品名称看，这款适合比熊使用。",
        facts=_grounded_manifest(),
    )

    assert outcome.reply_text == "从商品名称看，这款适合比熊使用。"
    assert outcome.model_metadata["status"] == "rejected"
    assert outcome.model_metadata["fallback_used"] is True
    assert outcome.model_metadata["validation_status"] == "rejected"
    assert provider.last_invocation is not None
    assert provider.last_invocation["status"] == "rejected"
    assert provider.last_invocation["error_code"] == "unsafe_model_reply"


def test_node_bound_grounded_rewrite_retries_one_rejected_output_with_stricter_messages() -> None:
    bound = _SequencedGroundedMessageProvider(
        ["这款能治疗皮肤病。", "可以的，从商品名称看，这款适合比熊使用。"]
    )
    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "deepseek-v4-pro"},
        provider_factory=lambda _config: bound,
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1", store_id="store-1", question="这款适合比熊吗？",
        history=[], deterministic="从商品名称看，这款适合比熊使用。",
        facts=_grounded_manifest(),
    )

    assert outcome.model_metadata["status"] == "succeeded"
    assert len(bound.messages) == 2
    assert "纠正重试" in bound.messages[1][0]["content"]


def test_node_bound_grounded_rewrite_retries_tracking_reply_without_privacy_boundary() -> None:
    deterministic = (
        "为保护信息安全，目前只能提供脱敏运单号：**********0156。"
        "可使用该号码在承运商官网查询物流。"
    )
    corrected = (
        "为保护信息安全，这里只能提供脱敏运单号：**********0156。"
        "您可以用这个号码在承运商官网查询物流信息。"
    )
    bound = _SequencedGroundedMessageProvider(
        [
            "好的，这是您的脱敏运单号：**********0156。您可以用这个号码在承运商官网查询物流信息。",
            corrected,
        ]
    )
    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "deepseek-v4-pro"},
        provider_factory=lambda _config: bound,
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1",
        store_id="store-1",
        question="把完整运单号发我。",
        history=[],
        deterministic=deterministic,
        facts=GroundedFactManifest(
            required_terms=("0156", "脱敏运单号"),
            allowed_numbers=("0156",),
            allowed_entities=(),
            prohibited_claims=("保证送达",),
        ),
    )

    assert outcome.reply_text == corrected
    assert outcome.model_metadata["status"] == "succeeded"
    assert len(bound.messages) == 2
    assert "隐私边界" in bound.messages[1][0]["content"]


def test_node_bound_grounded_rewrite_uses_exact_draft_model_attempt_after_two_rejections() -> None:
    deterministic = "从商品名称看，这款适合比熊使用。"
    bound = _SequencedGroundedMessageProvider(
        ["这款能治疗皮肤病。", "每天使用3次即可。", deterministic]
    )
    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "deepseek-v4-pro"},
        provider_factory=lambda _config: bound,
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1", store_id="store-1", question="这款适合比熊吗？",
        history=[], deterministic=deterministic, facts=_grounded_manifest(),
    )

    assert outcome.reply_text == deterministic
    assert outcome.model_metadata["status"] == "succeeded"
    assert len(bound.messages) == 3
    assert "逐字复制 deterministic_draft" in bound.messages[2][0]["content"]
    assert "润色" not in bound.messages[2][0]["content"]
    assert json.loads(bound.messages[2][1]["content"]) == {"deterministic_draft": deterministic}


def test_node_bound_grounded_rewrite_retries_transient_model_failure() -> None:
    bound = _SequencedGroundedMessageProvider(
        [RuntimeError("safe_llm_failure"), "可以的，从商品名称看，这款适合比熊使用。"]
    )
    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "deepseek-v4-pro"},
        provider_factory=lambda _config: bound,
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1", store_id="store-1", question="这款适合比熊吗？",
        history=[], deterministic="从商品名称看，这款适合比熊使用。",
        facts=_grounded_manifest(),
    )

    assert outcome.model_metadata["status"] == "succeeded"
    assert len(bound.messages) == 2


def test_node_bound_grounded_rewrite_records_failure_and_falls_back() -> None:
    class FailingGroundedProvider(DeterministicReplyProvider):
        def generate_from_messages(self, _messages: list[dict[str, str]]) -> str:
            raise RuntimeError("safe_llm_failure")

    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "llm-a", "model_id": "deepseek-v4-pro"},
        provider_factory=lambda _config: FailingGroundedProvider(),
    )

    outcome = provider.rewrite_grounded(
        organization_id="org-1", store_id="store-1", question="这款适合比熊吗？",
        history=[], deterministic="从商品名称看，这款适合比熊使用。",
        facts=_grounded_manifest(),
    )

    assert outcome.reply_text == "从商品名称看，这款适合比熊使用。"
    assert outcome.model_metadata["status"] == "failed"
    assert outcome.model_metadata["fallback_used"] is True
    assert outcome.model_metadata["validation_status"] == "not_attempted"
    assert provider.last_invocation is not None
    assert provider.last_invocation["status"] == "failed"
    assert provider.last_invocation["error_code"] == "llm_call_failed"
