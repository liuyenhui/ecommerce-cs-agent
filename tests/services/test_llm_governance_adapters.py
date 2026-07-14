from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from ecommerce_cs_agent.services.llm_governance_adapters import (
    KubernetesSecretProviderConnectionTester,
    PostgresEvaluationReleaseGateChecker,
)


def _provider(provider_type: str = "openai") -> dict[str, object]:
    return {
        "provider_id": "11111111-1111-1111-1111-111111111111",
        "provider_type": provider_type,
        "base_url": "https://models.example.test/v1",
        "secret_ref": {"namespace": "runtime", "name": "ecommerce-cs-agent-llm-provider", "key": "api-key"},
    }


def test_kubernetes_secret_tester_resolves_secret_and_probes_openai_without_leaking_it(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("service-account-token", encoding="utf-8")
    ca_file.write_text("test-ca", encoding="utf-8")
    requests: list[object] = []

    def transport(request: object, timeout: float, _ca_file: str | None) -> tuple[int, bytes]:
        requests.append(request)
        if str(request.full_url).startswith("https://10.0.0.1:443/api/"):
            assert request.headers["Authorization"] == "Bearer service-account-token"
            body = {"data": {"api-key": base64.b64encode(b"provider-secret").decode()}}
            return 200, json.dumps(body).encode()
        assert request.full_url == "https://models.example.test/v1/models"
        assert request.headers["Authorization"] == "Bearer provider-secret"
        assert "provider-secret" not in request.full_url
        assert timeout <= 20
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.0.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_refs={("ecommerce-cs-agent-llm-provider", "api-key")},
        transport=transport,
        monotonic=lambda: 1.0,
    )
    result = tester(_provider(), {"timeout_seconds": 20, "max_tokens": 1})

    assert result == {"status": "passed", "latency_ms": 0, "error_code": None}
    assert "provider-secret" not in repr(result)
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("provider_type", "header"),
    [("anthropic", "X-api-key")],
)
def test_kubernetes_secret_tester_uses_provider_specific_auth_headers(
    tmp_path: Path, provider_type: str, header: str
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")

    def transport(request: object, _timeout: float, _ca_file: str | None) -> tuple[int, bytes]:
        if "/api/v1/namespaces/" in request.full_url:
            return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()
        assert request.headers[header] == "secret"
        if provider_type == "anthropic":
            assert request.headers["Anthropic-version"] == "2023-06-01"
        assert "secret" not in request.full_url
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="kubernetes.default.svc",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_refs={("ecommerce-cs-agent-llm-provider", "api-key")},
        transport=transport,
    )
    assert tester(_provider(provider_type), {"timeout_seconds": 3})["status"] == "passed"


def test_kubernetes_secret_tester_redacts_transport_failures(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")

    def transport(request: object, _timeout: float, _ca_file: str | None) -> tuple[int, bytes]:
        if "/api/v1/namespaces/" in request.full_url:
            return 200, json.dumps({"data": {"api-key": base64.b64encode(b"super-secret").decode()}}).encode()
        raise HTTPError(request.full_url, 401, "super-secret unauthorized", {}, None)

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="kubernetes.default.svc",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_refs={("ecommerce-cs-agent-llm-provider", "api-key")},
        transport=transport,
    )
    result = tester(_provider(), {"timeout_seconds": 3})
    assert result == {"status": "failed", "latency_ms": pytest.approx(0, abs=100), "error_code": "auth_failed"}
    assert "super-secret" not in repr(result)


def test_kubernetes_secret_tester_requires_in_cluster_prerequisites(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Kubernetes in-cluster"):
        KubernetesSecretProviderConnectionTester.from_environment(
            environ={}, token_file=str(tmp_path / "missing"), ca_file=str(tmp_path / "missing-ca")
        )


@pytest.mark.parametrize(
    "secret_ref",
    [
        {"namespace": "other", "name": "ecommerce-cs-agent-llm-provider", "key": "api-key"},
        {"namespace": "runtime", "name": "ecommerce-cs-agent-runtime", "key": "DATABASE_URL"},
        {"namespace": "runtime", "name": "ecommerce-cs-agent-runtime", "key": "JWT_SECRET"},
        {"namespace": "runtime", "name": "ecommerce-cs-agent-llm-provider", "key": "JWT_SECRET"},
        {"namespace": "runtime", "name": "other-llm", "key": "api-key"},
        {"namespace": "runtime", "name": "ecommerce-cs-agent-llm-provider", "key": "bad/key"},
        {"namespace": "runtime", "name": "ecommerce-cs-agent-llm-provider", "key": "a" * 254},
    ],
)
def test_kubernetes_secret_tester_rejects_secret_outside_allowlist_before_transport(
    tmp_path: Path, secret_ref: dict[str, str]
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    transport_calls: list[object] = []

    def transport(request: object, _timeout: float, _ca_file: str | None) -> tuple[int, bytes]:
        transport_calls.append(request)
        return 500, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="kubernetes.default.svc",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_refs={("ecommerce-cs-agent-llm-provider", "api-key")},
        transport=transport,
    )
    provider = _provider()
    provider["secret_ref"] = secret_ref

    assert tester(provider, {"timeout_seconds": 3}) == {
        "status": "failed",
        "latency_ms": pytest.approx(0, abs=100),
        "error_code": "invalid_response",
    }
    assert transport_calls == []


@pytest.mark.parametrize("downward_namespace", ["runtime", None])
def test_kubernetes_secret_tester_reads_namespace_from_downward_env_or_service_account_file(
    tmp_path: Path, downward_namespace: str | None
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    namespace_file = tmp_path / "namespace"
    token_file.write_text("service-account-token", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    namespace_file.write_text("runtime", encoding="utf-8")
    secret_requests: list[str] = []

    def transport(request: object, _timeout: float, _ca_file: str | None) -> tuple[int, bytes]:
        if "/api/v1/namespaces/" in request.full_url:
            secret_requests.append(request.full_url)
            return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()
        return 200, b"{}"

    environment = {
        "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
        "KUBERNETES_SERVICE_PORT_HTTPS": "443",
        "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
            [{"name": "ecommerce-cs-agent-llm-provider", "keys": ["api-key"]}]
        ),
    }
    if downward_namespace:
        environment["LLM_GOVERNANCE_SECRET_NAMESPACE"] = downward_namespace
    tester = KubernetesSecretProviderConnectionTester.from_environment(
        environ=environment,
        token_file=str(token_file),
        ca_file=str(ca_file),
        namespace_file=str(namespace_file),
        transport=transport,
    )

    assert tester(_provider(), {"timeout_seconds": 3})["status"] == "passed"
    assert secret_requests == [
        "https://kubernetes.default.svc:443/api/v1/namespaces/runtime/secrets/ecommerce-cs-agent-llm-provider"
    ]


@pytest.mark.parametrize(
    "environment",
    [
        {
            "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
                [{"name": "ecommerce-cs-agent-llm-provider", "keys": ["api-key"]}]
            ),
        },
        {
            "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
        },
        {
            "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": "[]",
        },
        {
            "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
                [{"name": "ecommerce-cs-agent-llm-provider", "keys": []}]
            ),
        },
        {
            "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
                [{"name": "ecommerce-cs-agent-llm-provider", "keys": ["bad/key"]}]
            ),
        },
    ],
)
def test_kubernetes_secret_tester_fails_fast_without_namespace_or_allowlist(
    tmp_path: Path, environment: dict[str, str]
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    namespace_file = tmp_path / "missing-namespace"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")

    with pytest.raises(RuntimeError, match="namespace and Secret allowlist"):
        KubernetesSecretProviderConnectionTester.from_environment(
            environ=environment,
            token_file=str(token_file),
            ca_file=str(ca_file),
            namespace_file=str(namespace_file),
        )


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://azure.example.test", "https://azure.example.test/openai/v1/models"),
        ("https://azure.example.test/openai/v1", "https://azure.example.test/openai/v1/models"),
    ],
)
def test_kubernetes_secret_tester_uses_standard_azure_models_url(
    tmp_path: Path, base_url: str, expected_url: str
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")

    def transport(request: object, timeout: float, _ca_file: str | None) -> tuple[int, bytes]:
        if "/api/v1/namespaces/" in request.full_url:
            return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()
        assert request.full_url == expected_url
        assert request.headers == {"Accept": "application/json", "Api-key": "secret"}
        assert timeout == 3.0
        assert "secret" not in request.full_url
        assert "?" not in request.full_url
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="kubernetes.default.svc",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_refs={("ecommerce-cs-agent-llm-provider", "api-key")},
        transport=transport,
    )
    provider = _provider("azure_openai")
    provider["base_url"] = base_url

    assert tester(provider, {"timeout_seconds": 3})["status"] == "passed"


def test_postgres_evaluation_gate_requires_same_completed_passing_run() -> None:
    captured: dict[str, object] = {}

    class Cursor:
        def __enter__(self) -> "Cursor": return self
        def __exit__(self, *_args: object) -> None: return None
        def execute(self, sql: str, params: tuple[object, ...]) -> None:
            captured.update(sql=sql, params=params)
        def fetchone(self) -> tuple[str]:
            return ("eval-1",)

    class Connection:
        def __enter__(self) -> "Connection": return self
        def __exit__(self, *_args: object) -> None: return None
        def cursor(self) -> Cursor: return Cursor()

    checker = PostgresEvaluationReleaseGateChecker("postgresql://example", connect=lambda _url: Connection())
    result = checker(
        {
            "organization_id": "11111111-1111-1111-1111-111111111111",
            "version_id": "22222222-2222-2222-2222-222222222222",
            "revision": 7,
            "configuration_hash": "a" * 64,
            "status": "validated",
        },
        "eval-1",
    )
    assert result == {"status": "passed", "error_code": None}
    assert captured["params"] == (
        "eval-1",
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        7,
        "a" * 64,
    )
    assert "%s" in str(captured["sql"])
    assert "config_revision" in str(captured["sql"])
    assert "configuration_hash" in str(captured["sql"])
    assert "eval.completed_at >= eval.created_at" in str(captured["sql"])


@pytest.mark.parametrize(
    "version",
    [
        {"revision": 8, "configuration_hash": "a" * 64, "status": "validated"},
        {"revision": 7, "configuration_hash": "b" * 64, "status": "validated"},
        {"revision": 7, "configuration_hash": "a" * 64, "status": "pending_publish"},
    ],
)
def test_postgres_evaluation_gate_rejects_stale_snapshot_or_nonvalidated_version(version: dict[str, object]) -> None:
    class Cursor:
        def __enter__(self) -> "Cursor": return self
        def __exit__(self, *_args: object) -> None: return None
        def execute(self, _sql: str, _params: tuple[object, ...]) -> None: return None
        def fetchone(self) -> None: return None

    class Connection:
        def __enter__(self) -> "Connection": return self
        def __exit__(self, *_args: object) -> None: return None
        def cursor(self) -> Cursor: return Cursor()

    checker = PostgresEvaluationReleaseGateChecker("postgresql://example", connect=lambda _url: Connection())
    candidate = {
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "version_id": "22222222-2222-2222-2222-222222222222",
        **version,
    }
    assert checker(candidate, "eval-1") == {"status": "failed", "error_code": "release_gate_failed"}


def test_postgres_evaluation_gate_redacts_database_failures() -> None:
    def failed_connect(_url: str) -> object:
        raise RuntimeError("postgresql://user:secret@example/private")

    checker = PostgresEvaluationReleaseGateChecker("postgresql://example", connect=failed_connect)
    result = checker(
        {
            "organization_id": "11111111-1111-1111-1111-111111111111",
            "version_id": "22222222-2222-2222-2222-222222222222",
            "revision": 7,
            "configuration_hash": "a" * 64,
            "status": "validated",
        },
        "eval-1",
    )
    assert result == {"status": "failed", "error_code": "release_gate_failed"}
    assert "secret" not in repr(result)
