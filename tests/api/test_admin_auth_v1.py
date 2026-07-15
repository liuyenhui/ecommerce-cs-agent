from __future__ import annotations

from fastapi.testclient import TestClient

from tests.admin_fixtures import create_test_app


def test_customer_admin_login_creates_server_session_and_me_matches_openapi_shape() -> None:
    client = TestClient(create_test_app())

    login = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    assert login.status_code == 200
    assert "agent_admin_session=" in login.headers["set-cookie"]
    cookie = login.headers["set-cookie"].split(";", 1)[0]
    token = cookie.split("=", 1)[1]
    assert token
    assert token != "test-admin-session"

    me = client.get("/v1/admin/auth/me", headers={"Cookie": cookie})

    assert me.status_code == 200
    body = me.json()
    assert body["user"]["user_id"] == "admin-001"
    assert body["user"]["roles"] == ["owner"]
    assert body["organizations"][0]["id"] == "org-001"
    assert body["stores"][0]["id"] == "store-001"
    assert body["active_organization_id"] == "org-001"
    assert body["active_store_id"] == "store-001"


def test_customer_admin_logout_revokes_server_session() -> None:
    client = TestClient(create_test_app())
    login = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    cookie = login.headers["set-cookie"].split(";", 1)[0]

    logout = client.post("/v1/admin/auth/logout", headers={"Cookie": cookie})
    me = client.get("/v1/admin/auth/me", headers={"Cookie": cookie})

    assert logout.status_code == 204
    assert me.status_code == 401


def test_admin_context_lists_use_openapi_response_shapes() -> None:
    client = TestClient(create_test_app())
    login = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    cookie = login.headers["set-cookie"].split(";", 1)[0]

    organizations = client.get("/v1/admin/organizations", headers={"Cookie": cookie})
    stores = client.get("/v1/admin/stores?organization_id=org-001", headers={"Cookie": cookie})
    users = client.get("/v1/admin/users?organization_id=org-001", headers={"Cookie": cookie})

    assert organizations.status_code == 200
    assert "organizations" in organizations.json()
    assert stores.status_code == 200
    assert "stores" in stores.json()
    assert users.status_code == 200
    assert "page_info" in users.json()


def test_admin_store_settings_invitation_roles_and_audit_are_not_static() -> None:
    client = TestClient(create_test_app())
    login = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    cookie = login.headers["set-cookie"].split(";", 1)[0]

    settings = client.patch(
        "/v1/admin/stores/store-001/settings",
        headers={"Cookie": cookie},
        json={
            "organization_id": "org-001",
            "reason": "enable assist mode",
            "settings": {"assist_enabled": True},
        },
    )
    invitation = client.post(
        "/v1/admin/invitations",
        headers={"Cookie": cookie},
        json={
            "organization_id": "org-001",
            "email": "invitee@example.test",
            "roles": ["store_operator"],
            "store_ids": ["store-001"],
            "reason": "add operator",
            "idempotency_key": "invite-001",
        },
    )
    role_update = client.patch(
        "/v1/admin/users/admin-001/roles",
        headers={"Cookie": cookie},
        json={
            "organization_id": "org-001",
            "roles": ["owner"],
            "store_ids": ["store-001"],
            "reason": "verify owner",
        },
    )
    audit = client.get("/v1/admin/audit-logs?organization_id=org-001", headers={"Cookie": cookie})

    assert settings.status_code == 200
    assert settings.json()["settings"]["assist_enabled"] is True
    assert settings.json()["audit_log_id"].startswith("audit-")
    assert invitation.status_code == 201
    assert invitation.json()["roles"] == ["store_operator"]
    assert role_update.status_code == 200
    assert role_update.json()["user"]["roles"] == ["owner"]
    assert audit.status_code == 200
    assert len(audit.json()["items"]) >= 3
