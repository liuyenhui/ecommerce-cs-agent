from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.core.config import Settings


def _oidc_settings() -> Settings:
    return Settings(
        oidc_enabled=True,
        oidc_issuer="https://account.fcihome.com",
        oidc_client_id="customer-admin-dev",
        oidc_client_secret="customer-secret",
        oidc_redirect_uri="https://admin.ecommerce-cs-agent-dev.fcihome.com/v1/admin/auth/oidc/callback",
    )


def test_customer_admin_oidc_start_redirects_to_account_without_admin_session() -> None:
    client = TestClient(create_app(_oidc_settings()))

    response = client.get("/v1/admin/auth/oidc/start", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://account.fcihome.com/oauth/authorize?")
    assert "client_id=customer-admin-dev" in response.headers["location"]
    assert "code_challenge_method=S256" in response.headers["location"]
    assert "agent_admin_oidc_state=" in response.headers["set-cookie"]
    assert "agent_admin_session=" not in response.headers.get("set-cookie", "")


def test_customer_admin_oidc_callback_autolinks_existing_email_and_sets_customer_session(monkeypatch) -> None:
    settings = _oidc_settings()
    client = TestClient(create_app(settings))
    start = client.get("/v1/admin/auth/oidc/start", follow_redirects=False)
    state = _query_value(start.headers["location"], "state")

    def fake_exchange(_settings: Settings, code: str, state_payload: dict[str, str]) -> dict[str, object]:
        assert code == "account-code"
        assert state_payload["state"] == state
        return {
            "sub": "acct-admin-001",
            "email": "admin@example.test",
            "email_verified": True,
            "name": "Admin User",
        }

    monkeypatch.setattr("ecommerce_cs_agent.services.oidc.exchange_code_for_userinfo", fake_exchange)

    callback = client.get(
        f"/v1/admin/auth/oidc/callback?code=account-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/admin"
    assert "agent_admin_session=" in callback.headers["set-cookie"]
    assert "agent_admin_oidc_state=" in callback.headers["set-cookie"]
    me = client.get("/v1/admin/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == "admin@example.test"
    assert body["user"]["fcihome_account_sub"] == "acct-admin-001"
    system_me = client.get("/v1/system-admin/auth/me")
    assert system_me.status_code in {401, 403}


def test_customer_admin_oidc_callback_rejects_state_mismatch(monkeypatch) -> None:
    client = TestClient(create_app(_oidc_settings()))
    client.get("/v1/admin/auth/oidc/start", follow_redirects=False)

    def fake_exchange(_settings: Settings, _code: str, _state_payload: dict[str, str]) -> dict[str, object]:
        raise AssertionError("exchange must not run when state mismatches")

    monkeypatch.setattr("ecommerce_cs_agent.services.oidc.exchange_code_for_userinfo", fake_exchange)

    callback = client.get("/v1/admin/auth/oidc/callback?code=account-code&state=wrong")

    assert callback.status_code == 400
    assert callback.json()["error"]["code"] == "invalid_oidc_state"


def test_customer_admin_oidc_link_requires_customer_session() -> None:
    client = TestClient(create_app(_oidc_settings()))
    response = client.post("/v1/admin/auth/oidc/link", json={"sub": "acct-admin-001", "email": "admin@example.test"})
    assert response.status_code == 401

    login = client.post("/v1/admin/auth/login", json={"email": "admin@example.test", "password": "admin-password"})
    assert login.status_code == 200
    linked = client.post("/v1/admin/auth/oidc/link", json={"sub": "acct-admin-001", "email": "admin@example.test"})
    assert linked.status_code == 200
    assert linked.json()["user"]["fcihome_account_sub"] == "acct-admin-001"


def _query_value(url: str, key: str) -> str:
    values = parse_qs(urlparse(url).query).get(key)
    assert values
    return values[0]
