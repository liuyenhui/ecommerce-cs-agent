from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header

from ecommerce_cs_agent.api.auth import verify_bearer_token
from ecommerce_cs_agent.api.decisions import create_reply_decision, refill_context
from ecommerce_cs_agent.api.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    app = FastAPI(title="Ecommerce Customer Service Agent API")

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        verify_bearer_token(app_settings, authorization)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "ecommerce-cs-agent-api",
            "environment": app_settings.app_env,
        }

    @app.post("/v1/reply-decisions", dependencies=[Depends(require_auth)])
    def reply_decisions(request: dict[str, Any]) -> dict[str, Any]:
        return create_reply_decision(request)

    @app.post(
        "/v1/reply-decisions/{decision_id}/contexts/{context_type}",
        dependencies=[Depends(require_auth)],
    )
    def refill_decision_context(
        decision_id: str,
        context_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return refill_context(
            decision_id=decision_id,
            context_type=context_type,
            payload=payload,
        )

    return app


app = create_app()
