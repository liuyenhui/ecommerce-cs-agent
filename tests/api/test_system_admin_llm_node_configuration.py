from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import InMemorySystemAdminAuthService, SystemAdminSession
from ecommerce_cs_agent.services.llm_node_configuration import ApiKeyCipher, InMemoryLlmNodeConfigurationRepository


HEADERS = {"Cookie": "agent_system_admin_session=test-system-session"}
MASTER_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def client_for(role: str = "super_admin") -> tuple[TestClient, InMemoryLlmNodeConfigurationRepository]:
    settings = Settings(environment="test")
    auth = InMemorySystemAdminAuthService(settings)
    auth.sessions[settings.system_admin_session] = SystemAdminSession(
        token=settings.system_admin_session,
        user_id="system-user-1",
        email="system@example.test",
        display_name="System User",
        role=role,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    repository = InMemoryLlmNodeConfigurationRepository(ApiKeyCipher.from_base64(MASTER_KEY))
    app = create_app(
        settings,
        system_admin_auth_service_override=auth,
        llm_node_configuration_repository=repository,
    )
    return TestClient(app), repository


def create_model(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/system-admin/llms",
        headers=HEADERS,
        json={
            "name": "模型 A",
            "provider": "openai_compatible",
            "base_url": "https://llm.example.test/v1",
            "model_id": "chat-pro",
            "api_key": "fake-api-one-time-9876",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_llm_api_accepts_one_time_key_and_only_returns_mask() -> None:
    client, _repository = client_for()
    model = create_model(client)
    listed = client.get("/v1/system-admin/llms", headers=HEADERS)

    assert model["api_key_masked"] == "••••9876"
    assert "api_key" not in model
    assert "fake-api-one-time-9876" not in listed.text
    assert listed.json()["items"][0]["has_api_key"] is True


def test_binding_api_comes_from_server_registry_and_replaces_all_nodes() -> None:
    client, _repository = client_for()
    model = create_model(client)
    tested = client.post(f"/v1/system-admin/llms/{model['llm_id']}/connection-tests", headers=HEADERS, json={})
    before = client.get("/v1/system-admin/langgraph-llm-bindings", headers=HEADERS)
    saved = client.put(
        "/v1/system-admin/langgraph-llm-bindings",
        headers=HEADERS,
        json={
            "expected_revision": 0,
            "bindings": [
                {"node_id": "classify_service_stage", "llm_id": model["llm_id"]},
                {"node_id": "generate_candidate", "llm_id": model["llm_id"]},
            ],
        },
    )

    assert tested.status_code == 200
    assert [item["node_id"] for item in before.json()["nodes"]][:3] == [
        "normalize_request", "retrieve_context", "classify_service_stage"
    ]
    assert saved.status_code == 200
    assert saved.json()["scope"] == "global"
    assert saved.json()["revision"] == 1


@pytest.mark.parametrize("role", ["technical_support", "security_auditor"])
def test_read_only_roles_cannot_create_or_save_bindings(role: str) -> None:
    client, _repository = client_for(role)
    create = client.post(
        "/v1/system-admin/llms",
        headers=HEADERS,
        json={
            "name": "forbidden",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model_id": "gpt-4.1-mini",
            "api_key": "forbidden-secret",
        },
    )
    write = client.put(
        "/v1/system-admin/langgraph-llm-bindings",
        headers=HEADERS,
        json={"expected_revision": 0, "bindings": []},
    )

    assert create.status_code == 403
    assert write.status_code == 403
