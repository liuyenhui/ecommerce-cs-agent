from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import ssl
import time
from typing import Any, Protocol

from ecommerce_cs_agent.services.llm_runtime import RuntimeProvider, RuntimeRoutePolicy


class SecureProviderSession(Protocol):
    def execute_json(
        self,
        *,
        provider: RuntimeProvider,
        path: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> tuple[int, bytes]: ...


class LlmProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProviderGenerationResult:
    reply_payload: dict[str, str]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    safe_metadata: dict[str, Any]


class OpenAICompatibleProviderClient:
    def __init__(self, *, session: SecureProviderSession, monotonic=time.monotonic) -> None:
        self._session = session
        self._monotonic = monotonic

    def generate(
        self,
        provider: RuntimeProvider,
        *,
        messages: list[dict[str, str]],
        policy: RuntimeRoutePolicy,
    ) -> ProviderGenerationResult:
        if provider.provider_type not in {"openai", "openai_compatible"} or not provider.active:
            raise LlmProviderError("invalid_response")
        payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": policy.temperature,
            "max_tokens": policy.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        started = self._monotonic()
        attempts = max(1, policy.max_retries + 1)
        for attempt in range(attempts):
            try:
                status, body = self._session.execute_json(
                    provider=provider,
                    path="/chat/completions",
                    payload=payload,
                    timeout_seconds=policy.timeout_seconds,
                )
            except (TimeoutError, socket.timeout):
                error = LlmProviderError("timeout")
            except ssl.SSLError:
                error = LlmProviderError("provider_unavailable")
            except Exception:
                error = LlmProviderError("provider_unavailable")
            else:
                if 200 <= status < 300:
                    return self._parse_success(provider, body, started)
                error = LlmProviderError(_status_error(status))
            if attempt + 1 >= attempts or error.code not in {
                "rate_limited", "provider_unavailable", "timeout"
            }:
                raise error
        raise LlmProviderError("provider_unavailable")

    def _parse_success(
        self, provider: RuntimeProvider, body: bytes, started: float
    ) -> ProviderGenerationResult:
        if len(body) > 1024 * 1024:
            raise LlmProviderError("invalid_response")
        try:
            response = json.loads(body)
            content = response["choices"][0]["message"]["content"]
            reply_payload = json.loads(content)
            usage = response.get("usage") or {}
            if (
                not isinstance(reply_payload, dict)
                or set(reply_payload) != {"reply_text"}
                or not isinstance(reply_payload["reply_text"], str)
                or not reply_payload["reply_text"].strip()
            ):
                raise ValueError
            input_tokens = max(0, int(usage.get("prompt_tokens") or 0))
            output_tokens = max(0, int(usage.get("completion_tokens") or 0))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            raise LlmProviderError("invalid_response") from None
        latency_ms = max(0, int((self._monotonic() - started) * 1000))
        return ProviderGenerationResult(
            reply_payload={"reply_text": reply_payload["reply_text"].strip()},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            safe_metadata={
                "provider_id": provider.provider_id,
                "model": provider.model,
                "status": "succeeded",
            },
        )


def _status_error(status: int) -> str:
    if status in {401, 403}:
        return "auth_failed"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "provider_unavailable"
    return "invalid_response"
