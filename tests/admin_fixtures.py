from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import (
    AdminSession,
    InMemoryAdminAuthService,
    InMemorySystemAdminAuthService,
    SystemAdminSession,
)
from ecommerce_cs_agent.services.system_admin import InMemorySystemAdminRepository


def customer_admin_auth_fixture(settings: Settings) -> InMemoryAdminAuthService:
    service = InMemoryAdminAuthService(settings)
    service.organizations["org-001"] = {
        "id": "org-001",
        "name": "Fixture Organization",
        "status": "active",
        "metadata": {},
    }
    service.stores["store-001"] = {
        "id": "store-001",
        "organization_id": "org-001",
        "name": "Fixture PDD Store",
        "platform": "pdd",
        "status": "active",
        "metadata": {},
        "settings": {},
    }
    service.users["admin-001"] = {
        "user_id": "admin-001",
        "email": settings.admin_initial_email,
        "display_name": "Customer Admin",
        "fcihome_account_sub": None,
        "roles": ["owner"],
        "organization_ids": ["org-001"],
        "store_ids": ["store-001"],
        "status": "active",
        "last_login_at": None,
    }
    service.sessions[settings.admin_session] = AdminSession(
        token=settings.admin_session,
        user_id="admin-001",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    return service


def system_admin_auth_fixture(settings: Settings) -> InMemorySystemAdminAuthService:
    service = InMemorySystemAdminAuthService(settings)
    service.users["sysadmin-001"] = {
        "id": "sysadmin-001",
        "email": settings.system_admin_initial_email,
        "name": "System Admin",
        "role": "super_admin",
        "status": "active",
    }
    service.sessions[settings.system_admin_session] = SystemAdminSession(
        token=settings.system_admin_session,
        user_id="sysadmin-001",
        email=settings.system_admin_initial_email,
        display_name="System Admin",
        role="super_admin",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    return service


def system_admin_repository_fixture() -> InMemorySystemAdminRepository:
    repository = InMemorySystemAdminRepository()
    repository.users["sysadmin-001"] = {
        "id": "sysadmin-001",
        "system_user_id": "sysadmin-001",
        "email": "system-admin@example.test",
        "display_name": "System Admin",
        "role": "super_admin",
        "roles": ["super_admin"],
        "status": "active",
    }
    repository.organizations["org-001"] = {
        "id": "org-001",
        "organization_id": "org-001",
        "name": "Fixture Organization",
        "status": "active",
        "metadata": {},
        "external_ref": "org-001",
        "contact": {},
        "created_at": "2026-01-01T00:00:00Z",
    }
    repository.stores["store-001"] = {
        "id": "store-001",
        "store_id": "store-001",
        "organization_id": "org-001",
        "name": "Fixture PDD Store",
        "platform": "pdd",
        "status": "active",
        "metadata": {},
        "external_store_id": "store-001",
        "readiness_status": "blocked",
        "created_at": "2026-01-01T00:00:00Z",
    }
    return repository


def system_admin_session_fixture() -> SystemAdminSession:
    settings = Settings(environment="test", database_url=None)
    return system_admin_auth_fixture(settings).sessions[settings.system_admin_session]


def create_test_app(settings: Settings | None = None, **kwargs):
    from ecommerce_cs_agent.api.app import create_app

    settings = settings or Settings(environment="test", database_url=None)
    kwargs.setdefault("admin_auth_service_override", customer_admin_auth_fixture(settings))
    kwargs.setdefault("system_admin_auth_service_override", system_admin_auth_fixture(settings))
    return create_app(settings, **kwargs)
