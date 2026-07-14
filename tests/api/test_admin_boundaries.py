from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.core.config import Settings, load_settings
from ecommerce_cs_agent.services.admin_auth import (
    InMemorySystemAdminAuthService,
    system_admin_auth_service_for,
)


def _test_app():
    return create_app(Settings(environment="test", database_url=None))


def test_system_admin_auth_service_allows_in_memory_only_in_test() -> None:
    service = system_admin_auth_service_for(Settings(environment="test", database_url=None))

    assert isinstance(service, InMemorySystemAdminAuthService)


def test_system_admin_auth_service_requires_database_outside_test() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL is required for System Admin"):
        system_admin_auth_service_for(Settings(environment="development", database_url=None))


def test_external_api_token_cannot_call_customer_admin():
    client = TestClient(_test_app())

    response = client.get(
        "/v1/admin/auth/me",
        headers={"Authorization": "Bearer test-agent-token"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_customer_admin_session_cannot_call_system_admin():
    client = TestClient(_test_app())

    response = client.get(
        "/v1/system-admin/health",
        headers={"Cookie": "agent_admin_session=test-admin-session"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_system_admin_session_cannot_call_customer_admin():
    client = TestClient(_test_app())

    response = client.get(
        "/v1/admin/auth/me",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )

    assert response.status_code in {401, 403}
    assert response.json()["error"]["code"] in {"unauthorized", "forbidden"}


def test_external_api_token_cannot_call_system_admin():
    client = TestClient(_test_app())

    response = client.get(
        "/v1/system-admin/auth/me",
        headers={"Authorization": "Bearer test-agent-token"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_customer_admin_me_and_core_lists():
    client = TestClient(_test_app())
    headers = {"Cookie": "agent_admin_session=test-admin-session"}

    me = client.get("/v1/admin/auth/me", headers=headers)
    organizations = client.get("/v1/admin/organizations", headers=headers)
    stores = client.get("/v1/admin/stores", headers=headers)
    audit = client.get("/v1/admin/audit-logs", headers=headers)

    assert me.status_code == 200
    assert me.json()["active_organization_id"] == "org-001"
    assert organizations.status_code == 200
    assert organizations.json()["items"][0]["id"] == "org-001"
    assert stores.status_code == 200
    assert stores.json()["items"][0]["id"] == "store-001"
    assert audit.status_code == 200
    assert "items" in audit.json()
    assert organizations.json()["page"] == {"page": 1, "page_size": 50, "total": 1}


def test_product_content_upsert_writes_audit_and_health():
    client = TestClient(_test_app())
    headers = {"Cookie": "agent_admin_session=test-admin-session"}

    product = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-001",
            "store_id": "store-001",
            "external_product_id": "sku-001",
            "title": "测试商品",
            "attributes": {"color": "red"},
        },
    )
    health = client.get(
        f"/v1/product-content/products/{product.json()['product_id']}/health",
        headers=headers,
    )
    audit = client.get("/v1/admin/audit-logs", headers=headers)

    assert product.status_code == 201
    assert product.json()["product_id"].startswith("product-")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert audit.status_code == 200
    assert audit.json()["items"][0]["action"] == "product.upsert"


def test_product_content_ids_are_tenant_scoped():
    client = TestClient(_test_app())
    headers = {"Cookie": "agent_admin_session=test-admin-session"}

    first = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-a",
            "store_id": "store-001",
            "external_product_id": "sku-001",
            "title": "商品 A",
        },
    )
    second = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-b",
            "store_id": "store-001",
            "external_product_id": "sku-001",
            "title": "商品 B",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["product_id"] != second.json()["product_id"]


def test_system_admin_core_health_and_readiness():
    client = TestClient(_test_app())
    headers = {"Cookie": "agent_system_admin_session=test-system-session"}

    me = client.get("/v1/system-admin/auth/me", headers=headers)
    health = client.get("/v1/system-admin/health", headers=headers)
    readiness = client.get("/v1/system-admin/readiness/stores", headers=headers)

    assert me.status_code == 200
    assert me.json()["user"]["role"] == "super_admin"
    assert me.json()["user"]["system_user_id"] == "sysadmin-001"
    assert me.json()["roles"] == ["super_admin"]
    assert "system:read" in me.json()["capabilities"]
    assert health.status_code == 200
    assert health.json()["status"] in {"healthy", "degraded"}
    assert readiness.status_code == 200
    assert readiness.json()["items"][0]["store_id"] == "store-001"
    assert {item["code"] for item in readiness.json()["items"][0]["checks"]} == {
        "product_content",
        "price_snapshot",
        "knowledge_review",
        "rules",
        "action_capabilities",
        "api_integration",
    }


def test_admin_login_rejects_bad_credentials_and_sets_spec_cookie_for_valid_credentials():
    client = TestClient(_test_app())

    bad = client.post("/v1/admin/auth/login", json={"email": "admin@example.test", "password": "bad"})
    good = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert "agent_admin_session=" in good.headers["set-cookie"]
    assert "agent_system_admin_session=" not in good.headers["set-cookie"]


def test_system_admin_login_rejects_bad_credentials_and_sets_spec_cookie_for_valid_credentials():
    client = TestClient(_test_app())

    bad = client.post(
        "/v1/system-admin/auth/login",
        json={"email": "system-admin@example.test", "password": "bad"},
    )
    good = client.post(
        "/v1/system-admin/auth/login",
        json={"email": "system-admin@example.test", "password": "system-admin-password"},
    )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert "agent_system_admin_session=" in good.headers["set-cookie"]
    assert "agent_admin_session=" not in good.headers["set-cookie"]


def test_system_admin_logout_revokes_server_session():
    client = TestClient(_test_app())
    login = client.post(
        "/v1/system-admin/auth/login",
        json={"email": "system-admin@example.test", "password": "system-admin-password"},
    )
    cookie = login.headers["set-cookie"].split(";", 1)[0]

    logout = client.post("/v1/system-admin/auth/logout", headers={"Cookie": cookie})
    me = client.get("/v1/system-admin/auth/me", headers={"Cookie": cookie})

    assert logout.status_code == 204
    assert me.status_code == 401


def test_production_settings_fail_fast_without_required_secrets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for key in (
        "AGENT_API_TOKEN",
        "ADMIN_SESSION_SECRET",
        "SESSION_SECRET",
        "SYSTEM_ADMIN_SESSION_SECRET",
        "JWT_SECRET",
        "ADMIN_INITIAL_EMAIL",
        "ADMIN_INITIAL_PASSWORD_HASH",
        "SYSTEM_ADMIN_INITIAL_EMAIL",
        "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH",
        "DATABASE_URL",
        "OPEN_ERP_INTEGRATION_TOKEN",
        "OPEN_ERP_BILLING_LEASE_SECRET",
        "LLM_CURSOR_SIGNING_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    try:
        load_settings()
    except RuntimeError as exc:
        assert "Missing required production settings" in str(exc)
        assert "LLM_CURSOR_SIGNING_KEY" in str(exc)
    else:
        raise AssertionError("production settings should require external secrets")


def test_production_settings_fail_fast_when_only_llm_cursor_signing_key_is_missing(monkeypatch):
    required = {
        "AGENT_API_TOKEN": "agent-token",
        "ADMIN_SESSION_SECRET": "admin-session",
        "SYSTEM_ADMIN_SESSION_SECRET": "system-session",
        "ADMIN_INITIAL_EMAIL": "admin@example.test",
        "ADMIN_INITIAL_PASSWORD_HASH": "plain:admin-password",
        "SYSTEM_ADMIN_INITIAL_EMAIL": "system-admin@example.test",
        "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH": "plain:system-admin-password",
        "DATABASE_URL": "postgresql://example",
        "OPEN_ERP_INTEGRATION_TOKEN": "open-erp-token",
        "OPEN_ERP_BILLING_LEASE_SECRET": "billing-secret",
    }
    monkeypatch.setenv("APP_ENV", "production")
    for key, value in required.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("LLM_CURSOR_SIGNING_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LLM_CURSOR_SIGNING_KEY"):
        load_settings()


def test_production_settings_accept_existing_runtime_secret_keys(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-token")
    monkeypatch.setenv("SESSION_SECRET", "admin-session")
    monkeypatch.setenv("JWT_SECRET", "system-session")
    monkeypatch.setenv("ADMIN_INITIAL_EMAIL", "admin@example.test")
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD_HASH", "plain:admin-password")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("OPEN_ERP_INTEGRATION_TOKEN", "open-erp-token")
    monkeypatch.setenv("OPEN_ERP_BILLING_LEASE_SECRET", "billing-secret")
    monkeypatch.setenv("LLM_CURSOR_SIGNING_KEY", "test-only-fixed-llm-cursor-signing-key")
    for key in (
        "ADMIN_SESSION_SECRET",
        "SYSTEM_ADMIN_SESSION_SECRET",
        "SYSTEM_ADMIN_INITIAL_EMAIL",
        "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings()
    assert settings.llm_cursor_signing_key == "test-only-fixed-llm-cursor-signing-key"

    assert settings.admin_session == "admin-session"
    assert settings.system_admin_session == "system-session"
    assert settings.system_admin_initial_email == "admin@example.test"
    assert settings.system_admin_initial_password_hash == "plain:admin-password"


def test_development_settings_accept_local_test_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    settings = load_settings()

    assert settings.agent_api_token == "test-agent-token"
