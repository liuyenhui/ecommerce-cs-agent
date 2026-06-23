from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings


OIDC_STATE_COOKIE = "agent_admin_oidc_state"


def build_authorization_redirect(settings: Settings) -> tuple[str, str]:
    _require_admin_oidc(settings)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    state_payload = {
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "iat": str(int(time.time())),
    }
    params = {
        "client_id": settings.admin_oidc_client_id,
        "redirect_uri": settings.admin_oidc_redirect_uri,
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_s256(code_verifier),
        "code_challenge_method": "S256",
    }
    redirect_url = f"{str(settings.admin_oidc_issuer).rstrip('/')}/oauth/authorize?{urlencode(params)}"
    return redirect_url, _seal_state(settings, state_payload)


def read_state_cookie(settings: Settings, cookie_value: str | None, state: str) -> dict[str, str]:
    if not cookie_value or not state:
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败")
    payload = _open_state(settings, cookie_value)
    if payload.get("state") != state:
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败")
    iat = int(payload.get("iat", "0"))
    if iat < int(time.time()) - 600:
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败")
    return payload


def exchange_code_for_userinfo(settings: Settings, code: str, state_payload: dict[str, str]) -> dict[str, Any]:
    _require_admin_oidc(settings)
    if not code:
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败")
    token_body = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": settings.admin_oidc_client_id,
            "client_secret": settings.admin_oidc_client_secret,
            "code": code,
            "redirect_uri": settings.admin_oidc_redirect_uri,
            "code_verifier": state_payload["code_verifier"],
        }
    ).encode("utf-8")
    token_response = _json_request(f"{str(settings.admin_oidc_issuer).rstrip('/')}/oauth/token", data=token_body)
    access_token = token_response.get("access_token")
    if not access_token:
        raise api_error(401, "oidc_exchange_failed", "OIDC token exchange failed")
    return _json_request(
        f"{str(settings.admin_oidc_issuer).rstrip('/')}/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def _require_admin_oidc(settings: Settings) -> None:
    if not settings.admin_oidc_enabled:
        raise api_error(503, "oidc_disabled", "OIDC 配置未启用")
    missing = [
        key for key, value in {
            "ADMIN_OIDC_ISSUER": settings.admin_oidc_issuer,
            "ADMIN_OIDC_CLIENT_ID": settings.admin_oidc_client_id,
            "ADMIN_OIDC_CLIENT_SECRET": settings.admin_oidc_client_secret,
            "ADMIN_OIDC_REDIRECT_URI": settings.admin_oidc_redirect_uri,
        }.items() if not value
    ]
    if missing:
        raise api_error(503, "oidc_misconfigured", f"OIDC 配置缺失: {', '.join(missing)}")


def _json_request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = UrlRequest(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    if data is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(request, timeout=5) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _seal_state(settings: Settings, payload: dict[str, str]) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(settings.admin_session.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _open_state(settings: Settings, cookie_value: str) -> dict[str, str]:
    try:
        body, signature = cookie_value.split(".", 1)
    except ValueError as exc:
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败") from exc
    expected = hmac.new(settings.admin_session.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败")
    padded = body + "=" * (-len(body) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise api_error(400, "oidc_state_pkce_failed", "OIDC state/PKCE 校验失败") from exc


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
