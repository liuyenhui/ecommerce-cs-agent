from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings


@dataclass(frozen=True)
class Principal:
    kind: str
    user_id: str | None
    organization_id: str | None
    store_id: str | None
    role: str


def require_agent_api(
    settings: Settings,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Principal:
    expected = f"Bearer {settings.agent_api_token}"
    if not authorization:
        raise api_error(401, "unauthorized", "missing bearer token")
    if authorization != expected:
        raise api_error(401, "unauthorized", "invalid bearer token")
    return Principal("external_api", None, None, None, "external")


def require_admin_session(
    settings: Settings,
    cookie: Annotated[str | None, Header(alias="Cookie")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Principal:
    if authorization and authorization.startswith("Bearer "):
        raise api_error(403, "forbidden", "external API token cannot access customer admin")
    cookies = _parse_cookie(cookie)
    if cookies.get("agent_admin_session") != settings.admin_session:
        raise api_error(401, "unauthorized", "missing customer admin session")
    return Principal("customer_admin", "admin-001", "org-001", "store-001", "owner")


def require_system_admin_session(
    settings: Settings,
    cookie: Annotated[str | None, Header(alias="Cookie")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Principal:
    if authorization and authorization.startswith("Bearer "):
        raise api_error(403, "forbidden", "external API token cannot access system admin")
    cookies = _parse_cookie(cookie)
    if "agent_admin_session" in cookies and "agent_system_admin_session" not in cookies:
        raise api_error(403, "forbidden", "customer admin session cannot access system admin")
    if cookies.get("agent_system_admin_session") != settings.system_admin_session:
        raise api_error(401, "unauthorized", "missing system admin session")
    return Principal("system_admin", "sysadmin-001", None, None, "super_admin")


def _parse_cookie(cookie: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not cookie:
        return parsed
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed
