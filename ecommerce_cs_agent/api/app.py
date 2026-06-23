from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ecommerce_cs_agent.api.auth import (
    Principal,
    require_agent_api,
)
from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings, load_settings
from ecommerce_cs_agent.core.passwords import password_matches
from ecommerce_cs_agent.services import oidc as oidc_service
from ecommerce_cs_agent.services.admin import admin_repository_for
from ecommerce_cs_agent.services.admin_auth import admin_auth_service_for, system_admin_auth_service_for
from ecommerce_cs_agent.services.decision import DecisionService
from ecommerce_cs_agent.services.object_storage import ObjectStorageUnavailable, ObjectStorageValidationError
from ecommerce_cs_agent.services.product_analysis import product_document_analyzer_for
from ecommerce_cs_agent.services.system_admin import system_admin_repository_for


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="ecommerce-cs-agent", version="0.1.0")
    decisions = DecisionService(settings)
    admin_data = admin_repository_for(settings)
    product_analyzer = product_document_analyzer_for(settings)
    admin_auth = admin_auth_service_for(settings)
    system_admin_auth = system_admin_auth_service_for(settings)
    system_admin_data = system_admin_repository_for(settings)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(422, "validation_error", "request validation failed", {"details": exc.errors()})

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return _error_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        if hasattr(exc, "status_code") and hasattr(exc, "detail"):
            detail = getattr(exc, "detail")
            if isinstance(detail, dict) and "error" in detail:
                return JSONResponse(status_code=getattr(exc, "status_code"), content=detail)
        return _error_response(500, "internal_error", "unexpected server error")

    def agent_principal(request: Request) -> Principal:
        return require_agent_api(settings, request.headers.get("Authorization"))

    def admin_principal(request: Request) -> Principal:
        principal, _session = admin_auth.require_session(request.headers.get("Cookie"), request.headers.get("Authorization"))
        return principal

    def admin_session(request: Request) -> Any:
        _principal, session = admin_auth.require_session(request.headers.get("Cookie"), request.headers.get("Authorization"))
        return session

    def system_principal(request: Request) -> Principal:
        principal, _session = system_admin_auth.require_session(request.headers.get("Cookie"), request.headers.get("Authorization"))
        return principal

    def system_session(request: Request) -> Any:
        _principal, session = system_admin_auth.require_session(request.headers.get("Cookie"), request.headers.get("Authorization"))
        return session

    @app.get("/")
    def landing() -> dict[str, Any]:
        return {"service": settings.service_name, "login": "/login"}

    @app.get("/login")
    def login_page() -> dict[str, Any]:
        return {"service": settings.service_name, "auth": "agent-admin"}

    @app.get("/admin")
    def admin_shell(request: Request) -> Any:
        cookie = request.headers.get("Cookie")
        if not cookie or f"agent_admin_session={settings.admin_session}" not in cookie:
            return RedirectResponse("/login", status_code=307)
        return {"service": "ecommerce-cs-agent-admin", "status": "ok"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "environment": settings.environment,
        }

    @app.post("/v1/reply-decisions")
    async def create_reply_decision(
        request: Request,
        _principal: Principal = Depends(agent_principal),
    ) -> dict[str, Any]:
        payload = await request.json()
        _require_fields(payload, ["request_id", "platform", "message", "conversation", "mode"])
        payload = _normalize_reply_decision_payload(payload)
        return decisions.create_reply_decision(payload)

    def context_endpoint(context_type: str) -> Callable[..., Any]:
        async def refill(
            decision_id: str,
            request: Request,
            _principal: Principal = Depends(agent_principal),
        ) -> dict[str, Any]:
            payload = await request.json()
            _require_fields(payload, ["context_request_id"])
            try:
                response = decisions.refill_context(decision_id, context_type, payload)
            except PermissionError as exc:
                raise api_error(403, "forbidden", str(exc)) from exc
            except FileExistsError as exc:
                raise api_error(409, "idempotency_conflict", str(exc)) from exc
            except ValueError as exc:
                raise api_error(422, "validation_error", str(exc)) from exc
            if response is None:
                raise api_error(404, "not_found", "decision not found")
            return response

        return refill

    app.post("/v1/reply-decisions/{decision_id}/contexts/products")(context_endpoint("products"))
    app.post("/v1/reply-decisions/{decision_id}/contexts/orders")(context_endpoint("orders"))
    app.post("/v1/reply-decisions/{decision_id}/contexts/logistics")(context_endpoint("logistics"))
    app.post("/v1/reply-decisions/{decision_id}/contexts/rules")(context_endpoint("rules"))

    @app.post("/v1/reply-decisions/{decision_id}/actions/results")
    async def submit_action_result(
        decision_id: str,
        request: Request,
        _principal: Principal = Depends(agent_principal),
    ) -> dict[str, Any]:
        payload = await request.json()
        _require_fields(payload, ["action_id", "action_type", "idempotency_key", "status", "executed_at"])
        try:
            response = decisions.submit_action_result(decision_id, payload)
        except PermissionError as exc:
            raise api_error(403, "forbidden", str(exc)) from exc
        except FileExistsError as exc:
            raise api_error(409, "idempotency_conflict", str(exc)) from exc
        except ValueError as exc:
            raise api_error(422, "validation_error", str(exc)) from exc
        if response is None:
            raise api_error(404, "not_found", "decision not found")
        return response

    @app.post("/v1/feedback/human-replies")
    async def submit_human_reply_feedback(
        request: Request,
        _principal: Principal = Depends(agent_principal),
    ) -> dict[str, Any]:
        payload = await request.json()
        _require_fields(payload, ["decision_id", "human_reply", "used_candidate", "resolution_status"])
        response = decisions.submit_feedback(payload)
        if response is None:
            raise api_error(404, "not_found", "decision not found")
        return response

    @app.get("/v1/message-traces/{decision_id}")
    def get_message_trace(
        decision_id: str,
        _principal: Principal = Depends(admin_principal),
    ) -> dict[str, Any]:
        response = decisions.get_trace(decision_id)
        if response is None:
            raise api_error(404, "not_found", "decision not found")
        return response

    @app.post("/v1/admin/auth/login")
    async def admin_login(request: Request) -> JSONResponse:
        payload = await request.json()
        content, token = admin_auth.login(payload)
        response = JSONResponse(content=content)
        response.set_cookie("agent_admin_session", token, httponly=True, samesite="lax")
        return response

    @app.post("/v1/admin/auth/logout")
    def admin_logout(request: Request, _principal: Principal = Depends(admin_principal)) -> Response:
        cookies = _parse_cookie(request.headers.get("Cookie"))
        admin_auth.logout(cookies.get("agent_admin_session", ""))
        response = Response(status_code=204)
        response.delete_cookie("agent_admin_session")
        return response

    @app.get("/v1/admin/auth/me")
    def get_admin_me(session: Any = Depends(admin_session)) -> dict[str, Any]:
        return admin_auth.me(session)

    @app.get("/v1/admin/auth/oidc/start")
    def admin_oidc_start() -> RedirectResponse:
        redirect_url, state_cookie = oidc_service.build_authorization_redirect(settings)
        response = RedirectResponse(redirect_url, status_code=307)
        response.set_cookie(
            oidc_service.OIDC_STATE_COOKIE,
            state_cookie,
            httponly=True,
            samesite="lax",
            max_age=600,
        )
        return response

    @app.get("/v1/admin/auth/oidc/callback")
    def admin_oidc_callback(request: Request) -> RedirectResponse:
        try:
            state_payload = oidc_service.read_state_cookie(
                settings,
                request.cookies.get(oidc_service.OIDC_STATE_COOKIE),
                request.query_params.get("state") or "",
            )
            profile = oidc_service.exchange_code_for_userinfo(
                settings,
                request.query_params.get("code") or "",
                state_payload,
            )
            _content, token = admin_auth.login_oidc(profile)
        except HTTPException as exc:
            error_code = _http_error_code(exc)
            if error_code in {
                "oidc_state_pkce_failed",
                "oidc_unbound_account",
                "oidc_disabled",
                "oidc_misconfigured",
                "oidc_exchange_failed",
            }:
                response = RedirectResponse(f"/login?error={error_code}", status_code=307)
                response.delete_cookie(oidc_service.OIDC_STATE_COOKIE)
                return response
            raise
        response = RedirectResponse("/admin", status_code=307)
        response.set_cookie("agent_admin_session", token, httponly=True, samesite="lax")
        response.delete_cookie(oidc_service.OIDC_STATE_COOKIE)
        return response

    @app.post("/v1/admin/auth/oidc/link")
    async def admin_oidc_link(request: Request, session: Any = Depends(admin_session)) -> JSONResponse:
        payload = await request.json()
        _require_fields(payload, ["code", "state"])
        state_payload = oidc_service.read_state_cookie(
            settings,
            request.cookies.get(oidc_service.OIDC_STATE_COOKIE),
            str(payload.get("state") or ""),
        )
        profile = oidc_service.exchange_code_for_userinfo(settings, str(payload.get("code") or ""), state_payload)
        response = JSONResponse(content=admin_auth.link_oidc(session, profile))
        response.delete_cookie(oidc_service.OIDC_STATE_COOKIE)
        return response

    @app.get("/v1/admin/organizations")
    def list_admin_organizations(session: Any = Depends(admin_session)) -> dict[str, Any]:
        return admin_auth.list_organizations(session)

    @app.get("/v1/admin/stores")
    def list_admin_stores(request: Request, session: Any = Depends(admin_session)) -> dict[str, Any]:
        return admin_auth.list_stores(session, request.query_params.get("organization_id"))

    @app.patch("/v1/admin/stores/{store_id}/settings")
    async def update_admin_store_settings(store_id: str, request: Request, session: Any = Depends(admin_session)) -> dict[str, Any]:
        payload = await request.json()
        return admin_auth.update_store_settings(session, store_id, payload)

    @app.get("/v1/admin/users")
    def list_admin_users(request: Request, session: Any = Depends(admin_session)) -> dict[str, Any]:
        return admin_auth.list_users(session, request.query_params.get("organization_id"))

    @app.post("/v1/admin/invitations")
    async def create_admin_invitation(request: Request, session: Any = Depends(admin_session)) -> JSONResponse:
        payload = await request.json()
        return JSONResponse(status_code=201, content=admin_auth.create_invitation(session, payload))

    @app.patch("/v1/admin/users/{user_id}/roles")
    async def update_admin_user_roles(user_id: str, request: Request, session: Any = Depends(admin_session)) -> dict[str, Any]:
        payload = await request.json()
        return admin_auth.update_roles(session, user_id, payload)

    @app.get("/v1/admin/audit-logs")
    def list_admin_audit_logs(request: Request, session: Any = Depends(admin_session)) -> dict[str, Any]:
        auth_logs = admin_auth.list_audit_logs(session, request.query_params.get("organization_id"))
        repo_logs = admin_data.list_audit_logs("admin")
        if repo_logs:
            auth_logs["items"].extend(repo_logs)
            auth_logs["page"] = _page(len(auth_logs["items"]))
            auth_logs["page_info"] = _page(len(auth_logs["items"]))
        return auth_logs

    @app.post("/v1/product-content/products")
    async def upsert_product_content_product(request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await request.json()
        return JSONResponse(status_code=201, content=admin_data.upsert_product(payload, _principal.user_id or "admin-001"))

    @app.get("/v1/product-content/products")
    def list_product_content_products(request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        organization_id = _principal.organization_id or "org-001"
        store_id = request.query_params.get("store_id") or _principal.store_id or "store-001"
        if _principal.store_id and store_id != _principal.store_id:
            raise api_error(403, "forbidden", "store is not available for current admin session")
        page = _positive_int(request.query_params.get("page"), default=1, maximum=10_000)
        page_size = _positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return admin_data.list_products(organization_id, store_id, page=page, page_size=page_size)

    @app.post("/v1/product-content/product-import-drafts")
    async def create_product_import_draft(request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await request.json()
        _require_fields(payload, ["file_name", "mime_type", "content_base64", "idempotency_key"])
        store_id = str(payload.get("store_id") or _principal.store_id or "store-001")
        if _principal.store_id and store_id != _principal.store_id:
            raise api_error(403, "forbidden", "store is not available for current admin session")
        try:
            text = _decode_upload_text(payload)
            analysis = product_analyzer.analyze(
                text=text,
                file_name=str(payload["file_name"]),
                mime_type=str(payload["mime_type"]),
            )
            draft = admin_data.create_product_import_draft(
                {
                    **payload,
                    **analysis,
                    "organization_id": _principal.organization_id or "org-001",
                    "store_id": store_id,
                },
                _principal.user_id or "admin-001",
            )
        except ObjectStorageValidationError as exc:
            raise api_error(422, "object_storage_error", str(exc)) from exc
        except ObjectStorageUnavailable as exc:
            raise api_error(503, "object_storage_unavailable", "object storage is unavailable") from exc
        return JSONResponse(status_code=201, content=draft)

    @app.post("/v1/product-content/product-import-drafts/{draft_id}/confirm")
    async def confirm_product_import_draft(draft_id: str, request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await request.json()
        _require_fields(payload, ["idempotency_key", "draft_product"])
        try:
            response = admin_data.confirm_product_import_draft(draft_id, payload, _principal.user_id or "admin-001")
        except KeyError as exc:
            raise api_error(404, "not_found", "draft not found") from exc
        status_code = 200 if response.pop("replayed", False) else 201
        return JSONResponse(status_code=status_code, content=response)

    @app.post("/v1/product-content/assets")
    async def create_product_asset(request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await request.json()
        try:
            asset = admin_data.create_asset(payload, _principal.user_id or "admin-001")
        except ObjectStorageValidationError as exc:
            raise api_error(422, "object_storage_error", str(exc)) from exc
        except ObjectStorageUnavailable as exc:
            raise api_error(503, "object_storage_unavailable", "object storage is unavailable") from exc
        return JSONResponse(status_code=201, content={
            "asset_id": asset["asset_id"],
            "product_id": asset["product_id"],
            "asset_type": asset["asset_type"],
            "review_status": asset["review_status"],
            "object_key": asset.get("file_ref"),
            "object_hash": asset.get("file_hash"),
            "mime_type": asset.get("mime_type"),
            "size_bytes": asset.get("size_bytes"),
            "storage_status": asset.get("storage_status"),
        })

    @app.post("/v1/product-content/assets/{asset_id}/markdown")
    async def create_product_asset_markdown(asset_id: str, request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await request.json()
        try:
            markdown = admin_data.create_asset_markdown(asset_id, payload, _principal.user_id or "admin-001")
        except KeyError as exc:
            raise api_error(404, "not_found", "asset not found") from exc
        return JSONResponse(status_code=201, content={
            "asset_id": markdown["asset_id"],
            "markdown_id": markdown["markdown_id"],
            "conversion_status": markdown["conversion_status"],
            "candidate_ids": markdown["candidate_ids"],
        })

    @app.post("/v1/product-content/knowledge-candidates/{candidate_id}/reviews")
    async def review_product_knowledge_candidate(candidate_id: str, _request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await _request.json()
        candidate = admin_data.review_knowledge_candidate(candidate_id, payload, _principal.user_id or "admin-001")
        return JSONResponse(status_code=201, content={
            "review_id": f"review-{candidate_id}",
            "candidate_id": candidate["candidate_id"],
            "action": payload.get("action", "approve" if candidate["review_status"] == "accepted" else "reject"),
            "accepted": candidate["review_status"] == "accepted",
            "knowledge_entry_id": candidate.get("knowledge_entry_id") or (f"knowledge-{candidate_id}" if candidate["review_status"] == "accepted" else None),
            "reviewed_at": candidate.get("reviewed_at") or _now(),
        })

    @app.post("/v1/product-content/price-snapshots")
    async def create_product_price_snapshot(_request: Request, _principal: Principal = Depends(admin_principal)) -> JSONResponse:
        payload = await _request.json()
        snapshot = admin_data.create_price_snapshot(payload, _principal.user_id or "admin-001")
        return JSONResponse(status_code=201, content=snapshot)

    @app.get("/v1/product-content/products/{product_id}/health")
    def get_product_content_health(product_id: str, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return admin_data.product_health(product_id)

    @app.post("/v1/system-admin/auth/login")
    async def system_admin_login(request: Request) -> JSONResponse:
        payload = await request.json()
        content, token = system_admin_auth.login(payload)
        response = JSONResponse(content=content)
        response.set_cookie("agent_system_admin_session", token, httponly=True, samesite="lax")
        return response

    @app.post("/v1/system-admin/auth/logout")
    def system_admin_logout(request: Request, _principal: Principal = Depends(system_principal)) -> Response:
        cookies = _parse_cookie(request.headers.get("Cookie"))
        system_admin_auth.logout(cookies.get("agent_system_admin_session", ""))
        response = Response(status_code=204)
        response.delete_cookie("agent_system_admin_session")
        return response

    @app.get("/v1/system-admin/auth/me")
    def get_system_admin_me(session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_auth.me(session)

    @app.get("/v1/system-admin/health")
    def get_system_health(session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.system_health(session)

    @app.get("/v1/system-admin/readiness/stores")
    def list_system_store_readiness(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.store_readiness(session, _query_filters(request))

    @app.get("/v1/system-admin/users")
    def list_system_admin_users(session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.list_users(session)

    @app.post("/v1/system-admin/users")
    async def create_system_admin_user(_request: Request, session: Any = Depends(system_session)) -> JSONResponse:
        payload = await _request.json()
        _require_fields(payload, ["email", "display_name", "roles", "reason"])
        return JSONResponse(status_code=201, content=system_admin_data.create_user(session, payload))

    @app.get("/v1/system-admin/organizations")
    def list_system_organizations(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.list_organizations(session, _query_filters(request))

    @app.post("/v1/system-admin/organizations")
    async def create_system_organization(_request: Request, session: Any = Depends(system_session)) -> JSONResponse:
        payload = await _request.json()
        _require_fields(payload, ["name", "status", "reason"])
        return JSONResponse(status_code=201, content=system_admin_data.create_organization(session, payload))

    @app.get("/v1/system-admin/stores")
    def list_system_stores(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.list_stores(session, _query_filters(request))

    @app.post("/v1/system-admin/stores")
    async def create_system_store(_request: Request, session: Any = Depends(system_session)) -> JSONResponse:
        payload = await _request.json()
        _require_fields(payload, ["organization_id", "name", "platform", "status", "reason"])
        return JSONResponse(status_code=201, content=system_admin_data.create_store(session, payload))

    @app.get("/v1/system-admin/message-traces")
    def list_system_message_traces(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.list_message_traces(session, _query_filters(request))

    @app.get("/v1/system-admin/message-traces/{decision_id}")
    def get_system_message_trace(decision_id: str, request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        response = system_admin_data.get_message_trace(session, decision_id, _query_filters(request))
        if response is None:
            raise api_error(404, "not_found", "decision not found")
        return response

    @app.get("/v1/system-admin/tasks")
    def list_system_tasks(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.list_tasks(session, _query_filters(request))

    @app.post("/v1/system-admin/tasks/{task_id}/retry")
    async def retry_system_task(task_id: str, _request: Request, session: Any = Depends(system_session)) -> JSONResponse:
        payload = await _request.json()
        _require_fields(payload, ["idempotency_key", "reason"])
        return JSONResponse(status_code=202, content=system_admin_data.retry_task(session, task_id, payload))

    @app.get("/v1/system-admin/audit-logs")
    def list_system_audit_logs(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        return system_admin_data.list_audit_logs(session, _query_filters(request))

    for method, path in [
        ("POST", "/v1/events/messages"),
        ("GET", "/v1/tasks/{task_id}"),
        ("POST", "/v1/webhook-subscriptions"),
        ("GET", "/v1/webhook-subscriptions"),
        ("PATCH", "/v1/webhook-subscriptions/{subscription_id}"),
        ("DELETE", "/v1/webhook-subscriptions/{subscription_id}"),
        ("GET", "/v1/admin/connectors"),
        ("POST", "/v1/admin/connectors"),
        ("PATCH", "/v1/admin/connectors/{connector_id}"),
        ("GET", "/v1/admin/rules/rule-sets"),
        ("POST", "/v1/admin/rules/rule-sets"),
        ("POST", "/v1/admin/rules/rule-sets/{rule_set_id}/dry-runs"),
        ("POST", "/v1/admin/rules/rule-sets/{rule_set_id}/releases"),
    ]:
        app.add_api_route(path, _not_implemented, methods=[method])

    return app


def _error_response(status_code: int, code: str, message: str, extra: dict[str, Any] | None = None) -> JSONResponse:
    content: dict[str, Any] = {"detail": message, "error": {"code": code, "message": message}}
    if extra:
        content["error"].update(extra)
    return JSONResponse(status_code=status_code, content=content)


def _http_error_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        error = exc.detail.get("error")
        if isinstance(error, dict) and error.get("code"):
            return str(error["code"])
    return "http_error"


def _require_fields(payload: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise api_error(422, "validation_error", f"missing required fields: {', '.join(missing)}")


def _positive_int(raw: str | None, *, default: int, maximum: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise api_error(422, "validation_error", "invalid pagination parameter") from exc
    if value < 1:
        raise api_error(422, "validation_error", "pagination parameter must be positive")
    return min(value, maximum)


def _decode_upload_text(payload: dict[str, Any]) -> str:
    try:
        content = base64.b64decode(str(payload.get("content_base64", "")), validate=True)
    except ValueError as exc:
        raise api_error(422, "validation_error", "invalid content_base64") from exc
    if not content:
        raise api_error(422, "validation_error", "uploaded content is empty")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="ignore")


def _normalize_reply_decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    external_store_id = normalized.get("external_store_id") or normalized.get("store_id")
    if not external_store_id:
        raise api_error(422, "validation_error", "missing required fields: external_store_id")

    platform_account_ref = normalized.get("platform_account_ref") or normalized.get("platform_account_id")
    tenant_ref = normalized.get("tenant_id") or normalized.get("organization_id")
    tenant_id = str(tenant_ref) if tenant_ref is not None else str(platform_account_ref or external_store_id)
    if tenant_ref is None and not tenant_id.startswith("tenant-"):
        tenant_id = f"tenant-{tenant_id}"

    normalized.setdefault("tenant_id", tenant_id)
    # Existing persistence and Admin surfaces still use organization_id internally.
    normalized.setdefault("organization_id", tenant_id)
    normalized.setdefault("store_id", str(external_store_id))
    normalized.setdefault("external_store_id", str(external_store_id))
    return normalized


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _admin_user() -> dict[str, Any]:
    return {
        "id": "admin-001",
        "email": "admin@example.test",
        "name": "Customer Admin",
        "role": "owner",
        "status": "active",
    }


def _system_user() -> dict[str, Any]:
    return {
        "id": "sysadmin-001",
        "email": "system-admin@example.test",
        "name": "System Admin",
        "role": "super_admin",
        "status": "active",
    }


def _organization() -> dict[str, Any]:
    return {"id": "org-001", "name": "Demo Organization", "status": "active", "metadata": {}}


def _store() -> dict[str, Any]:
    return {
        "id": "store-001",
        "organization_id": "org-001",
        "name": "Demo PDD Store",
        "platform": "pdd",
        "status": "active",
        "metadata": {},
    }


def _admin_auth_payload() -> dict[str, Any]:
    return {"user": _admin_user(), "organizations": [_organization()], "stores": [_store()]}


def _system_me_payload() -> dict[str, Any]:
    return {"user": _system_user(), "permissions": ["system:read", "system:write"]}


def _audit_log(log_type: str, actor_id: str) -> dict[str, Any]:
    return {
        "id": f"audit-{log_type}-001",
        "actor_id": actor_id,
        "action": "read",
        "object_type": log_type,
        "object_id": "local",
        "created_at": _now(),
        "metadata": {},
    }


def _page(total: int) -> dict[str, int]:
    return {"page": 1, "page_size": 50, "total": total}


def _query_filters(request: Request) -> dict[str, Any]:
    return {key: value for key, value in request.query_params.items() if value not in {"", None}}


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


async def _not_implemented() -> None:
    raise api_error(501, "not_implemented", "this contract is reserved for a later phase")


def _password_matches(email: Any, password: Any, expected_email: str, stored_hash: str) -> bool:
    return password_matches(email, password, expected_email, stored_hash)


app = create_app()
