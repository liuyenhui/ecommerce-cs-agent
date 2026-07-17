from __future__ import annotations

import json

import pytest

from ecommerce_cs_agent.services.admin_auth import SystemAdminSession
from ecommerce_cs_agent.services.llm_node_configuration import (
    ApiKeyCipher,
    InMemoryLlmNodeConfigurationRepository,
    LANGGRAPH_NODE_REGISTRY,
)
from ecommerce_cs_agent.services.llm import NodeBoundReplyProvider


SESSION = SystemAdminSession(
    token="session",
    user_id="system-user-1",
    email="system@example.test",
    display_name="System User",
    role="super_admin",
    expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
)
MASTER_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def payload(name: str = "客服模型", api_key: str = "fake-live-secret-1234") -> dict[str, object]:
    return {
        "name": name,
        "provider": "openai_compatible",
        "base_url": "https://llm.example.test/v1",
        "model_id": "chat-pro",
        "api_key": api_key,
    }


def test_api_key_cipher_uses_random_authenticated_encryption_and_never_returns_plaintext() -> None:
    cipher = ApiKeyCipher.from_base64(MASTER_KEY)

    first = cipher.encrypt("fake-live-secret-1234")
    second = cipher.encrypt("fake-live-secret-1234")

    assert first["ciphertext"] != second["ciphertext"]
    assert first["nonce"] != second["nonce"]
    assert first["encryption_version"] == "aes-256-gcm-v1"
    assert "fake-live-secret-1234" not in json.dumps(first)
    assert cipher.decrypt(first) == "fake-live-secret-1234"


def test_repository_masks_keys_and_requires_passed_connection_before_binding() -> None:
    repository = InMemoryLlmNodeConfigurationRepository(ApiKeyCipher.from_base64(MASTER_KEY))
    created = repository.create_llm(SESSION, payload())

    assert created["has_api_key"] is True
    assert created["api_key_masked"] == "••••1234"
    assert "api_key" not in created
    assert "fake-live-secret-1234" not in json.dumps(repository.audit_logs)

    with pytest.raises(Exception) as failure:
        repository.replace_bindings(
            SESSION,
            {
                "expected_revision": 0,
                "bindings": [
                    {"node_id": "classify_service_stage", "llm_id": created["llm_id"]},
                    {"node_id": "generate_candidate", "llm_id": created["llm_id"]},
                ],
            },
        )
    assert failure.value.detail["error"]["code"] == "llm_connection_test_required"

    tested = repository.test_connection(SESSION, created["llm_id"])
    saved = repository.replace_bindings(
        SESSION,
        {
            "expected_revision": 0,
            "bindings": [
                {"node_id": "classify_service_stage", "llm_id": created["llm_id"]},
                {"node_id": "generate_candidate", "llm_id": created["llm_id"]},
            ],
        },
    )

    assert tested["status"] == "passed"
    assert saved["revision"] == 1
    assert {item["node_id"] for item in saved["nodes"] if item["uses_llm"]} == {
        "classify_service_stage",
        "generate_candidate",
    }
    assert next(item for item in saved["nodes"] if item["node_id"] == "normalize_request")["uses_llm"] is False


def test_binding_replace_is_complete_revisioned_and_rejects_disabled_models_atomically() -> None:
    repository = InMemoryLlmNodeConfigurationRepository(ApiKeyCipher.from_base64(MASTER_KEY))
    first = repository.create_llm(SESSION, payload("模型 A", "key-a-1111"))
    second = repository.create_llm(SESSION, payload("模型 B", "key-b-2222"))
    repository.test_connection(SESSION, first["llm_id"])
    repository.test_connection(SESSION, second["llm_id"])

    with pytest.raises(Exception) as missing:
        repository.replace_bindings(
            SESSION,
            {"expected_revision": 0, "bindings": [{"node_id": "classify_service_stage", "llm_id": first["llm_id"]}]},
        )
    assert missing.value.detail["error"]["code"] == "required_node_binding_missing"
    assert repository.get_bindings(SESSION)["revision"] == 0

    repository.update_llm(SESSION, second["llm_id"], {"expected_revision": 2, "enabled": False})
    with pytest.raises(Exception) as disabled:
        repository.replace_bindings(
            SESSION,
            {
                "expected_revision": 0,
                "bindings": [
                    {"node_id": "classify_service_stage", "llm_id": first["llm_id"]},
                    {"node_id": "generate_candidate", "llm_id": second["llm_id"]},
                ],
            },
        )
    assert disabled.value.detail["error"]["code"] == "llm_not_bindable"
    assert repository.get_bindings(SESSION)["revision"] == 0


def test_connection_affecting_edit_invalidates_previous_test_before_binding() -> None:
    repository = InMemoryLlmNodeConfigurationRepository(ApiKeyCipher.from_base64(MASTER_KEY))
    model = repository.create_llm(SESSION, payload())
    repository.test_connection(SESSION, model["llm_id"])

    updated = repository.update_llm(SESSION, model["llm_id"], {"expected_revision": 2, "model_id": "chat-pro-v2"})

    assert updated["status"] == "untested"
    assert updated["last_connection_test_status"] is None
    with pytest.raises(Exception) as failure:
        repository.replace_bindings(SESSION, {"expected_revision": 0, "bindings": [
            {"node_id": "classify_service_stage", "llm_id": model["llm_id"]},
            {"node_id": "generate_candidate", "llm_id": model["llm_id"]},
        ]})
    assert failure.value.detail["error"]["code"] == "llm_connection_test_required"

def test_registry_is_the_complete_graph_order_and_only_real_llm_nodes_are_selectable() -> None:
    assert [item.node_id for item in LANGGRAPH_NODE_REGISTRY] == [
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
    assert [item.node_id for item in LANGGRAPH_NODE_REGISTRY if item.uses_llm] == [
        "classify_service_stage",
        "generate_candidate",
    ]


def test_node_bound_provider_resolves_each_real_node_independently_without_fallback() -> None:
    resolved: list[str] = []

    class Provider:
        model_version = "fake"

        def classify_service_stage(self, **_kwargs: object) -> dict[str, object]:
            return {"primary_stage": "pre_sale", "secondary_stages": [], "confidence": 0.9, "reason_code": "purchase_intent", "evidence_refs": [], "needs_context": []}

        def generate_candidate(self, **_kwargs: object) -> str:
            return "bound candidate"

    provider = NodeBoundReplyProvider(
        resolver=lambda node_id: resolved.append(node_id) or {"llm_id": node_id, "model_id": f"model-{node_id}", "base_url": "https://llm.example.test/v1", "api_key": "secret"},
        provider_factory=lambda _config: Provider(),
    )

    provider.classify_service_stage(message="hi", conversation={}, context={})
    candidate = provider.generate_candidate(message="hi", knowledge=[], service_stage={"primary_stage": "pre_sale"}, context={})

    assert resolved == ["classify_service_stage", "generate_candidate"]
    assert candidate == "bound candidate"


def test_node_bound_provider_propagates_model_failure_instead_of_switching_models() -> None:
    class FailedProvider:
        model_version = "failed"

        def generate_candidate(self, **_kwargs: object) -> str:
            raise RuntimeError("safe_llm_failure")

    provider = NodeBoundReplyProvider(
        resolver=lambda _node_id: {"llm_id": "only-model", "model_id": "failed-model", "base_url": "https://llm.example.test/v1", "api_key": "secret"},
        provider_factory=lambda _config: FailedProvider(),
    )

    with pytest.raises(RuntimeError, match="safe_llm_failure"):
        provider.generate_candidate(message="hi", knowledge=[], service_stage={"primary_stage": "pre_sale"}, context={})
