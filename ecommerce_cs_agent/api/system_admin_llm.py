from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.services.llm_governance import LlmGovernanceRepository


def _canonical_uuid(value: Any) -> UUID:
    if not isinstance(value, str):
        raise ValueError("must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("must be a canonical UUID") from None
    if str(parsed) != value:
        raise ValueError("must be a canonical UUID")
    return parsed


def _rfc3339_datetime(value: Any) -> Any:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("must be an RFC3339 timestamp with timezone")
    return value


CanonicalUUID = Annotated[UUID, BeforeValidator(_canonical_uuid)]
ResourceId = Annotated[UUID, BeforeValidator(_canonical_uuid), Path()]
Rfc3339DateTime = Annotated[datetime, BeforeValidator(_rfc3339_datetime)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class AuditWrite(StrictRequest):
    reason: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f]+$")


class SecretReference(StrictRequest):
    namespace: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9._-]+$")
    key: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9._-]+$")


class ProviderCreateRequest(AuditWrite):
    name: str = Field(min_length=1, max_length=128)
    provider_type: Literal["openai", "openai_compatible", "anthropic", "azure_openai"]
    base_url: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretReference
    enabled: bool = True


class ProviderUpdateRequest(AuditWrite):
    expected_revision: int = Field(ge=1, le=2_147_483_647)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ProviderUpdateRequest":
        if self.name is None and self.enabled is None:
            raise ValueError("name or enabled is required")
        return self


class ConnectionTestRequest(AuditWrite):
    config_version_id: CanonicalUUID
    timeout_seconds: int = Field(default=20, ge=1, le=20)
    max_tokens: int = Field(default=256, ge=1, le=256)


class DraftCreateRequest(AuditWrite):
    organization_id: CanonicalUUID
    description: str | None = Field(default=None, max_length=512)


class ScenarioRoute(StrictRequest):
    scenario: str = Field(min_length=1, max_length=64)
    primary_provider_config_id: CanonicalUUID
    primary_model: str = Field(min_length=1, max_length=128)
    fallback_provider_config_id: CanonicalUUID | None = None
    fallback_model: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(ge=1, le=1_000_000)
    timeout_seconds: int = Field(ge=1, le=300)
    max_retries: int = Field(ge=0, le=20)
    circuit_breaker_threshold: int = Field(ge=1, le=10_000)
    recovery_probe_seconds: int = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def validate_fallback_pair(self) -> "ScenarioRoute":
        if (self.fallback_provider_config_id is None) != (self.fallback_model is None):
            raise ValueError("fallback provider and model must be supplied together")
        return self


class RouteReplaceRequest(AuditWrite):
    expected_revision: int = Field(ge=1, le=2_147_483_647)
    routes: list[ScenarioRoute] = Field(min_length=1, max_length=32)


class RevisionWriteRequest(AuditWrite):
    expected_revision: int = Field(ge=1, le=2_147_483_647)


class SubmitPublishRequest(RevisionWriteRequest):
    evaluation_run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_:-]+$")


class RollbackRequest(AuditWrite):
    pass


class UsageFilters(StrictRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=False)
    start_at: Rfc3339DateTime | None = None
    end_at: Rfc3339DateTime | None = None
    provider_config_id: CanonicalUUID | None = None
    model: str | None = Field(default=None, min_length=1, max_length=128)
    scenario: str | None = Field(default=None, min_length=1, max_length=64)
    organization_id: CanonicalUUID | None = None
    store_id: CanonicalUUID | None = None
    currency: Literal["CNY", "USD"] | None = None
    status: Literal["succeeded", "failed", "timed_out", "rejected"] | None = None
    route_role: Literal["primary", "fallback"] | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "UsageFilters":
        for field in ("start_at", "end_at"):
            value = getattr(self, field)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field} must include a timezone")
        if self.start_at is not None and self.end_at is not None and self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at")
        return self

    def service_filters(self) -> dict[str, Any]:
        values = self.model_dump(exclude_none=True)
        for field in ("start_at", "end_at"):
            if field in values:
                values[field] = values[field].astimezone(timezone.utc).isoformat()
        for field in ("provider_config_id", "organization_id", "store_id"):
            if field in values:
                values[field] = str(values[field])
        return values


class UsageBreakdownFilters(UsageFilters):
    group_by: Literal["provider", "model", "scenario", "organization", "store", "status", "error_code"]


class InvocationFilters(UsageFilters):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = Field(default=None, min_length=1, max_length=1024)


class ConfigVersionsQuery(StrictRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, strict=False)
    organization_id: CanonicalUUID
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=1024)


class ReleaseRecordsQuery(ConfigVersionsQuery):
    pass

def _query_model(request: Request, model: type[StrictRequest]) -> StrictRequest:
    try:
        return model.model_validate(dict(request.query_params))
    except ValidationError as exc:
        details = [
            {"type": item.get("type"), "loc": list(item.get("loc", ())), "msg": item.get("msg")}
            for item in exc.errors()
        ]
        raise api_error(422, "validation_error", f"invalid query parameters: {details}") from None


def _version_response(version: dict[str, Any]) -> dict[str, Any]:
    response = dict(version)
    release_id = response.get("release_record_id")
    response["release_record"] = (
        {
            "release_record_id": release_id,
            "status": response.get("release_status"),
            "rollback_of_version_id": response.get("rollback_of_version_id"),
        }
        if release_id
        else None
    )
    evaluation_id = response.get("evaluation_run_id")
    response["evaluation"] = {"evaluation_run_id": evaluation_id} if evaluation_id else None
    return response


def register_system_admin_llm_routes(
    app: FastAPI,
    repository: LlmGovernanceRepository,
    system_session: Callable[..., Any],
) -> None:
    @app.get("/v1/system-admin/llm/providers")
    def list_llm_providers(session: Any = Depends(system_session)) -> dict[str, Any]:
        return {"items": repository.list_providers(session)}

    @app.post("/v1/system-admin/llm/providers")
    def create_llm_provider(payload: ProviderCreateRequest, session: Any = Depends(system_session)) -> JSONResponse:
        result = repository.create_provider(session, payload.model_dump(mode="json"))
        return JSONResponse(status_code=201, content=result)

    @app.patch("/v1/system-admin/llm/providers/{provider_id}")
    def update_llm_provider(provider_id: ResourceId, payload: ProviderUpdateRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        body = payload.model_dump(mode="json", exclude_none=True)
        expected_revision = body.pop("expected_revision")
        return repository.update_provider(session, str(provider_id), body, expected_revision=expected_revision)

    @app.post("/v1/system-admin/llm/providers/{provider_id}/connection-tests")
    def test_llm_provider_connection(provider_id: ResourceId, payload: ConnectionTestRequest, session: Any = Depends(system_session)) -> JSONResponse:
        result = repository.test_connection(session, str(provider_id), payload.model_dump(mode="json"))
        return JSONResponse(status_code=202, content=result)

    @app.get("/v1/system-admin/llm/config-versions")
    def list_llm_config_versions(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        query = _query_model(request, ConfigVersionsQuery)
        assert isinstance(query, ConfigVersionsQuery)
        organization_id = str(query.organization_id)
        page = repository.list_versions_page(session, organization_id, limit=query.limit, cursor=query.cursor)
        return {"items": [_version_response(item) for item in page["items"]], "page_info": page["page_info"]}

    @app.get("/v1/system-admin/llm/releases")
    def list_llm_release_records(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        query = _query_model(request, ReleaseRecordsQuery)
        assert isinstance(query, ReleaseRecordsQuery)
        return repository.list_release_records_page(session, str(query.organization_id), limit=query.limit, cursor=query.cursor)

    @app.get("/v1/system-admin/llm/config-versions/{version_id}")
    def get_llm_config_version(version_id: ResourceId, session: Any = Depends(system_session)) -> dict[str, Any]:
        return _version_response(repository.get_version(session, str(version_id)))

    @app.post("/v1/system-admin/llm/config-versions/drafts")
    def create_llm_config_draft(payload: DraftCreateRequest, session: Any = Depends(system_session)) -> JSONResponse:
        result = _version_response(repository.create_draft(session, payload.model_dump(mode="json", exclude_none=True)))
        return JSONResponse(status_code=201, content=result)

    @app.put("/v1/system-admin/llm/config-versions/{version_id}/routes")
    @app.patch("/v1/system-admin/llm/config-versions/{version_id}/routes")
    def replace_llm_config_routes(version_id: ResourceId, payload: RouteReplaceRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        body = payload.model_dump(mode="json")
        expected_revision = body.pop("expected_revision")
        routes = body.pop("routes")
        return _version_response(repository.replace_routes(session, str(version_id), routes, expected_revision=expected_revision, payload=body))

    @app.post("/v1/system-admin/llm/config-versions/{version_id}/validate")
    def validate_llm_config(version_id: ResourceId, payload: RevisionWriteRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return _version_response(repository.validate_draft(session, str(version_id), payload.model_dump(mode="json")))

    @app.post("/v1/system-admin/llm/config-versions/{version_id}/submit-publish")
    def submit_llm_config_publish(version_id: ResourceId, payload: SubmitPublishRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return _version_response(repository.submit_publish(session, str(version_id), payload.model_dump(mode="json")))

    @app.post("/v1/system-admin/llm/config-versions/{version_id}/publish")
    def publish_llm_config(version_id: ResourceId, payload: RevisionWriteRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return _version_response(repository.publish(session, str(version_id), payload.model_dump(mode="json")))

    @app.post("/v1/system-admin/llm/config-versions/{version_id}/rollback")
    def rollback_llm_config(version_id: ResourceId, payload: RollbackRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return _version_response(repository.rollback(session, str(version_id), payload.model_dump(mode="json")))

    @app.get("/v1/system-admin/llm/usage/summary")
    def get_llm_usage_summary(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        filters = _query_model(request, UsageFilters)
        assert isinstance(filters, UsageFilters)
        return repository.usage_summary(session, filters.service_filters())

    @app.get("/v1/system-admin/llm/usage/timeseries")
    def get_llm_usage_timeseries(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        filters = _query_model(request, UsageFilters)
        assert isinstance(filters, UsageFilters)
        return {"items": repository.usage_timeseries(session, filters.service_filters())}

    @app.get("/v1/system-admin/llm/usage/breakdown")
    def get_llm_usage_breakdown(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        filters = _query_model(request, UsageBreakdownFilters)
        assert isinstance(filters, UsageBreakdownFilters)
        values = filters.service_filters()
        group_by = values.pop("group_by")
        return {"items": repository.usage_breakdown(session, values, group_by)}

    @app.get("/v1/system-admin/llm/usage/invocations")
    def list_llm_usage_invocations(request: Request, session: Any = Depends(system_session)) -> dict[str, Any]:
        filters = _query_model(request, InvocationFilters)
        assert isinstance(filters, InvocationFilters)
        values = filters.service_filters()
        return repository.list_invocations_page(session, values)
