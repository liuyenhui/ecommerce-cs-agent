from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from ecommerce_cs_agent.core.config import Settings
from tests.admin_fixtures import create_test_app


def _oidc_settings() -> Settings:
    return Settings(
        environment="test",
        admin_oidc_enabled=True,
        admin_oidc_issuer="https://account.fcihome.com",
        admin_oidc_client_id="customer-admin-dev",
        admin_oidc_client_secret="customer-secret",
        admin_oidc_redirect_uri="https://admin.ecommerce-cs-agent-dev.fcihome.com/v1/admin/auth/oidc/callback",
    )


def test_customer_admin_oidc_start_disabled_returns_clear_config_error() -> None:
    client = TestClient(create_test_app())

    response = client.get("/v1/admin/auth/oidc/start", follow_redirects=False)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "oidc_disabled"
    assert "agent_admin_session=" not in response.headers.get("set-cookie", "")
    assert "agent_system_admin_session=" not in response.headers.get("set-cookie", "")


def test_customer_admin_oidc_start_redirects_to_fcihome_without_admin_session() -> None:
    client = TestClient(create_test_app(_oidc_settings()))

    response = client.get("/v1/admin/auth/oidc/start", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://account.fcihome.com/oauth/authorize?")
    assert "client_id=customer-admin-dev" in response.headers["location"]
    assert "code_challenge_method=S256" in response.headers["location"]
    assert "agent_admin_oidc_state=" in response.headers["set-cookie"]
    assert "agent_admin_session=" not in response.headers.get("set-cookie", "")
    assert "agent_system_admin_session=" not in response.headers.get("set-cookie", "")


def test_customer_admin_oidc_callback_sets_only_customer_session(monkeypatch) -> None:
    settings = _oidc_settings()
    client = TestClient(create_test_app(settings))
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
    set_cookie = callback.headers["set-cookie"]
    assert "agent_admin_session=" in set_cookie
    assert "agent_system_admin_session=" not in set_cookie
    me = client.get("/v1/admin/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["fcihome_account_sub"] == "acct-admin-001"
    system_me = client.get("/v1/system-admin/auth/me")
    assert system_me.status_code in {401, 403}


def test_customer_admin_oidc_callback_state_failure_redirects_to_distinct_login_error(monkeypatch) -> None:
    client = TestClient(create_test_app(_oidc_settings()))
    client.get("/v1/admin/auth/oidc/start", follow_redirects=False)

    def fake_exchange(_settings: Settings, _code: str, _state_payload: dict[str, str]) -> dict[str, object]:
        raise AssertionError("exchange must not run when state validation fails")

    monkeypatch.setattr("ecommerce_cs_agent.services.oidc.exchange_code_for_userinfo", fake_exchange)

    callback = client.get(
        "/v1/admin/auth/oidc/callback?code=account-code&state=wrong",
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?error=oidc_state_pkce_failed"
    assert "agent_admin_session=" not in callback.headers.get("set-cookie", "")
    assert "agent_system_admin_session=" not in callback.headers.get("set-cookie", "")


def test_customer_admin_oidc_callback_unbound_account_redirects_to_distinct_login_error(monkeypatch) -> None:
    settings = _oidc_settings()
    client = TestClient(create_test_app(settings))
    start = client.get("/v1/admin/auth/oidc/start", follow_redirects=False)
    state = _query_value(start.headers["location"], "state")

    def fake_exchange(_settings: Settings, _code: str, _state_payload: dict[str, str]) -> dict[str, object]:
        return {
            "sub": "acct-new-001",
            "email": "unknown@example.test",
            "email_verified": True,
        }

    monkeypatch.setattr("ecommerce_cs_agent.services.oidc.exchange_code_for_userinfo", fake_exchange)

    callback = client.get(
        f"/v1/admin/auth/oidc/callback?code=account-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?error=oidc_unbound_account"
    assert "agent_admin_session=" not in callback.headers.get("set-cookie", "")
    assert "agent_system_admin_session=" not in callback.headers.get("set-cookie", "")


def test_customer_admin_oidc_link_requires_customer_session(monkeypatch) -> None:
    settings = _oidc_settings()
    client = TestClient(create_test_app(settings))

    missing_session = client.post(
        "/v1/admin/auth/oidc/link",
        json={"code": "account-code", "state": "state"},
    )
    assert missing_session.status_code == 401

    login = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    start = client.get("/v1/admin/auth/oidc/start", follow_redirects=False)
    state = _query_value(start.headers["location"], "state")

    def fake_exchange(_settings: Settings, code: str, state_payload: dict[str, str]) -> dict[str, object]:
        assert code == "account-code"
        assert state_payload["state"] == state
        return {
            "sub": "acct-admin-001",
            "email": "admin@example.test",
            "email_verified": True,
        }

    monkeypatch.setattr("ecommerce_cs_agent.services.oidc.exchange_code_for_userinfo", fake_exchange)
    linked = client.post(
        "/v1/admin/auth/oidc/link",
        json={"code": "account-code", "state": state},
    )

    assert login.status_code == 200
    assert linked.status_code == 200
    assert linked.json()["user"]["fcihome_account_sub"] == "acct-admin-001"


def test_system_admin_has_no_oidc_entrypoint() -> None:
    client = TestClient(create_test_app(_oidc_settings()))

    response = client.get("/v1/system-admin/auth/oidc/start")

    assert response.status_code == 404


def _query_value(url: str, key: str) -> str:
    values = parse_qs(urlparse(url).query).get(key)
    assert values
    return values[0]
