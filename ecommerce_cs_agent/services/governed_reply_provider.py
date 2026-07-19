from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ecommerce_cs_agent.services.llm_provider import LlmProviderError, OpenAICompatibleProviderClient
from ecommerce_cs_agent.services.llm_runtime import RuntimeRouteRepository
from ecommerce_cs_agent.services.reply_generation import (
    GroundedFactManifest,
    GroundedRewriteRequest,
    UnsafeModelReply,
    build_rewrite_messages,
    validate_model_reply,
)


@dataclass(frozen=True, slots=True)
class ReplyRewriteOutcome:
    reply_text: str
    model_metadata: dict[str, Any]


class InvocationMetricRecorder(Protocol):
    def record_invocation(
        self, *, scenario_route_id: str, route_role: str, organization_id: str,
        store_id: str, input_tokens: int, output_tokens: int, latency_ms: int,
        status: str, error_code: str | None,
    ) -> None: ...


class NullInvocationMetricRecorder:
    def record_invocation(
        self, *, scenario_route_id: str, route_role: str, organization_id: str,
        store_id: str, input_tokens: int, output_tokens: int, latency_ms: int,
        status: str, error_code: str | None,
    ) -> None:
        return None


class GovernedReplyProvider:
    model_version = "governed-reply-generation"

    def __init__(
        self,
        *,
        route_repository: RuntimeRouteRepository,
        provider_client: OpenAICompatibleProviderClient,
        metric_recorder: InvocationMetricRecorder | None = None,
    ) -> None:
        self._routes = route_repository
        self._client = provider_client
        self._metrics = metric_recorder or NullInvocationMetricRecorder()

    def rewrite_grounded(
        self, *, organization_id: str, store_id: str, question: str,
        history: list[dict[str, Any]], deterministic: str, facts: GroundedFactManifest,
    ) -> ReplyRewriteOutcome:
        route = self._routes.resolve_reply_route(
            organization_id=organization_id, store_id=store_id
        )
        if route is None:
            return self._fallback(deterministic, status="route_unavailable")
        try:
            messages = build_rewrite_messages(
                GroundedRewriteRequest(
                    question=question,
                    history=tuple(
                        str(item.get("content") or "")
                        for item in history[-2:]
                        if isinstance(item, dict)
                    ),
                    deterministic_draft=deterministic,
                    facts=facts,
                )
            )
        except ValueError:
            return self._fallback(deterministic, status="input_rejected", validation="rejected")

        last_error = "provider_unavailable"
        last_validation = "not_attempted"
        attempted_fallback = False
        for role, provider in (("primary", route.primary), ("fallback", route.fallback)):
            if provider is None:
                continue
            attempted_fallback = role == "fallback"
            try:
                result = self._client.generate(provider, messages=messages, policy=route.policy)
                reply = validate_model_reply(
                    deterministic=deterministic,
                    model_reply=result.reply_payload["reply_text"],
                    facts=facts,
                )
            except UnsafeModelReply:
                last_error, last_validation = "unsafe_model_reply", "rejected"
                self._record(
                    route=route, role=role, organization_id=organization_id,
                    store_id=store_id, status="rejected", error_code=last_error,
                    input_tokens=0, output_tokens=0, latency_ms=0,
                )
                continue
            except LlmProviderError as exc:
                last_error = exc.code
                self._record(
                    route=route, role=role, organization_id=organization_id,
                    store_id=store_id,
                    status="timed_out" if exc.code == "timeout" else "failed",
                    error_code=exc.code, input_tokens=0, output_tokens=0, latency_ms=0,
                )
                continue
            self._record(
                route=route, role=role, organization_id=organization_id,
                store_id=store_id, status="succeeded", error_code=None,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
            )
            return ReplyRewriteOutcome(
                reply,
                {"model_version": provider.model, "route_role": role, "status": "succeeded",
                 "fallback_used": role == "fallback", "validation_status": "passed"},
            )
        return self._fallback(
            deterministic,
            status="failed",
            validation=last_validation,
            fallback_used=attempted_fallback,
            error_code=last_error,
        )

    def _record(self, *, route: Any, role: str, **metadata: Any) -> None:
        self._metrics.record_invocation(
            scenario_route_id=route.route_id,
            route_role=role,
            **metadata,
        )

    @staticmethod
    def _fallback(
        deterministic: str, *, status: str, validation: str = "not_attempted",
        fallback_used: bool = False, error_code: str | None = None,
    ) -> ReplyRewriteOutcome:
        metadata: dict[str, Any] = {
            "model_version": "deterministic-reply-v1", "route_role": None,
            "status": status, "fallback_used": fallback_used,
            "validation_status": validation,
        }
        if error_code:
            metadata["error_code"] = error_code
        return ReplyRewriteOutcome(deterministic, metadata)
