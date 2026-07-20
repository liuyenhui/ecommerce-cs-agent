import json

import pytest

from ecommerce_cs_agent.services.llm_provider import (
    LlmProviderError,
    OpenAICompatibleProviderClient,
)
from ecommerce_cs_agent.services.llm_runtime import RuntimeProvider, RuntimeRoutePolicy


def _provider() -> RuntimeProvider:
    return RuntimeProvider(
        provider_id="provider-1",
        provider_type="openai_compatible",
        base_url="https://llm.example.test/v1",
        secret_namespace="runtime",
        secret_name="llm",
        secret_key="api-key",
        model="deepseek-chat",
        enabled=True,
        status="active",
    )


def _policy(*, retries: int = 0) -> RuntimeRoutePolicy:
    return RuntimeRoutePolicy(0.2, 256, 12, retries, 5, 60)


class RecordingSecureSession:
    def __init__(self, responses: list[tuple[int, bytes]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def execute_json(self, *, provider, path, payload, timeout_seconds):
        self.calls.append(
            {"provider": provider, "path": path, "payload": payload, "timeout": timeout_seconds}
        )
        return self.responses.pop(0)


def test_generates_strict_json_reply_with_safe_metadata() -> None:
    content = json.dumps({"reply_text": "可以的，这款比熊可以用。"}, ensure_ascii=False)
    session = RecordingSecureSession(
        [(200, json.dumps({"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 42, "completion_tokens": 13}}).encode())]
    )
    client = OpenAICompatibleProviderClient(session=session)

    result = client.generate(
        _provider(), messages=[{"role": "user", "content": "safe prompt"}], policy=_policy()
    )

    assert result.reply_payload == {"reply_text": "可以的，这款比熊可以用。"}
    assert result.input_tokens == 42
    assert result.output_tokens == 13
    request = session.calls[0]
    assert request["path"] == "/chat/completions"
    assert request["payload"]["model"] == "deepseek-chat"
    assert request["payload"]["response_format"] == {"type": "json_object"}
    assert "Authorization" not in json.dumps(result.safe_metadata)
    assert "safe prompt" not in json.dumps(result.safe_metadata)


@pytest.mark.parametrize(
    ("status", "error_code"),
    [(401, "auth_failed"), (429, "rate_limited"), (503, "provider_unavailable")],
)
def test_maps_provider_status_without_leaking_body(status: int, error_code: str) -> None:
    session = RecordingSecureSession([(status, b"secret upstream detail")])

    with pytest.raises(LlmProviderError) as raised:
        OpenAICompatibleProviderClient(session=session).generate(
            _provider(), messages=[], policy=_policy()
        )

    assert raised.value.code == error_code
    assert "secret upstream detail" not in str(raised.value)


def test_retries_bounded_transient_failures_and_rejects_invalid_json() -> None:
    good = json.dumps(
        {"choices": [{"message": {"content": '{"reply_text":"安全回复"}'}}], "usage": {}}
    ).encode()
    session = RecordingSecureSession([(503, b"unavailable"), (200, good)])
    result = OpenAICompatibleProviderClient(session=session).generate(
        _provider(), messages=[], policy=_policy(retries=1)
    )
    assert result.reply_payload == {"reply_text": "安全回复"}
    assert len(session.calls) == 2

    invalid = RecordingSecureSession([(200, b'{"choices":[]}')])
    with pytest.raises(LlmProviderError) as raised:
        OpenAICompatibleProviderClient(session=invalid).generate(
            _provider(), messages=[], policy=_policy()
        )
    assert raised.value.code == "invalid_response"
