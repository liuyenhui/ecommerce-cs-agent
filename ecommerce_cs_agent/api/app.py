from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from ecommerce_cs_agent.api.auth import (
    Principal,
    require_admin_session,
    require_agent_api,
    require_system_admin_session,
)
from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings, load_settings
from ecommerce_cs_agent.services.admin import admin_repository_for
from ecommerce_cs_agent.services.decision import DecisionService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="ecommerce-cs-agent", version="0.1.0")
    decisions = DecisionService(settings)
    admin_data = admin_repository_for(settings)

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
        return require_admin_session(
            settings,
            request.headers.get("Cookie"),
            request.headers.get("Authorization"),
        )

    def system_principal(request: Request) -> Principal:
        return require_system_admin_session(
            settings,
            request.headers.get("Cookie"),
            request.headers.get("Authorization"),
        )

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
        _require_fields(payload, ["request_id", "organization_id", "store_id", "platform", "message", "conversation", "mode"])
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
        if not _password_matches(
            payload.get("email"),
            payload.get("password"),
            settings.admin_initial_email,
            settings.admin_initial_password_hash,
        ):
            raise api_error(401, "unauthorized", "invalid admin credentials")
        response = JSONResponse(content=_admin_auth_payload())
        response.set_cookie("agent_admin_session", settings.admin_session, httponly=True, samesite="lax")
        return response

    @app.post("/v1/admin/auth/logout")
    def admin_logout(_principal: Principal = Depends(admin_principal)) -> JSONResponse:
        response = JSONResponse(content={"accepted": True})
        response.delete_cookie("agent_admin_session")
        return response

    @app.get("/v1/admin/auth/me")
    def get_admin_me(_principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {**_admin_auth_payload(), "active_organization_id": "org-001", "active_store_id": "store-001"}

    @app.get("/v1/admin/organizations")
    def list_admin_organizations(_principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {"items": [_organization()], "page": _page(1)}

    @app.get("/v1/admin/stores")
    def list_admin_stores(_principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {"items": [_store()], "page": _page(1)}

    @app.patch("/v1/admin/stores/{store_id}/settings")
    async def update_admin_store_settings(store_id: str, _request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {
            "store_id": store_id,
            "organization_id": "org-001",
            "settings": {},
            "updated_at": _now(),
            "audit_log_id": "audit-admin-001",
        }

    @app.get("/v1/admin/users")
    def list_admin_users(_principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {"items": [_admin_user()], "page": _page(1)}

    @app.post("/v1/admin/invitations")
    async def create_admin_invitation(_request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        payload = await _request.json()
        return {
            "invitation_id": "inv-001",
            "organization_id": "org-001",
            "email": payload.get("email", "invitee@example.test"),
            "roles": payload.get("roles", ["operator"]),
            "store_ids": payload.get("store_ids", []),
            "status": "pending",
            "expires_at": _now(),
            "audit_log_id": "audit-admin-001",
        }

    @app.patch("/v1/admin/users/{user_id}/roles")
    async def update_admin_user_roles(user_id: str, _request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        user = {**_admin_user(), "id": user_id}
        return {"user": user, "audit_log_id": "audit-admin-001"}

    @app.get("/v1/admin/audit-logs")
    def list_admin_audit_logs(_principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        items = admin_data.list_audit_logs("admin") or [_audit_log("admin_audit", "admin-001")]
        return {"items": items, "page": _page(len(items))}

    @app.post("/v1/product-content/products")
    async def upsert_product_content_product(request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        payload = await request.json()
        return admin_data.upsert_product(payload, _principal.user_id or "admin-001")

    @app.post("/v1/product-content/assets")
    async def create_product_asset(_request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {"asset_id": "asset-001", "status": "draft"}

    @app.post("/v1/product-content/assets/{asset_id}/markdown")
    async def create_product_asset_markdown(asset_id: str, _request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {"asset_id": asset_id, "markdown_id": "md-001", "conversion_status": "pending_review"}

    @app.post("/v1/product-content/knowledge-candidates/{candidate_id}/reviews")
    async def review_product_knowledge_candidate(candidate_id: str, _request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        payload = await _request.json()
        candidate = admin_data.review_knowledge_candidate(candidate_id, payload, _principal.user_id or "admin-001")
        return {
            "candidate_id": candidate["candidate_id"],
            "accepted": candidate["review_status"] == "accepted",
            "knowledge_entry_id": f"knowledge-{candidate_id}" if candidate["review_status"] == "accepted" else None,
        }

    @app.post("/v1/product-content/price-snapshots")
    async def create_product_price_snapshot(_request: Request, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return {"price_snapshot_id": "price-001", "status": "active"}

    @app.get("/v1/product-content/products/{product_id}/health")
    def get_product_content_health(product_id: str, _principal: Principal = Depends(admin_principal)) -> dict[str, Any]:
        return admin_data.product_health(product_id)

    @app.post("/v1/system-admin/auth/login")
    async def system_admin_login(request: Request) -> JSONResponse:
        payload = await request.json()
        if not _password_matches(
            payload.get("email"),
            payload.get("password"),
            settings.system_admin_initial_email,
            settings.system_admin_initial_password_hash,
        ):
            raise api_error(401, "unauthorized", "invalid system admin credentials")
        response = JSONResponse(content=_system_me_payload())
        response.set_cookie("agent_system_admin_session", settings.system_admin_session, httponly=True, samesite="lax")
        return response

    @app.post("/v1/system-admin/auth/logout")
    def system_admin_logout(_principal: Principal = Depends(system_principal)) -> JSONResponse:
        response = JSONResponse(content={"accepted": True})
        response.delete_cookie("agent_system_admin_session")
        return response

    @app.get("/v1/system-admin/auth/me")
    def get_system_admin_me(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return _system_me_payload()

    @app.get("/v1/system-admin/health")
    def get_system_health(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return admin_data.system_health()

    @app.get("/v1/system-admin/readiness/stores")
    def list_system_store_readiness(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        items = admin_data.store_readiness()
        return {"items": items, "page": _page(len(items))}

    @app.get("/v1/system-admin/users")
    def list_system_admin_users(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"items": [_system_user()], "page": _page(1)}

    @app.post("/v1/system-admin/users")
    async def create_system_admin_user(_request: Request, _principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"user": _system_user(), "accepted": True}

    @app.get("/v1/system-admin/organizations")
    def list_system_organizations(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"items": [_organization()], "page": _page(1)}

    @app.post("/v1/system-admin/organizations")
    async def create_system_organization(_request: Request, _principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"organization": _organization(), "accepted": True}

    @app.get("/v1/system-admin/stores")
    def list_system_stores(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"items": [_store()], "page": _page(1)}

    @app.post("/v1/system-admin/stores")
    async def create_system_store(_request: Request, _principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"store": _store(), "accepted": True}

    @app.get("/v1/system-admin/message-traces")
    def list_system_message_traces(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"items": [], "page": _page(0)}

    @app.get("/v1/system-admin/message-traces/{decision_id}")
    def get_system_message_trace(decision_id: str, _principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        response = decisions.get_trace(decision_id)
        if response is None:
            raise api_error(404, "not_found", "decision not found")
        return response

    @app.get("/v1/system-admin/tasks")
    def list_system_tasks(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"items": [], "page": _page(0)}

    @app.post("/v1/system-admin/tasks/{task_id}/retry")
    async def retry_system_task(task_id: str, _request: Request, _principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        return {"task_id": task_id, "accepted": True, "status": "queued"}

    @app.get("/v1/system-admin/audit-logs")
    def list_system_audit_logs(_principal: Principal = Depends(system_principal)) -> dict[str, Any]:
        items = admin_data.list_audit_logs("system") or [_audit_log("system_audit", "sysadmin-001")]
        return {"items": items, "page": _page(len(items))}

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


def _require_fields(payload: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise api_error(422, "validation_error", f"missing required fields: {', '.join(missing)}")


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


async def _not_implemented() -> None:
    raise api_error(501, "not_implemented", "this contract is reserved for a later phase")


def _password_matches(email: Any, password: Any, expected_email: str, stored_hash: str) -> bool:
    if email != expected_email or not isinstance(password, str):
        return False
    if stored_hash.startswith("plain:"):
        return password == stored_hash.removeprefix("plain:")
    return False


app = create_app()
