from __future__ import annotations

import json
from typing import Any, Protocol
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.outbound_http import validate_public_https_url
from ecommerce_cs_agent.services.service_stage import ServiceStageClassification, classify_service_stage


class ReplyProvider(Protocol):
    model_version: str

    def classify_service_stage(
        self, *, message: str, conversation: dict[str, Any], context: dict[str, Any]
    ) -> ServiceStageClassification:
        raise NotImplementedError

    def generate_candidate(
        self,
        *,
        message: str,
        knowledge: list[dict[str, Any]],
        service_stage: ServiceStageClassification,
        context: dict[str, Any],
    ) -> str:
        raise NotImplementedError


class DeterministicReplyProvider:
    model_version = "deterministic-reply-v1"

    def classify_service_stage(
        self, *, message: str, conversation: dict[str, Any], context: dict[str, Any]
    ) -> ServiceStageClassification:
        return classify_service_stage(message=message, conversation=conversation, context=context)

    def generate_candidate(
        self,
        *,
        message: str,
        knowledge: list[dict[str, Any]],
        service_stage: ServiceStageClassification,
        context: dict[str, Any],
    ) -> str:
        if service_stage["primary_stage"] == "unknown":
            return "请问您想咨询商品购买、订单物流，还是签收后的使用或售后问题？"
        if knowledge:
            content = str(knowledge[0].get("content", "")).strip()
            if content:
                return f"{content} 请以商品详情页和客服最终确认为准。"
        return "我先帮您核对信息，请以订单和商品详情页的最新状态为准。"


class OpenAICompatibleReplyProvider:
    model_version = "openai-compatible-reply-v1"

    def __init__(self, *, base_url: str, api_key: str, model: str, fallback: ReplyProvider | None = None) -> None:
        self.base_url = validate_public_https_url(base_url, field="LLM base URL")
        self.api_key = api_key
        self.model = model
        self.fallback = fallback or DeterministicReplyProvider()

    def classify_service_stage(
        self, *, message: str, conversation: dict[str, Any], context: dict[str, Any]
    ) -> ServiceStageClassification:
        baseline = classify_service_stage(message=message, conversation=conversation, context=context)
        prompt = {
            "message": message,
            "conversation_messages": conversation.get("messages", []),
            "context": context,
            "deterministic_baseline": baseline,
            "policy": {
                "pre_sale": "purchase, comparison, recommendation, or repurchase intent",
                "in_sale": "ordered but not delivered",
                "after_sale": "delivered use, quality, return, repair, or warranty",
                "unknown": "facts are insufficient",
                "repurchase": "always pre_sale even for an existing customer",
            },
        }
        parsed = self._chat_json(
            system=(
                "Classify one ecommerce customer message. Return JSON only with primary_stage, secondary_stages, "
                "confidence, reason_code, evidence_refs, needs_context. Never invent order, logistics, product, or policy facts."
            ),
            user=json.dumps(prompt, ensure_ascii=False, default=str),
        )
        normalized = _normalize_classification(parsed)
        if normalized is None:
            return {**baseline, "_classifier_source": "fallback", "_classifier_error": "invalid_or_unavailable_output"}  # type: ignore[return-value]
        if baseline["primary_stage"] != "unknown":
            normalized["primary_stage"] = baseline["primary_stage"]
            normalized["secondary_stages"] = list(
                dict.fromkeys(
                    stage
                    for stage in [*baseline["secondary_stages"], *normalized["secondary_stages"]]
                    if stage not in {baseline["primary_stage"], "unknown"}
                )
            )
            normalized["reason_code"] = "mixed_intent" if normalized["secondary_stages"] else baseline["reason_code"]
        normalized["needs_context"] = list(dict.fromkeys([*baseline["needs_context"], *normalized["needs_context"]]))
        normalized["evidence_refs"] = list(dict.fromkeys([*baseline["evidence_refs"], *normalized["evidence_refs"]]))
        return {**normalized, "_classifier_source": "llm_hybrid", "_classifier_error": None}  # type: ignore[return-value]

    def generate_candidate(
        self,
        *,
        message: str,
        knowledge: list[dict[str, Any]],
        service_stage: ServiceStageClassification,
        context: dict[str, Any],
    ) -> str:
        stage_rules = {
            "pre_sale": "Do not invent order status. Answer only from product evidence.",
            "in_sale": "Do not guess shipping or arrival time. Use verified order and logistics facts only.",
            "after_sale": "Do not invent return, refund, repair, or warranty policy.",
            "unknown": "Ask a neutral clarification question and make no business commitment.",
        }
        parsed = self._chat_json(
            system=(
                "Generate a concise Chinese customer-service candidate reply. It is a candidate only, not permission to send. "
                "Return a JSON object with exactly one string field named reply_text. "
                + stage_rules[service_stage["primary_stage"]]
            ),
            user=json.dumps(
                {"message": message, "service_stage": service_stage, "knowledge": knowledge, "context": context},
                ensure_ascii=False,
                default=str,
            ),
        )
        reply_text = str(parsed.get("reply_text") or "").strip() if isinstance(parsed, dict) else ""
        if reply_text:
            return reply_text
        return self.fallback.generate_candidate(
            message=message,
            knowledge=knowledge,
            service_stage=service_stage,
            context=context,
        )

    def _chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        request = urllib_request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = str(data["choices"][0]["message"]["content"])
            parsed = json.loads(_strip_json_fence(content))
            return parsed if isinstance(parsed, dict) else {}
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError):
            return {}


def reply_provider_for(settings: Settings) -> ReplyProvider:
    if (
        settings.environment.lower() != "test"
        and settings.llm_base_url
        and settings.llm_api_key
        and settings.llm_model
    ):
        return OpenAICompatibleReplyProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    return DeterministicReplyProvider()


def _normalize_classification(value: dict[str, Any]) -> ServiceStageClassification | None:
    stages = {"pre_sale", "in_sale", "after_sale", "unknown"}
    reasons = {
        "purchase_intent", "repurchase_intent", "awaiting_fulfillment", "in_transit_unreceived",
        "delivered_usage", "delivered_quality", "return_refund", "repair_warranty", "mixed_intent",
        "insufficient_context",
    }
    primary = str(value.get("primary_stage") or "")
    reason = str(value.get("reason_code") or "")
    secondary = value.get("secondary_stages")
    needs = value.get("needs_context")
    evidence = value.get("evidence_refs")
    if primary not in stages or reason not in reasons or not isinstance(secondary, list):
        return None
    if any(str(stage) not in stages or str(stage) in {primary, "unknown"} for stage in secondary):
        return None
    allowed_context = {"products", "orders", "logistics", "rules"}
    if not isinstance(needs, list) or any(str(item) not in allowed_context for item in needs):
        return None
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        return None
    return {
        "primary_stage": primary,  # type: ignore[typeddict-item]
        "secondary_stages": list(dict.fromkeys(str(stage) for stage in secondary)),  # type: ignore[typeddict-item]
        "confidence": float(confidence),
        "reason_code": reason,  # type: ignore[typeddict-item]
        "evidence_refs": list(dict.fromkeys(str(item) for item in evidence)) if isinstance(evidence, list) else [],
        "needs_context": list(dict.fromkeys(str(item) for item in needs)),
    }


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()
