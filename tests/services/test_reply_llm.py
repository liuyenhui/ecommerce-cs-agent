from __future__ import annotations

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.llm import DeterministicReplyProvider, OpenAICompatibleReplyProvider, reply_provider_for


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
