from dataclasses import replace

from ecommerce_cs_agent.services.llm_runtime import (
    InMemoryRuntimeRouteRepository,
    RuntimeProvider,
    RuntimeReplyRoute,
    RuntimeRoutePolicy,
)


def _route(*, release_status: str = "running", route_enabled: bool = True) -> RuntimeReplyRoute:
    primary = RuntimeProvider(
        provider_id="provider-primary",
        provider_type="openai_compatible",
        base_url="https://llm.example.test/v1",
        secret_namespace="runtime",
        secret_name="llm-primary",
        secret_key="api-key",
        model="deepseek-chat",
        enabled=True,
        status="active",
    )
    fallback = RuntimeProvider(
        provider_id="provider-fallback",
        provider_type="openai_compatible",
        base_url="https://fallback.example.test/v1",
        secret_namespace="runtime",
        secret_name="llm-fallback",
        secret_key="api-key",
        model="deepseek-lite",
        enabled=True,
        status="active",
    )
    return RuntimeReplyRoute(
        route_id="route-1",
        organization_id="org-a",
        config_version_id="version-1",
        scenario="reply_generation",
        release_status=release_status,
        enabled=route_enabled,
        primary=primary,
        fallback=fallback,
        policy=RuntimeRoutePolicy(
            temperature=0.2,
            max_output_tokens=512,
            timeout_seconds=20,
            max_retries=1,
            circuit_breaker_threshold=5,
            recovery_probe_seconds=60,
        ),
    )


def test_resolves_only_running_released_reply_route_for_same_org_store() -> None:
    repository = InMemoryRuntimeRouteRepository(
        routes=[_route()], store_organizations={("org-a", "store-a")}
    )

    route = repository.resolve_reply_route(organization_id="org-a", store_id="store-a")

    assert route is not None
    assert route.scenario == "reply_generation"
    assert route.primary.model == "deepseek-chat"
    assert route.fallback is not None
    assert route.fallback.model == "deepseek-lite"
    assert route.policy.max_retries == 1
    assert repository.resolve_reply_route(organization_id="org-b", store_id="store-a") is None


def test_rejects_non_running_disabled_route_or_provider() -> None:
    disabled_primary = _route()
    disabled_primary = replace(
        disabled_primary, primary=replace(disabled_primary.primary, enabled=False)
    )
    repository = InMemoryRuntimeRouteRepository(
        routes=[_route(release_status="pending"), _route(route_enabled=False), disabled_primary],
        store_organizations={("org-a", "store-a")},
    )

    assert repository.resolve_reply_route(organization_id="org-a", store_id="store-a") is None


def test_requires_reply_generation_scenario_and_active_provider() -> None:
    route = _route()
    wrong_scenario = replace(route, scenario="knowledge_extraction")
    unhealthy = replace(route, primary=replace(route.primary, status="unhealthy"))
    repository = InMemoryRuntimeRouteRepository(
        routes=[wrong_scenario, unhealthy], store_organizations={("org-a", "store-a")}
    )

    assert repository.resolve_reply_route(organization_id="org-a", store_id="store-a") is None
