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
        "secret_ref": {"namespace": "runtime", "name": "llm", "key": "api-key"},
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
        transport=transport,
        monotonic=lambda: 1.0,
    )
    result = tester(_provider(), {"timeout_seconds": 20, "max_tokens": 1})

    assert result == {"status": "passed", "latency_ms": 0, "error_code": None}
    assert "provider-secret" not in repr(result)
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("provider_type", "header"),
    [("anthropic", "X-api-key"), ("azure_openai", "Api-key")],
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


def test_postgres_evaluation_gate_requires_same_completed_passing_run() -> None:
    captured: dict[str, object] = {}

    class Cursor:
        def __enter__(self) -> "Cursor": return self
        def __exit__(self, *_args: object) -> None: return None
        def execute(self, sql: str, params: tuple[object, ...]) -> None:
            captured.update(sql=sql, params=params)
        def fetchone(self) -> tuple[str, str, int]:
            return ("completed", "passed", 0)

    class Connection:
        def __enter__(self) -> "Connection": return self
        def __exit__(self, *_args: object) -> None: return None
        def cursor(self) -> Cursor: return Cursor()

    checker = PostgresEvaluationReleaseGateChecker("postgresql://example", connect=lambda _url: Connection())
    result = checker(
        {"organization_id": "11111111-1111-1111-1111-111111111111", "version_id": "22222222-2222-2222-2222-222222222222"},
        "eval-1",
    )
    assert result == {"status": "passed", "error_code": None}
    assert captured["params"] == ("eval-1", "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    assert "%s" in str(captured["sql"])
