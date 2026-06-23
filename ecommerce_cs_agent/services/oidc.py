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
    _require_oidc(settings)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    payload = {
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "iat": str(int(time.time())),
    }
    params = {
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_s256(code_verifier),
        "code_challenge_method": "S256",
    }
    url = f"{settings.oidc_issuer.rstrip('/')}/oauth/authorize?{urlencode(params)}"
    return url, _seal_state(settings, payload)


def read_state_cookie(settings: Settings, cookie_value: str | None, state: str) -> dict[str, str]:
    if not cookie_value:
        raise api_error(400, "invalid_oidc_state", "missing OIDC state cookie")
    payload = _open_state(settings, cookie_value)
    if payload.get("state") != state:
        raise api_error(400, "invalid_oidc_state", "OIDC state mismatch")
    iat = int(payload.get("iat", "0"))
    if iat < int(time.time()) - 600:
        raise api_error(400, "invalid_oidc_state", "OIDC state expired")
    return payload


def exchange_code_for_userinfo(settings: Settings, code: str, state_payload: dict[str, str]) -> dict[str, Any]:
    _require_oidc(settings)
    token_body = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
            "code": code,
            "redirect_uri": settings.oidc_redirect_uri,
            "code_verifier": state_payload["code_verifier"],
        }
    ).encode("utf-8")
    token_response = _json_request(f"{settings.oidc_issuer.rstrip('/')}/oauth/token", data=token_body)
    access_token = token_response.get("access_token")
    if not access_token:
        raise api_error(401, "oidc_exchange_failed", "OIDC token response did not include access_token")
    return _json_request(
        f"{settings.oidc_issuer.rstrip('/')}/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def _json_request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = UrlRequest(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    if data is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(request, timeout=5) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _require_oidc(settings: Settings) -> None:
    if not settings.oidc_enabled:
        raise api_error(404, "oidc_disabled", "OIDC login is not enabled")
    missing = [
        key for key, value in {
            "OIDC_ISSUER": settings.oidc_issuer,
            "OIDC_CLIENT_ID": settings.oidc_client_id,
            "OIDC_CLIENT_SECRET": settings.oidc_client_secret,
            "OIDC_REDIRECT_URI": settings.oidc_redirect_uri,
        }.items() if not value
    ]
    if missing:
        raise api_error(500, "oidc_misconfigured", f"missing OIDC settings: {', '.join(missing)}")


def _seal_state(settings: Settings, payload: dict[str, str]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(settings.admin_session.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _open_state(settings: Settings, cookie_value: str) -> dict[str, str]:
    try:
        body, signature = cookie_value.split(".", 1)
    except ValueError as exc:
        raise api_error(400, "invalid_oidc_state", "invalid OIDC state cookie") from exc
    expected = hmac.new(settings.admin_session.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise api_error(400, "invalid_oidc_state", "invalid OIDC state signature")
    padded = body + "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
