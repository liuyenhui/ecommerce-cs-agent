from __future__ import annotations

from typing import Annotated, Any, Callable, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Path, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator


ResourceId = Annotated[UUID, Path()]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class LlmCreateRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=128)
    provider: Literal["openai", "deepseek", "qwen", "openai_compatible"]
    base_url: str = Field(min_length=1, max_length=2048)
    model_id: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1, max_length=4096)


class LlmUpdateRequest(StrictRequest):
    expected_revision: int = Field(ge=1, le=2_147_483_647)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider: Literal["openai", "deepseek", "qwen", "openai_compatible"] | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "LlmUpdateRequest":
        if not set(self.model_fields_set) - {"expected_revision"}:
            raise ValueError("at least one change is required")
        return self


class ConnectionTestRequest(StrictRequest):
    pass


class NodeBinding(StrictRequest):
    node_id: str = Field(min_length=1, max_length=128)
    llm_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class BindingReplaceRequest(StrictRequest):
    expected_revision: int = Field(ge=0, le=2_147_483_647)
    bindings: list[NodeBinding] = Field(max_length=32)


def register_system_admin_llm_node_routes(
    app: FastAPI,
    repository: Any,
    system_session: Callable[..., Any],
) -> None:
    @app.get("/v1/system-admin/llms")
    def list_llms(session: Any = Depends(system_session)) -> dict[str, Any]:
        return {"items": repository.list_llms(session)}

    @app.post("/v1/system-admin/llms")
    def create_llm(payload: LlmCreateRequest, session: Any = Depends(system_session)) -> JSONResponse:
        return JSONResponse(status_code=201, content=repository.create_llm(session, payload.model_dump(mode="json")))

    @app.patch("/v1/system-admin/llms/{llm_id}")
    def update_llm(llm_id: ResourceId, payload: LlmUpdateRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return repository.update_llm(session, str(llm_id), payload.model_dump(mode="json", exclude_none=True))

    @app.delete("/v1/system-admin/llms/{llm_id}", status_code=204)
    def delete_llm(llm_id: ResourceId, session: Any = Depends(system_session)) -> Response:
        repository.delete_llm(session, str(llm_id))
        return Response(status_code=204)

    @app.post("/v1/system-admin/llms/{llm_id}/connection-tests")
    def test_connection(llm_id: ResourceId, _payload: ConnectionTestRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return repository.test_connection(session, str(llm_id))

    @app.get("/v1/system-admin/langgraph-llm-bindings")
    def get_bindings(session: Any = Depends(system_session)) -> dict[str, Any]:
        return repository.get_bindings(session)

    @app.put("/v1/system-admin/langgraph-llm-bindings")
    def replace_bindings(payload: BindingReplaceRequest, session: Any = Depends(system_session)) -> dict[str, Any]:
        return repository.replace_bindings(session, payload.model_dump(mode="json"))
