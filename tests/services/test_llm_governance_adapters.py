from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

from ecommerce_cs_agent.services import llm_governance_adapters as adapter_module
from ecommerce_cs_agent.services.llm_governance_adapters import (
    KubernetesSecretProviderConnectionTester,
    PostgresEvaluationReleaseGateChecker,
    _KubernetesApiTransport,
    _PinnedProviderTransport,
)


def _deadline(seconds: float) -> object:
    deadline_type = getattr(adapter_module, "_Deadline", None)
    assert deadline_type is not None, "transport deadline abstraction is required"
    return deadline_type(time.monotonic() + seconds)


def _remaining(deadline: object) -> float:
    return getattr(deadline, "remaining")()


def _provider(provider_type: str = "openai") -> dict[str, object]:
    return {
        "provider_id": "11111111-1111-1111-1111-111111111111",
        "provider_type": provider_type,
        "base_url": "https://models.example.test/v1",
        "secret_ref": {"namespace": "runtime", "name": "ecommerce-cs-agent-llm-provider", "key": "api-key"},
    }


def test_bounded_resolver_pool_caps_workers_outstanding_jobs_and_recovers() -> None:
    pool_type = getattr(adapter_module, "_BoundedResolverPool", None)
    assert pool_type is not None, "bounded resolver pool is required"
    release = threading.Event()
    two_workers_started = threading.Event()
    lock = threading.Lock()
    started = 0

    def blocking_getaddrinfo(_host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        nonlocal started
        with lock:
            started += 1
            if started >= 2:
                two_workers_started.set()
        release.wait()
        return [(2, 1, 6, "", ("10.0.0.9", port))]

    pool = pool_type(workers=2, max_outstanding=3, getaddrinfo=blocking_getaddrinfo)
    caller_results: list[str] = []

    def call_and_timeout() -> None:
        try:
            pool.resolve("blocked.invalid", 443, 0.08)
        except TimeoutError:
            caller_results.append("timeout")

    callers = [threading.Thread(target=call_and_timeout) for _ in range(3)]
    for caller in callers:
        caller.start()
    assert two_workers_started.wait(0.2)
    started_at = time.monotonic()
    with pytest.raises(TimeoutError):
        pool.resolve("capacity.invalid", 443, 1.0)
    assert time.monotonic() - started_at < 0.05
    assert len(pool._threads) == 2
    assert all(worker.daemon for worker in pool._threads)
    assert all("blocked.invalid" not in worker.name for worker in pool._threads)

    for caller in callers:
        caller.join(0.2)
    assert caller_results == ["timeout", "timeout", "timeout"]
    with pytest.raises(TimeoutError):
        pool.resolve("still-full.invalid", 443, 1.0)

    release.set()
    deadline = time.monotonic() + 0.5
    while pool.outstanding and time.monotonic() < deadline:
        time.sleep(0.005)
    assert pool.resolve("recovered.invalid", 443, 0.2) == ["10.0.0.9"]


def test_kubernetes_service_host_must_be_an_ip_literal(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")

    with pytest.raises(RuntimeError, match="IP literal"):
        KubernetesSecretProviderConnectionTester(
            kubernetes_host="kubernetes.default.svc",
            kubernetes_port=443,
            service_account_token_file=str(token_file),
            kubernetes_ca_file=str(ca_file),
            allowed_namespace="runtime",
            allowed_secret_origins={
                ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
            },
        )


def test_kubernetes_ipv6_api_url_is_bracketed_and_uses_the_literal_address(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    urls: list[str] = []

    def kubernetes_transport(request: object, _deadline: object, _ca: str | None) -> tuple[int, bytes]:
        urls.append(request.full_url)
        return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="fd00::10",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=lambda *_args: (200, b"{}"),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
    )

    assert tester(_provider(), {"timeout_seconds": 20})["status"] == "passed"
    assert urls == [
        "https://[fd00::10]:443/api/v1/namespaces/runtime/secrets/ecommerce-cs-agent-llm-provider"
    ]


def test_kubernetes_secret_tester_resolves_secret_and_probes_openai_without_leaking_it(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("service-account-token", encoding="utf-8")
    ca_file.write_text("test-ca", encoding="utf-8")
    requests: list[object] = []

    def transport(request: object, deadline: object, _ca_file: str | None) -> tuple[int, bytes]:
        requests.append(request)
        if str(request.full_url).startswith("https://10.0.0.1:443/api/"):
            assert request.headers["Authorization"] == "Bearer service-account-token"
            body = {"data": {"api-key": base64.b64encode(b"provider-secret").decode()}}
            return 200, json.dumps(body).encode()
        assert request.full_url == "https://models.example.test/v1/models"
        assert request.headers["Authorization"] == "Bearer provider-secret"
        assert "provider-secret" not in request.full_url
        assert _remaining(deadline) <= 20
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.0.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=transport,
        provider_transport=lambda request, deadline, _ip, _host: transport(request, deadline, None),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
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
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=transport,
        provider_transport=lambda request, timeout, _ip, _host: transport(request, timeout, None),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
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
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=transport,
        provider_transport=lambda request, timeout, _ip, _host: transport(request, timeout, None),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
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
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=transport,
        provider_transport=lambda request, timeout, _ip, _host: transport(request, timeout, None),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
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
        "KUBERNETES_SERVICE_HOST": "10.96.0.1",
        "KUBERNETES_SERVICE_PORT_HTTPS": "443",
        "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
            [
                {
                    "name": "ecommerce-cs-agent-llm-provider",
                    "keys": [{"key": "api-key", "allowedOrigins": []}],
                }
            ]
        ),
        "LLM_GOVERNANCE_RUNTIME_LLM_SECRET_REF": json.dumps(
            {"name": "ecommerce-cs-agent-llm-provider", "key": "api-key"}
        ),
        "LLM_BASE_URL": "https://models.example.test/v1",
    }
    if downward_namespace:
        environment["LLM_GOVERNANCE_SECRET_NAMESPACE"] = downward_namespace
    tester = KubernetesSecretProviderConnectionTester.from_environment(
        environ=environment,
        token_file=str(token_file),
        ca_file=str(ca_file),
        namespace_file=str(namespace_file),
        kubernetes_transport=transport,
        provider_transport=lambda request, timeout, _ip, _host: transport(request, timeout, None),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
    )

    assert tester(_provider(), {"timeout_seconds": 3})["status"] == "passed"
    assert secret_requests == [
        "https://10.96.0.1:443/api/v1/namespaces/runtime/secrets/ecommerce-cs-agent-llm-provider"
    ]


@pytest.mark.parametrize(
    "environment",
    [
        {
            "KUBERNETES_SERVICE_HOST": "10.96.0.1",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
                [
                    {
                        "name": "ecommerce-cs-agent-llm-provider",
                        "keys": [
                            {"key": "api-key", "allowedOrigins": ["https://models.example.test"]}
                        ],
                    }
                ]
            ),
        },
        {
            "KUBERNETES_SERVICE_HOST": "10.96.0.1",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
        },
        {
            "KUBERNETES_SERVICE_HOST": "10.96.0.1",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": "[]",
        },
        {
            "KUBERNETES_SERVICE_HOST": "10.96.0.1",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
                [{"name": "ecommerce-cs-agent-llm-provider", "keys": []}]
            ),
        },
        {
            "KUBERNETES_SERVICE_HOST": "10.96.0.1",
            "KUBERNETES_SERVICE_PORT_HTTPS": "443",
            "LLM_GOVERNANCE_SECRET_NAMESPACE": "runtime",
            "LLM_GOVERNANCE_ALLOWED_SECRET_REFS": json.dumps(
                [
                    {
                        "name": "ecommerce-cs-agent-llm-provider",
                        "keys": [{"key": "bad/key", "allowedOrigins": []}],
                    }
                ]
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

    def transport(request: object, deadline: object, _ca_file: str | None) -> tuple[int, bytes]:
        if "/api/v1/namespaces/" in request.full_url:
            return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()
        assert request.full_url == expected_url
        assert request.headers == {
            "Accept": "application/json",
            "Host": "azure.example.test",
            "Api-key": "secret",
        }
        assert 0 < _remaining(deadline) <= 3.0
        assert "secret" not in request.full_url
        assert "?" not in request.full_url
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://azure.example.test"}
        },
        kubernetes_transport=transport,
        provider_transport=lambda request, deadline, _ip, _host: transport(request, deadline, None),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
    )
    provider = _provider("azure_openai")
    provider["base_url"] = base_url

    assert tester(provider, {"timeout_seconds": 3})["status"] == "passed"


@pytest.mark.parametrize(
    ("base_url", "resolved_ips"),
    [
        ("https://attacker.example/v1", ["93.184.216.34"]),
        ("https://models.example.test/v1", ["127.0.0.1"]),
        ("https://models.example.test/v1", ["93.184.216.34", "10.0.0.8"]),
        ("https://kubernetes.default.svc/v1", ["93.184.216.34"]),
        ("http://models.example.test/v1", ["93.184.216.34"]),
        ("https://user@models.example.test/v1", ["93.184.216.34"]),
        ("https://models.example.test/v1?debug=1", ["93.184.216.34"]),
        ("https://models.example.test/v1#fragment", ["93.184.216.34"]),
        ("https://models.example.test/v1\nheader", ["93.184.216.34"]),
    ],
)
def test_provider_origin_and_public_dns_are_checked_before_kubernetes_secret_access(
    tmp_path: Path, base_url: str, resolved_ips: list[str]
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    kubernetes_calls: list[object] = []
    provider_calls: list[object] = []

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=lambda request, timeout, ca: (
            kubernetes_calls.append((request, timeout, ca)) or (500, b"{}")
        ),
        provider_transport=lambda request, timeout, ip, host: (
            provider_calls.append((request, timeout, ip, host)) or (500, b"{}")
        ),
        resolver=lambda _host, _port, _timeout: resolved_ips,
    )
    provider = _provider()
    provider["base_url"] = base_url

    result = tester(provider, {"timeout_seconds": 20})

    assert result["status"] == "failed"
    assert result["error_code"] == "invalid_response"
    assert kubernetes_calls == []
    assert provider_calls == []
    assert all(value not in repr(result) for value in (base_url, *resolved_ips))


@pytest.mark.parametrize("resolved_ip", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_provider_transport_uses_the_initial_pinned_public_ip_without_second_dns_lookup(
    tmp_path: Path, resolved_ip: str
) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    resolver_calls: list[str] = []
    provider_calls: list[tuple[str, str]] = []

    def resolver(host: str, _port: int, _timeout: float) -> list[str]:
        resolver_calls.append(host)
        return [resolved_ip] if len(resolver_calls) == 1 else ["10.0.0.8"]

    def kubernetes_transport(_request: object, _timeout: float, _ca: str | None) -> tuple[int, bytes]:
        return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()

    def provider_transport(request: object, _timeout: float, ip: str, server_hostname: str) -> tuple[int, bytes]:
        provider_calls.append((ip, server_hostname))
        assert request.headers["Host"] == "models.example.test"
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=provider_transport,
        resolver=resolver,
    )

    assert tester(_provider(), {"timeout_seconds": 20})["status"] == "passed"
    assert resolver_calls == ["models.example.test"]
    assert provider_calls == [(resolved_ip, "models.example.test")]


def test_provider_redirect_is_not_followed_and_authorization_is_not_sent_to_location(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    provider_requests: list[object] = []

    def kubernetes_transport(_request: object, _timeout: float, _ca: str | None) -> tuple[int, bytes]:
        return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()

    def provider_transport(request: object, _timeout: float, _ip: str, _host: str) -> tuple[int, bytes]:
        provider_requests.append(request)
        return 302, b'{"location":"https://attacker.example/steal"}'

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=provider_transport,
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
    )

    result = tester(_provider(), {"timeout_seconds": 20})

    assert result == {"status": "failed", "latency_ms": pytest.approx(0, abs=100), "error_code": "invalid_response"}
    assert len(provider_requests) == 1
    assert provider_requests[0].headers["Authorization"] == "Bearer secret"
    assert "attacker.example" not in repr(result)


def test_single_deadline_passes_only_remaining_time_to_provider(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    clock = [0.0]
    deadlines: list[object] = []
    provider_timeouts: list[float] = []

    def kubernetes_transport(_request: object, deadline: object, _ca: str | None) -> tuple[int, bytes]:
        deadlines.append(deadline)
        assert _remaining(deadline) == pytest.approx(20.0)
        clock[0] = 12.0
        return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()

    def provider_transport(_request: object, deadline: object, _ip: str, _host: str) -> tuple[int, bytes]:
        deadlines.append(deadline)
        provider_timeouts.append(_remaining(deadline))
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=provider_transport,
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
        monotonic=lambda: clock[0],
    )

    assert tester(_provider(), {"timeout_seconds": 20})["status"] == "passed"
    assert deadlines[0] is deadlines[1]
    assert provider_timeouts == [pytest.approx(8.0)]


def test_exhausted_deadline_after_secret_resolution_does_not_call_provider(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    clock = [0.0]
    provider_calls: list[object] = []

    def kubernetes_transport(_request: object, _timeout: float, _ca: str | None) -> tuple[int, bytes]:
        clock[0] = 21.0
        return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=lambda *args: provider_calls.append(args) or (200, b"{}"),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
        monotonic=lambda: clock[0],
    )

    result = tester(_provider(), {"timeout_seconds": 20})

    assert result["error_code"] == "timeout"
    assert provider_calls == []


def test_exhausted_deadline_after_provider_response_is_canonical_timeout(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    clock = [0.0]

    def kubernetes_transport(_request: object, _deadline: object, _ca: str | None) -> tuple[int, bytes]:
        return 200, json.dumps({"data": {"api-key": base64.b64encode(b"secret").decode()}}).encode()

    def provider_transport(_request: object, _deadline: object, _ip: str, _host: str) -> tuple[int, bytes]:
        clock[0] = 21.0
        return 200, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=provider_transport,
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
        monotonic=lambda: clock[0],
    )

    result = tester(_provider(), {"timeout_seconds": 20})

    assert result["status"] == "failed"
    assert result["error_code"] == "timeout"
    assert set(result) == {"status", "latency_ms", "error_code"}


def test_default_kubernetes_transport_ignores_https_proxy_and_targets_only_cluster_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class RawSocket:
        def settimeout(self, timeout: float) -> None: calls["socket_timeout"] = timeout
        def do_handshake(self) -> None: calls["tls_handshake"] = True
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: calls["socket_closed"] = True

    raw_socket = RawSocket()

    class Context:
        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            calls.update(
                wrapped_socket=sock,
                server_hostname=server_hostname,
                do_handshake_on_connect=do_handshake_on_connect,
            )
            return sock

    class Response:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b"{}"

    class Connection:
        def __init__(self, host: str, port: int, **kwargs: object) -> None:
            calls.update(host=host, port=port, kwargs=kwargs)
            self.sock: object | None = None

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            calls.update(method=method, path=path, headers=headers)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setenv("HTTPS_PROXY", "https://attacker.invalid:8443")
    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda address, timeout: calls.update(socket_address=address) or raw_socket,
    )
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda **_kwargs: Context())

    status, body = _KubernetesApiTransport(
        tls_server_hostname="kubernetes.default.svc"
    )(
        adapter_module.Request(
            "https://10.96.0.1:443/api/v1/namespaces/runtime/secrets/llm",
            headers={"Authorization": "Bearer token"},
        ),
        _deadline(5.0),
        "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
    )

    assert (status, body) == (200, b"{}")
    assert calls["host"] == "10.96.0.1"
    assert calls["port"] == 443
    assert calls["socket_address"] == ("10.96.0.1", 443)
    assert calls["server_hostname"] == "kubernetes.default.svc"
    assert calls["do_handshake_on_connect"] is False
    assert calls["tls_handshake"] is True
    assert calls["path"] == "/api/v1/namespaces/runtime/secrets/llm"
    assert "attacker.invalid" not in repr(calls)


@pytest.mark.parametrize("transport_kind", ["kubernetes", "provider"])
def test_tls_socket_is_owned_before_post_wrap_deadline_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transport_kind: str,
) -> None:
    clock = [0.0]

    class Socket:
        def __init__(self) -> None:
            self.closed = False

        def settimeout(self, _timeout: float) -> None:
            return None

        def shutdown(self, _how: int) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    raw_socket = Socket()
    tls_socket = Socket()

    class Context:
        def wrap_socket(
            self,
            _sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool = True,
        ) -> object:
            assert do_handshake_on_connect is False
            assert server_hostname in {
                "kubernetes.default.svc",
                "models.example.test",
            }
            clock[0] = 2.0
            return tls_socket

    deadline_type = getattr(adapter_module, "_Deadline")
    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: raw_socket,
    )
    monkeypatch.setattr(
        adapter_module.ssl,
        "create_default_context",
        lambda **_kwargs: Context(),
    )

    with pytest.raises(TimeoutError):
        if transport_kind == "kubernetes":
            ca_file = tmp_path / "ca.crt"
            ca_file.write_text("ca", encoding="utf-8")
            _KubernetesApiTransport()(
                adapter_module.Request(
                    "https://10.96.0.1/api/v1/namespaces/runtime/secrets/llm"
                ),
                deadline_type(1.0, lambda: clock[0]),
                str(ca_file),
            )
        else:
            _PinnedProviderTransport()(
                adapter_module.Request("https://models.example.test/models"),
                deadline_type(1.0, lambda: clock[0]),
                "93.184.216.34",
                "models.example.test",
            )

    assert tls_socket.closed is True


def test_kubernetes_redirect_is_rejected_without_reusing_service_account_token(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ca_file = tmp_path / "ca.crt"
    token_file.write_text("sa-token", encoding="utf-8")
    ca_file.write_text("ca", encoding="utf-8")
    kubernetes_requests: list[object] = []
    provider_calls: list[object] = []

    def kubernetes_transport(request: object, _timeout: float, _ca: str | None) -> tuple[int, bytes]:
        kubernetes_requests.append(request)
        return 302, b"{}"

    tester = KubernetesSecretProviderConnectionTester(
        kubernetes_host="10.96.0.1",
        kubernetes_port=443,
        service_account_token_file=str(token_file),
        kubernetes_ca_file=str(ca_file),
        allowed_namespace="runtime",
        allowed_secret_origins={
            ("ecommerce-cs-agent-llm-provider", "api-key"): {"https://models.example.test"}
        },
        kubernetes_transport=kubernetes_transport,
        provider_transport=lambda *args: provider_calls.append(args) or (200, b"{}"),
        resolver=lambda _host, _port, _timeout: ["93.184.216.34"],
    )

    result = tester(_provider(), {"timeout_seconds": 20})

    assert result["error_code"] == "invalid_response"
    assert len(kubernetes_requests) == 1
    assert kubernetes_requests[0].headers["Authorization"] == "Bearer sa-token"
    assert provider_calls == []


def test_default_provider_transport_connects_to_pinned_ip_with_original_tls_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    class RawSocket:
        def settimeout(self, timeout: float) -> None: calls["socket_timeout"] = timeout
        def do_handshake(self) -> None: calls["tls_handshake"] = True
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: calls["socket_closed"] = True

    raw_socket = RawSocket()

    class Context:
        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            calls.update(
                wrapped_socket=sock,
                server_hostname=server_hostname,
                do_handshake_on_connect=do_handshake_on_connect,
            )
            return sock

    class Response:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b"{}"

    class Connection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.update(http_host=host, http_port=port, timeout=timeout)
            self.sock: object | None = None

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            calls.update(method=method, path=path, headers=headers)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda address, timeout: calls.update(socket_address=address, socket_timeout=timeout) or raw_socket,
    )
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)

    status, _body = _PinnedProviderTransport()(
        adapter_module.Request(
            "https://models.example.test/models",
            headers={"Host": "models.example.test", "Authorization": "Bearer secret"},
        ),
        _deadline(5.0),
        "93.184.216.34",
        "models.example.test",
    )

    assert status == 200
    assert calls["socket_address"] == ("93.184.216.34", 443)
    assert calls["server_hostname"] == "models.example.test"
    assert calls["do_handshake_on_connect"] is False
    assert calls["tls_handshake"] is True
    assert calls["headers"] == {"Host": "models.example.test", "Authorization": "Bearer secret"}


def test_provider_transport_enforces_one_deadline_across_tcp_tls_and_http_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowSocket:
        def settimeout(self, _timeout: float) -> None: return None
        def do_handshake(self) -> None: return None
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: return None

    slow_socket = SlowSocket()

    class Context:
        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            assert do_handshake_on_connect is False
            assert server_hostname == "models.example.test"
            time.sleep(0.04)
            return sock

    class Connection:
        def __init__(self, _host: str, _port: int, timeout: float) -> None:
            self.sock: object | None = None
        def request(self, _method: str, _path: str, headers: dict[str, str]) -> None:
            time.sleep(0.04)
        def getresponse(self) -> object:
            raise AssertionError("deadline must expire before reading the response")
        def close(self) -> None:
            raise OSError("socket was closed by deadline guard")

    def slow_connect(_address: object, timeout: float) -> SlowSocket:
        assert 0 < timeout <= 0.1
        time.sleep(0.04)
        return slow_socket

    monkeypatch.setattr(adapter_module.socket, "create_connection", slow_connect)
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        _PinnedProviderTransport()(
            adapter_module.Request("https://models.example.test/models"),
            _deadline(0.1),
            "93.184.216.34",
            "models.example.test",
        )

    assert time.monotonic() - started < 0.25


def test_deadline_guard_socket_oserror_and_close_error_remain_canonical_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]

    class Socket:
        def settimeout(self, _timeout: float) -> None: return None
        def do_handshake(self) -> None: return None
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: return None

    sock = Socket()

    class Context:
        def wrap_socket(
            self,
            value: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            assert do_handshake_on_connect is False
            return value

    class Connection:
        def __init__(self, _host: str, _port: int, timeout: float) -> None:
            self.sock: object | None = None
        def request(self, _method: str, _path: str, headers: dict[str, str]) -> None:
            clock[0] = 2.0
            raise OSError("deadline guard closed socket")
        def close(self) -> None:
            raise OSError("already closed")

    deadline_type = getattr(adapter_module, "_Deadline")
    monkeypatch.setattr(adapter_module.socket, "create_connection", lambda *_args, **_kwargs: sock)
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)

    with pytest.raises(TimeoutError):
        _PinnedProviderTransport()(
            adapter_module.Request("https://models.example.test/models"),
            deadline_type(1.0, lambda: clock[0]),
            "93.184.216.34",
            "models.example.test",
        )


def test_proxy_connect_slow_fragments_share_the_provider_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowProxySocket:
        def __init__(self) -> None:
            self.fragments = [b"HTTP/1.1 200 ", b"Connection established\r\n\r\n"]
        def settimeout(self, _timeout: float) -> None: return None
        def sendall(self, _value: bytes) -> None: return None
        def recv(self, _size: int) -> bytes:
            time.sleep(0.06)
            return self.fragments.pop(0)
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: return None

    proxy_socket = SlowProxySocket()
    monkeypatch.setattr(adapter_module.socket, "create_connection", lambda *_args, **_kwargs: proxy_socket)
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        _PinnedProviderTransport(
            "http://proxy.example:8080",
            resolver=lambda _host, _port, _timeout: ["10.0.0.5"],
        )(
            adapter_module.Request("https://models.example.test/models"),
            _deadline(0.1),
            "93.184.216.34",
            "models.example.test",
        )

    assert time.monotonic() - started < 0.25


def test_kubernetes_transport_enforces_one_deadline_across_tls_and_body_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowSocket:
        def settimeout(self, _timeout: float) -> None: return None
        def do_handshake(self) -> None: return None
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: return None

    slow_socket = SlowSocket()

    class Context:
        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            assert do_handshake_on_connect is False
            assert server_hostname == "kubernetes.default.svc"
            time.sleep(0.03)
            return sock

    class Response:
        status = 200
        def read(self, _limit: int) -> bytes:
            time.sleep(0.03)
            return b"{}"

    class Connection:
        def __init__(self, _host: str, _port: int, **_kwargs: object) -> None:
            self.sock: object | None = None
        def request(self, _method: str, _path: str, headers: dict[str, str]) -> None:
            time.sleep(0.03)
        def getresponse(self) -> Response:
            time.sleep(0.03)
            return Response()
        def close(self) -> None: return None

    def slow_connect(_address: object, timeout: float) -> SlowSocket:
        assert 0 < timeout <= 0.1
        time.sleep(0.03)
        return slow_socket

    monkeypatch.setattr(adapter_module.socket, "create_connection", slow_connect)
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda **_kwargs: Context())
    monkeypatch.setattr(adapter_module.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        _KubernetesApiTransport()(
            adapter_module.Request("https://10.96.0.1/api/v1/namespaces/runtime/secrets/provider"),
            _deadline(0.1),
            "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        )

    assert time.monotonic() - started < 0.25


@pytest.mark.parametrize(
    "proxy_url",
    [
        "https://proxy.example:8443",
        "socks5://proxy.example:1080",
        "http://user:password@proxy.example:8080",
        "http://proxy.example:8080/tunnel",
        "http://proxy.example:8080?mode=tunnel",
    ],
)
def test_provider_transport_fails_closed_for_unsupported_proxy_urls(
    monkeypatch: pytest.MonkeyPatch,
    proxy_url: str,
) -> None:
    socket_calls: list[object] = []
    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda *args, **kwargs: socket_calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="unsupported_proxy"):
        _PinnedProviderTransport(proxy_url)(
            adapter_module.Request("https://models.example.test/models"),
            _deadline(5.0),
            "93.184.216.34",
            "models.example.test",
        )

    assert socket_calls == []


def test_http_proxy_uses_connect_to_pinned_ip_before_tls_and_never_receives_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class ProxySocket:
        def __init__(self) -> None:
            self.sent = b""
            self.responses = [b"HTTP/1.1 200 Connection established\r\n\r\n"]

        def sendall(self, value: bytes) -> None:
            self.sent += value

        def recv(self, _size: int) -> bytes:
            return self.responses.pop(0) if self.responses else b""

        def settimeout(self, timeout: float) -> None:
            calls["socket_timeout"] = timeout

        def do_handshake(self) -> None:
            calls["tls_handshake"] = True

        def shutdown(self, _how: int) -> None:
            return None

        def close(self) -> None:
            calls["proxy_closed"] = True

    proxy_socket = ProxySocket()

    class Context:
        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            assert do_handshake_on_connect is False
            calls.update(server_hostname=server_hostname)
            return sock

    class Response:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b"{}"

    class Connection:
        def __init__(self, _host: str, _port: int, timeout: float) -> None:
            self.sock: object | None = None

        def request(self, _method: str, _path: str, headers: dict[str, str]) -> None:
            calls["provider_headers"] = headers

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda address, timeout: calls.update(proxy_address=address, proxy_timeout=timeout) or proxy_socket,
    )
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)

    status, _body = _PinnedProviderTransport(
        "http://proxy.example:8080",
        resolver=lambda _host, _port, _timeout: ["10.0.0.5"],
    )(
        adapter_module.Request(
            "https://models.example.test/models",
            headers={"Host": "models.example.test", "Authorization": "Bearer secret"},
        ),
        _deadline(5.0),
        "93.184.216.34",
        "models.example.test",
    )

    assert status == 200
    assert calls["proxy_address"] == ("10.0.0.5", 8080)
    assert b"CONNECT 93.184.216.34:443" in proxy_socket.sent
    assert b"secret" not in proxy_socket.sent
    assert calls["server_hostname"] == "models.example.test"
    assert calls["provider_headers"] == {
        "Host": "models.example.test",
        "Authorization": "Bearer secret",
    }


def test_proxy_dns_is_resolved_once_and_connects_to_the_first_pinned_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {"resolver": 0}

    class ProxySocket:
        def settimeout(self, _timeout: float) -> None: return None
        def do_handshake(self) -> None: return None
        def sendall(self, _value: bytes) -> None: return None
        def recv(self, _size: int) -> bytes:
            return b"HTTP/1.1 200 Connection established\r\n\r\n"
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: return None

    proxy_socket = ProxySocket()

    def resolver(host: str, port: int, timeout: float) -> list[str]:
        calls["resolver"] = int(calls["resolver"]) + 1
        assert (host, port) == ("proxy.internal", 8080)
        return ["10.0.0.5"] if calls["resolver"] == 1 else ["10.0.0.6"]

    class Context:
        def wrap_socket(
            self,
            sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            assert do_handshake_on_connect is False
            return sock

    class Response:
        status = 200
        def read(self, _limit: int) -> bytes: return b"{}"

    class Connection:
        def __init__(self, _host: str, _port: int, timeout: float) -> None:
            self.sock: object | None = None
        def request(self, _method: str, _path: str, headers: dict[str, str]) -> None: return None
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: return None

    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda address, timeout: calls.update(address=address) or proxy_socket,
    )
    monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(adapter_module.http.client, "HTTPConnection", Connection)

    status, _body = _PinnedProviderTransport(
        "http://proxy.internal:8080", resolver=resolver
    )(
        adapter_module.Request("https://models.example.test/models"),
        _deadline(1.0),
        "93.184.216.34",
        "models.example.test",
    )

    assert status == 200
    assert calls["resolver"] == 1
    assert calls["address"] == ("10.0.0.5", 8080)


def test_slow_proxy_dns_consumes_the_same_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_calls: list[object] = []

    def slow_resolver(_host: str, _port: int, _timeout: float) -> list[str]:
        time.sleep(0.11)
        return ["10.0.0.5"]

    monkeypatch.setattr(
        adapter_module.socket,
        "create_connection",
        lambda *args, **kwargs: socket_calls.append((args, kwargs)),
    )
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        _PinnedProviderTransport(
            "http://proxy.internal:8080", resolver=slow_resolver
        )(
            adapter_module.Request("https://models.example.test/models"),
            _deadline(0.1),
            "93.184.216.34",
            "models.example.test",
        )

    assert time.monotonic() - started < 0.25
    assert socket_calls == []


@pytest.mark.parametrize("transport_kind", ["provider-context", "provider-wrap", "kubernetes-wrap"])
def test_raw_socket_is_closed_when_tls_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
    transport_kind: str,
) -> None:
    class RawSocket:
        def __init__(self) -> None: self.closed = False
        def settimeout(self, _timeout: float) -> None: return None
        def shutdown(self, _how: int) -> None: return None
        def close(self) -> None: self.closed = True

    raw_socket = RawSocket()

    class FailingContext:
        def wrap_socket(
            self,
            _sock: object,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> object:
            assert do_handshake_on_connect is False
            raise RuntimeError("tls setup failed")

    monkeypatch.setattr(adapter_module.socket, "create_connection", lambda *_args, **_kwargs: raw_socket)
    if transport_kind == "provider-context":
        monkeypatch.setattr(
            adapter_module.ssl,
            "create_default_context",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("context failed")),
        )
        transport = _PinnedProviderTransport()
        args = (
            adapter_module.Request("https://models.example.test/models"),
            _deadline(1.0),
            "93.184.216.34",
            "models.example.test",
        )
    elif transport_kind == "provider-wrap":
        monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda **_kwargs: FailingContext())
        transport = _PinnedProviderTransport()
        args = (
            adapter_module.Request("https://models.example.test/models"),
            _deadline(1.0),
            "93.184.216.34",
            "models.example.test",
        )
    else:
        monkeypatch.setattr(adapter_module.ssl, "create_default_context", lambda **_kwargs: FailingContext())
        transport = _KubernetesApiTransport(tls_server_hostname="kubernetes.default.svc")
        args = (
            adapter_module.Request("https://10.96.0.1/api/v1/namespaces/runtime/secrets/provider"),
            _deadline(1.0),
            "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        )

    with pytest.raises(RuntimeError, match="failed"):
        transport(*args)

    assert raw_socket.closed is True


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
