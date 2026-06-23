from __future__ import annotations

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import InMemoryAdminAuthService


def test_in_memory_admin_oidc_autolinks_existing_active_email_and_writes_audit() -> None:
    service = InMemoryAdminAuthService(Settings())

    response, token = service.login_oidc(
        {
            "sub": "acct-admin-001",
            "email": "admin@example.test",
            "email_verified": True,
            "name": "Admin User",
        }
    )

    assert token
    assert response["user"]["user_id"] == "admin-001"
    assert response["user"]["fcihome_account_sub"] == "acct-admin-001"
    assert service.users["admin-001"]["fcihome_account_sub"] == "acct-admin-001"
    assert service.audit_logs[0]["action"] == "auth.oidc.login"


def test_in_memory_admin_oidc_does_not_create_permissions_for_unknown_email() -> None:
    service = InMemoryAdminAuthService(Settings())

    try:
        service.login_oidc(
            {
                "sub": "acct-new-001",
                "email": "new@example.test",
                "email_verified": True,
                "name": "New User",
            }
        )
    except Exception as exc:
        assert getattr(exc, "status_code") == 403
    else:
        raise AssertionError("unknown OIDC account should not create admin permissions")
