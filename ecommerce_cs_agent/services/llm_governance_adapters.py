from __future__ import annotations

import base64
import binascii
import json
import os
import re
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import psycopg


Transport = Callable[[Request, float, str | None], tuple[int, bytes]]
_SECRET_REF = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")


def _default_transport(request: Request, timeout: float, ca_file: str | None) -> tuple[int, bytes]:
    context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 - validated HTTPS URLs only
        return int(response.status), response.read(1024 * 1024)


class KubernetesSecretProviderConnectionTester:
    """Resolve one Secret value in-cluster, probe a provider, then discard it."""

    def __init__(
        self,
        *,
        kubernetes_host: str,
        kubernetes_port: int,
        service_account_token_file: str,
        kubernetes_ca_file: str,
        transport: Transport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not kubernetes_host or not 1 <= int(kubernetes_port) <= 65535:
            raise RuntimeError("Kubernetes in-cluster host and port are required")
        if not Path(service_account_token_file).is_file() or not Path(kubernetes_ca_file).is_file():
            raise RuntimeError("Kubernetes in-cluster token and CA files are required")
        self._host = kubernetes_host
        self._port = int(kubernetes_port)
        self._token_file = service_account_token_file
        self._ca_file = kubernetes_ca_file
        self._transport = transport or _default_transport
        self._monotonic = monotonic

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        token_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        ca_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        transport: Transport | None = None,
    ) -> "KubernetesSecretProviderConnectionTester":
        env = os.environ if environ is None else environ
        host = env.get("KUBERNETES_SERVICE_HOST", "")
        port = env.get("KUBERNETES_SERVICE_PORT_HTTPS") or env.get("KUBERNETES_SERVICE_PORT") or "0"
        try:
            parsed_port = int(port)
        except ValueError:
            parsed_port = 0
        return cls(
            kubernetes_host=host,
            kubernetes_port=parsed_port,
            service_account_token_file=token_file,
            kubernetes_ca_file=ca_file,
            transport=transport,
        )

    @staticmethod
    def _valid_ref(value: Any) -> bool:
        return isinstance(value, str) and bool(_SECRET_REF.fullmatch(value))

    def _resolve_secret(self, reference: Mapping[str, Any], timeout: float) -> str:
        namespace, name, key = (reference.get(field) for field in ("namespace", "name", "key"))
        if not all(self._valid_ref(value) for value in (namespace, name, key)):
            raise ValueError("invalid_secret_ref")
        token = Path(self._token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("secret_resolution_failed")
        url = (
            f"https://{self._host}:{self._port}/api/v1/namespaces/"
            f"{quote(namespace, safe='')}/secrets/{quote(name, safe='')}"
        )
        request = Request(url, method="GET", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        status, body = self._transport(request, timeout, self._ca_file)
        if status != 200:
            raise RuntimeError("secret_resolution_failed")
        payload = json.loads(body)
        encoded = payload.get("data", {}).get(key)
        if not isinstance(encoded, str) or len(encoded) > 128 * 1024:
            raise RuntimeError("secret_resolution_failed")
        try:
            secret = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise RuntimeError("secret_resolution_failed") from None
        if not secret or len(secret) > 64 * 1024:
            raise RuntimeError("secret_resolution_failed")
        return secret

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, HTTPError):
            if exc.code in {401, 403}:
                return "auth_failed"
            if exc.code == 429:
                return "rate_limited"
            if exc.code >= 500:
                return "provider_unavailable"
            return "invalid_response"
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return "timeout"
        if isinstance(exc, ssl.SSLError):
            return "tls_error"
        if isinstance(exc, URLError):
            if isinstance(exc.reason, socket.gaierror):
                return "dns_error"
            return "connection_failed"
        if isinstance(exc, ValueError) and str(exc) == "invalid_secret_ref":
            return "invalid_response"
        return "connection_failed"

    def __call__(self, provider: dict[str, Any], request_options: dict[str, int]) -> dict[str, Any]:
        started = self._monotonic()
        timeout = float(min(20, max(1, int(request_options.get("timeout_seconds", 20)))))
        try:
            secret = self._resolve_secret(provider.get("secret_ref") or {}, timeout)
            provider_type = str(provider.get("provider_type") or "")
            base_url = str(provider.get("base_url") or "").rstrip("/")
            if not base_url.startswith("https://"):
                raise ValueError("invalid_provider_url")
            headers = {"Accept": "application/json"}
            probe_url = base_url
            if provider_type in {"openai", "openai_compatible"}:
                headers["Authorization"] = f"Bearer {secret}"
                probe_url += "/models"
            elif provider_type == "anthropic":
                headers.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
                probe_url += "/models"
            elif provider_type == "azure_openai":
                headers["api-key"] = secret
            else:
                raise ValueError("invalid_provider_type")
            status, _body = self._transport(Request(probe_url, method="GET", headers=headers), timeout, None)
            if not 200 <= status < 300:
                raise HTTPError(probe_url, status, "provider probe failed", {}, None)
            result_status, error_code = "passed", None
        except Exception as exc:  # all upstream details must stay outside the response
            result_status, error_code = "failed", self._error_code(exc)
        latency_ms = max(0, int((self._monotonic() - started) * 1000))
        return {"status": result_status, "latency_ms": latency_ms, "error_code": error_code}


class PostgresEvaluationReleaseGateChecker:
    def __init__(self, database_url: str, *, connect: Callable[[str], Any] = psycopg.connect) -> None:
        self._database_url = database_url
        self._connect = connect

    def __call__(self, version: dict[str, Any], evaluation_run_id: str) -> dict[str, Any]:
        if version.get("status") != "validated":
            return {"status": "failed", "error_code": "release_gate_failed"}
        try:
            with self._connect(self._database_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT eval.id
                    FROM llm_eval_run AS eval
                    JOIN llm_config_version AS version
                      ON version.id = eval.config_version_id
                     AND version.organization_id = eval.organization_id
                    WHERE eval.id=%s
                      AND eval.organization_id=%s
                      AND eval.config_version_id=%s
                      AND eval.config_revision=%s
                      AND eval.configuration_hash=%s
                      AND version.status='validated'
                      AND version.revision=eval.config_revision
                      AND version.configuration_hash=eval.configuration_hash
                      AND eval.status='completed'
                      AND eval.gate_status='passed'
                      AND eval.red_line_failures=0
                      AND eval.completed_at IS NOT NULL
                      AND eval.completed_at >= eval.created_at
                    """,
                    (
                        evaluation_run_id,
                        version.get("organization_id"),
                        version.get("version_id"),
                        version.get("revision"),
                        version.get("configuration_hash"),
                    ),
                )
                row = cursor.fetchone()
        except Exception:
            row = None
        passed = bool(row)
        return {"status": "passed" if passed else "failed", "error_code": None if passed else "release_gate_failed"}
