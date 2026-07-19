from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RuntimeProvider:
    provider_id: str
    provider_type: str
    base_url: str
    secret_namespace: str
    secret_name: str
    secret_key: str
    model: str
    enabled: bool
    status: str

    @property
    def active(self) -> bool:
        return self.enabled and self.status == "active"


@dataclass(frozen=True, slots=True)
class RuntimeRoutePolicy:
    temperature: float
    max_output_tokens: int
    timeout_seconds: int
    max_retries: int
    circuit_breaker_threshold: int
    recovery_probe_seconds: int


@dataclass(frozen=True, slots=True)
class RuntimeReplyRoute:
    route_id: str
    organization_id: str
    config_version_id: str
    scenario: str
    release_status: str
    enabled: bool
    primary: RuntimeProvider
    fallback: RuntimeProvider | None
    policy: RuntimeRoutePolicy

    @property
    def runnable(self) -> bool:
        return (
            self.release_status == "running"
            and self.scenario == "reply_generation"
            and self.enabled
            and self.primary.active
        )


class RuntimeRouteRepository(Protocol):
    def resolve_reply_route(
        self, *, organization_id: str, store_id: str
    ) -> RuntimeReplyRoute | None: ...


class NullRuntimeRouteRepository:
    def resolve_reply_route(
        self, *, organization_id: str, store_id: str
    ) -> RuntimeReplyRoute | None:
        return None


class InMemoryRuntimeRouteRepository:
    def __init__(
        self,
        *,
        routes: list[RuntimeReplyRoute] | None = None,
        store_organizations: set[tuple[str, str]] | None = None,
    ) -> None:
        self._routes = list(routes or [])
        self._store_organizations = set(store_organizations or set())

    def resolve_reply_route(
        self, *, organization_id: str, store_id: str
    ) -> RuntimeReplyRoute | None:
        if (organization_id, store_id) not in self._store_organizations:
            return None
        return next(
            (
                route
                for route in self._routes
                if route.organization_id == organization_id and route.runnable
            ),
            None,
        )


class PostgresRuntimeRouteRepository:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url

    def resolve_reply_route(
        self, *, organization_id: str, store_id: str
    ) -> RuntimeReplyRoute | None:
        with self._connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT route.id::text, org.external_organization_id,
                           version.id::text, route.scenario, release.status, route.enabled,
                           primary_provider.id::text, primary_provider.provider_type,
                           primary_provider.base_url, primary_provider.secret_namespace,
                           primary_provider.secret_name, primary_provider.secret_key,
                           route.primary_model, primary_provider.enabled, primary_provider.status,
                           fallback_provider.id::text, fallback_provider.provider_type,
                           fallback_provider.base_url, fallback_provider.secret_namespace,
                           fallback_provider.secret_name, fallback_provider.secret_key,
                           route.fallback_model, fallback_provider.enabled, fallback_provider.status,
                           route.temperature, route.max_output_tokens, route.timeout_seconds,
                           route.max_retries, route.circuit_breaker_threshold,
                           route.recovery_probe_seconds
                    FROM organization org
                    JOIN store store
                      ON store.organization_id = org.id
                     AND store.external_store_id = %s
                    JOIN llm_release_record release
                      ON release.organization_id = org.id
                     AND release.status = 'running'
                    JOIN llm_config_version version
                      ON version.id = release.config_version_id
                     AND version.organization_id = org.id
                     AND version.status = 'running'
                    JOIN llm_scenario_route route
                      ON route.config_version_id = version.id
                     AND route.scenario = 'reply_generation'
                     AND route.enabled = true
                    JOIN llm_provider_config primary_provider
                      ON primary_provider.id = route.primary_provider_config_id
                     AND primary_provider.enabled = true
                     AND primary_provider.status = 'active'
                    LEFT JOIN llm_provider_config fallback_provider
                      ON fallback_provider.id = route.fallback_provider_config_id
                     AND fallback_provider.enabled = true
                     AND fallback_provider.status = 'active'
                    WHERE org.external_organization_id = %s
                    LIMIT 1
                    """,
                    (store_id, organization_id),
                )
                row = cursor.fetchone()
        return _route_from_row(row) if row else None


def _route_from_row(row: tuple[object, ...]) -> RuntimeReplyRoute:
    primary = RuntimeProvider(
        provider_id=str(row[6]), provider_type=str(row[7]), base_url=str(row[8]),
        secret_namespace=str(row[9]), secret_name=str(row[10]), secret_key=str(row[11]),
        model=str(row[12]), enabled=bool(row[13]), status=str(row[14]),
    )
    fallback = None
    if row[15] is not None:
        fallback = RuntimeProvider(
            provider_id=str(row[15]), provider_type=str(row[16]), base_url=str(row[17]),
            secret_namespace=str(row[18]), secret_name=str(row[19]), secret_key=str(row[20]),
            model=str(row[21]), enabled=bool(row[22]), status=str(row[23]),
        )
    return RuntimeReplyRoute(
        route_id=str(row[0]), organization_id=str(row[1]), config_version_id=str(row[2]),
        scenario=str(row[3]), release_status=str(row[4]), enabled=bool(row[5]),
        primary=primary, fallback=fallback,
        policy=RuntimeRoutePolicy(
            temperature=float(Decimal(str(row[24]))), max_output_tokens=int(row[25]),
            timeout_seconds=int(row[26]), max_retries=int(row[27]),
            circuit_breaker_threshold=int(row[28]), recovery_probe_seconds=int(row[29]),
        ),
    )
