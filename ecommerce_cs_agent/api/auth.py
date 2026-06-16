from __future__ import annotations

from fastapi import HTTPException, status

from ecommerce_cs_agent.api.settings import Settings


def verify_bearer_token(
    settings: Settings,
    authorization: str | None,
) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authorization scheme",
        )

    if not settings.agent_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent api token is not configured",
        )

    if token != settings.agent_api_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid bearer token",
        )
