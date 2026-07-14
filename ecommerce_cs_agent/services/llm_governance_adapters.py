from __future__ import annotations

import base64
import binascii
import http.client
import ipaddress
import json
import os
import queue
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request

import psycopg


KubernetesTransport = Callable[[Request, "_Deadline", str | None], tuple[int, bytes]]
ProviderTransport = Callable[[Request, "_Deadline", str, str], tuple[int, bytes]]
Resolver = Callable[[str, int, float], list[str]]
_SECRET_REF = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
_SECRET_KEY = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
_MAX_RESPONSE_BYTES = 1024 * 1024


class _SecurityPolicyError(ValueError):
    pass


class _Deadline:
    def __init__(self, end: float, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.end = end
        self._monotonic = monotonic

    def remaining(self) -> float:
        value = self.end - self._monotonic()
        if value <= 0:
            raise TimeoutError
        return value

    def expired(self) -> bool:
        return self.end - self._monotonic() <= 0


class _SocketDeadlineGuard:
    def __init__(self, sock: Any, deadline: _Deadline) -> None:
        self._lock = threading.Lock()
        self._socket = sock
        self.expired = False
        self._timer = threading.Timer(deadline.remaining(), self._expire)
        self._timer.daemon = True
        self._timer.start()

    def replace_socket(self, sock: Any) -> None:
        with self._lock:
            self._socket = sock

    def _expire(self) -> None:
        with self._lock:
            self.expired = True
            sock = self._socket
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except (AttributeError, OSError):
            pass
        try:
            sock.close()
        except (AttributeError, OSError):
            pass

    def cancel(self) -> None:
        self._timer.cancel()


def _contains_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _canonical_origin(value: str, *, require_origin_only: bool) -> str:
    if not isinstance(value, str) or not value or _contains_control(value):
        raise _SecurityPolicyError("invalid_origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port or 443
    except ValueError:
        raise _SecurityPolicyError("invalid_origin") from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not 1 <= port <= 65535
        or (require_origin_only and parsed.path not in {"", "/"})
    ):
        raise _SecurityPolicyError("invalid_origin")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise _SecurityPolicyError("invalid_origin") from None
    authority = f"[{host}]" if ":" in host else host
    if port != 443:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def _bounded_resolver(host: str, port: int, timeout: float) -> list[str]:
    if timeout <= 0:
        raise TimeoutError
    results: queue.Queue[object] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
            results.put(list(addresses))
        except Exception as exc:
            results.put(exc)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        outcome = results.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError from None
    if isinstance(outcome, Exception):
        raise socket.gaierror from None
    return outcome


def _set_deadline_timeout(sock: Any, deadline: _Deadline) -> None:
    sock.settimeout(deadline.remaining())


def _read_bounded(response: http.client.HTTPResponse, deadline: _Deadline, sock: Any) -> bytes:
    read1 = getattr(response, "read1", None)
    if not callable(read1):
        _set_deadline_timeout(sock, deadline)
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        deadline.remaining()
        if len(body) > _MAX_RESPONSE_BYTES:
            raise _SecurityPolicyError("response_too_large")
        return body
    chunks: list[bytes] = []
    total = 0
    while True:
        _set_deadline_timeout(sock, deadline)
        chunk = read1(min(64 * 1024, _MAX_RESPONSE_BYTES + 1 - total))
        deadline.remaining()
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise _SecurityPolicyError("response_too_large")


def _guard_socket(sock: Any, deadline: _Deadline) -> _SocketDeadlineGuard:
    try:
        return _SocketDeadlineGuard(sock, deadline)
    except Exception:
        try:
            sock.close()
        except (AttributeError, OSError):
            pass
        raise


def _safe_close(value: Any) -> None:
    try:
        value.close()
    except (AttributeError, OSError):
        pass


class _KubernetesApiTransport:
    """In-cluster HTTPS only; intentionally has no proxy or redirect support."""

    def __call__(self, request: Request, deadline: _Deadline, ca_file: str | None) -> tuple[int, bytes]:
        parsed = urlsplit(request.full_url)
        if parsed.scheme != "https" or not parsed.hostname or not ca_file:
            raise _SecurityPolicyError("invalid_kubernetes_request")
        context = ssl.create_default_context(cafile=ca_file)
        port = parsed.port or 443
        raw_socket = socket.create_connection((parsed.hostname, port), timeout=deadline.remaining())
        guard = _guard_socket(raw_socket, deadline)
        connection: http.client.HTTPConnection | None = None
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        try:
            _set_deadline_timeout(raw_socket, deadline)
            tls_socket = context.wrap_socket(raw_socket, server_hostname=parsed.hostname)
            deadline.remaining()
            guard.replace_socket(tls_socket)
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=deadline.remaining())
            connection.sock = tls_socket
            _set_deadline_timeout(tls_socket, deadline)
            connection.request("GET", path, headers=dict(request.header_items()))
            deadline.remaining()
            _set_deadline_timeout(tls_socket, deadline)
            response = connection.getresponse()
            deadline.remaining()
            return int(response.status), _read_bounded(response, deadline, tls_socket)
        except Exception:
            if deadline.expired() or guard.expired:
                raise TimeoutError from None
            raise
        finally:
            guard.cancel()
            if connection is not None:
                _safe_close(connection)


def _proxy_tunnel_socket(
    proxy_url: str,
    pinned_ip: str,
    port: int,
    deadline: _Deadline,
) -> tuple[socket.socket, _SocketDeadlineGuard]:
    try:
        proxy = urlsplit(proxy_url)
        proxy_port = proxy.port or 80
    except ValueError:
        raise _SecurityPolicyError("unsupported_proxy") from None
    if (
        _contains_control(proxy_url)
        or proxy.scheme.lower() != "http"
        or not proxy.hostname
        or proxy.username is not None
        or proxy.password is not None
        or proxy.path not in {"", "/"}
        or proxy.query
        or proxy.fragment
        or not 1 <= proxy_port <= 65535
    ):
        raise _SecurityPolicyError("unsupported_proxy")
    sock = socket.create_connection((proxy.hostname, proxy_port), timeout=deadline.remaining())
    guard = _guard_socket(sock, deadline)
    authority = f"[{pinned_ip}]:{port}" if ":" in pinned_ip else f"{pinned_ip}:{port}"
    request = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n\r\n"
    try:
        _set_deadline_timeout(sock, deadline)
        sock.sendall(request.encode("ascii"))
        deadline.remaining()
        response = bytearray()
        while b"\r\n\r\n" not in response and len(response) <= 16 * 1024:
            _set_deadline_timeout(sock, deadline)
            chunk = sock.recv(4096)
            deadline.remaining()
            if not chunk:
                break
            response.extend(chunk)
        status_line = bytes(response).split(b"\r\n", 1)[0]
        if not status_line.startswith(b"HTTP/") or b" 200 " not in status_line:
            raise _SecurityPolicyError("proxy_connect_failed")
        return sock, guard
    except Exception:
        guard.cancel()
        _safe_close(sock)
        if deadline.expired() or guard.expired:
            raise TimeoutError from None
        raise


class _PinnedProviderTransport:
    """HTTPS transport pinned to a prevalidated IP with original-host TLS SNI."""

    def __init__(self, proxy_url: str | None = None) -> None:
        self._proxy_url = proxy_url.strip() if proxy_url else None

    def __call__(
        self,
        request: Request,
        deadline: _Deadline,
        pinned_ip: str,
        server_hostname: str,
    ) -> tuple[int, bytes]:
        parsed = urlsplit(request.full_url)
        port = parsed.port or 443
        if parsed.scheme != "https":
            raise _SecurityPolicyError("invalid_provider_request")
        if self._proxy_url:
            raw_socket, guard = _proxy_tunnel_socket(
                self._proxy_url, pinned_ip, port, deadline
            )
        else:
            raw_socket = socket.create_connection(
                (pinned_ip, port), timeout=deadline.remaining()
            )
            guard = _guard_socket(raw_socket, deadline)
        connection: http.client.HTTPConnection | None = None
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        try:
            context = ssl.create_default_context()
            _set_deadline_timeout(raw_socket, deadline)
            tls_socket = context.wrap_socket(raw_socket, server_hostname=server_hostname)
            deadline.remaining()
            guard.replace_socket(tls_socket)
            connection = http.client.HTTPConnection(
                pinned_ip, port, timeout=deadline.remaining()
            )
            connection.sock = tls_socket
            _set_deadline_timeout(tls_socket, deadline)
            connection.request("GET", path, headers=dict(request.header_items()))
            deadline.remaining()
            _set_deadline_timeout(tls_socket, deadline)
            response = connection.getresponse()
            deadline.remaining()
            return int(response.status), _read_bounded(response, deadline, tls_socket)
        except Exception:
            if deadline.expired() or guard.expired:
                raise TimeoutError from None
            raise
        finally:
            guard.cancel()
            if connection is not None:
                _safe_close(connection)


class KubernetesSecretProviderConnectionTester:
    """Resolve one Secret value in-cluster, probe a provider, then discard it."""

    def __init__(
        self,
        *,
        kubernetes_host: str,
        kubernetes_port: int,
        service_account_token_file: str,
        kubernetes_ca_file: str,
        allowed_namespace: str,
        allowed_secret_origins: Mapping[tuple[str, str], set[str] | frozenset[str]],
        kubernetes_transport: KubernetesTransport | None = None,
        provider_transport: ProviderTransport | None = None,
        resolver: Resolver = _bounded_resolver,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not kubernetes_host or not 1 <= int(kubernetes_port) <= 65535:
            raise RuntimeError("Kubernetes in-cluster host and port are required")
        if not Path(service_account_token_file).is_file() or not Path(kubernetes_ca_file).is_file():
            raise RuntimeError("Kubernetes in-cluster token and CA files are required")
        if not self._valid_ref(allowed_namespace) or not allowed_secret_origins:
            raise RuntimeError("Kubernetes namespace and Secret allowlist are required")
        canonical_bindings: dict[tuple[str, str], frozenset[str]] = {}
        try:
            for ref, origins in allowed_secret_origins.items():
                if (
                    not isinstance(ref, tuple)
                    or len(ref) != 2
                    or not self._valid_ref(ref[0])
                    or not self._valid_secret_key(ref[1])
                    or not origins
                ):
                    raise RuntimeError
                canonical_bindings[ref] = frozenset(
                    _canonical_origin(origin, require_origin_only=True) for origin in origins
                )
        except (RuntimeError, _SecurityPolicyError, TypeError):
            raise RuntimeError("Kubernetes Secret origin bindings are required") from None
        self._host = kubernetes_host
        self._port = int(kubernetes_port)
        self._token_file = service_account_token_file
        self._ca_file = kubernetes_ca_file
        self._allowed_namespace = allowed_namespace
        self._allowed_secret_origins = canonical_bindings
        self._kubernetes_transport = kubernetes_transport or _KubernetesApiTransport()
        self._provider_transport = provider_transport or _PinnedProviderTransport()
        self._resolver = resolver
        self._monotonic = monotonic

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        token_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        ca_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        namespace_file: str = "/var/run/secrets/kubernetes.io/serviceaccount/namespace",
        kubernetes_transport: KubernetesTransport | None = None,
        provider_transport: ProviderTransport | None = None,
        resolver: Resolver = _bounded_resolver,
    ) -> "KubernetesSecretProviderConnectionTester":
        env = os.environ if environ is None else environ
        host = env.get("KUBERNETES_SERVICE_HOST", "")
        port = env.get("KUBERNETES_SERVICE_PORT_HTTPS") or env.get("KUBERNETES_SERVICE_PORT") or "0"
        try:
            parsed_port = int(port)
        except ValueError:
            parsed_port = 0
        namespace = env.get("LLM_GOVERNANCE_SECRET_NAMESPACE", "").strip()
        if not namespace and Path(namespace_file).is_file():
            namespace = Path(namespace_file).read_text(encoding="utf-8").strip()
        allowed_secret_origins = cls._parse_allowed_secret_refs(
            env.get("LLM_GOVERNANCE_ALLOWED_SECRET_REFS", "")
        )
        runtime_ref = cls._parse_runtime_secret_ref(
            env.get("LLM_GOVERNANCE_RUNTIME_LLM_SECRET_REF", "")
        )
        runtime_base_url = env.get("LLM_BASE_URL", "").strip()
        if runtime_ref and runtime_ref in allowed_secret_origins and runtime_base_url:
            allowed_secret_origins[runtime_ref].add(
                _canonical_origin(runtime_base_url, require_origin_only=False)
            )
        proxy_url = env.get("HTTPS_PROXY") or env.get("https_proxy")
        return cls(
            kubernetes_host=host,
            kubernetes_port=parsed_port,
            service_account_token_file=token_file,
            kubernetes_ca_file=ca_file,
            allowed_namespace=namespace,
            allowed_secret_origins=allowed_secret_origins,
            kubernetes_transport=kubernetes_transport,
            provider_transport=provider_transport or _PinnedProviderTransport(proxy_url),
            resolver=resolver,
        )

    @staticmethod
    def _valid_ref(value: Any) -> bool:
        return isinstance(value, str) and bool(_SECRET_REF.fullmatch(value))

    @staticmethod
    def _valid_secret_key(value: Any) -> bool:
        return isinstance(value, str) and bool(_SECRET_KEY.fullmatch(value))

    @classmethod
    def _parse_allowed_secret_refs(cls, raw_value: str) -> dict[tuple[str, str], set[str]]:
        if not raw_value.strip():
            return {}
        try:
            entries = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError("Kubernetes namespace and Secret allowlist are required") from None
        if not isinstance(entries, list):
            raise RuntimeError("Kubernetes namespace and Secret allowlist are required")
        if not entries:
            return {}

        refs: dict[tuple[str, str], set[str]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"name", "keys"}:
                raise RuntimeError("Kubernetes namespace and Secret allowlist are required")
            name, keys = entry["name"], entry["keys"]
            if not cls._valid_ref(name) or not isinstance(keys, list) or not keys:
                raise RuntimeError("Kubernetes namespace and Secret allowlist are required")
            for key_entry in keys:
                if not isinstance(key_entry, dict) or set(key_entry) != {"key", "allowedOrigins"}:
                    raise RuntimeError("Kubernetes namespace and Secret allowlist are required")
                key, origins = key_entry["key"], key_entry["allowedOrigins"]
                if not cls._valid_secret_key(key) or not isinstance(origins, list):
                    raise RuntimeError("Kubernetes namespace and Secret allowlist are required")
                refs[(name, key)] = set(origins)
        return refs

    @classmethod
    def _parse_runtime_secret_ref(cls, raw_value: str) -> tuple[str, str] | None:
        if not raw_value.strip():
            return None
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError("Kubernetes runtime LLM Secret reference is invalid") from None
        if (
            not isinstance(value, dict)
            or set(value) != {"name", "key"}
            or not cls._valid_ref(value["name"])
            or not cls._valid_secret_key(value["key"])
        ):
            raise RuntimeError("Kubernetes runtime LLM Secret reference is invalid")
        return value["name"], value["key"]

    def _resolve_secret(self, reference: Mapping[str, Any], deadline: _Deadline) -> str:
        namespace, name, key = (reference.get(field) for field in ("namespace", "name", "key"))
        if (
            not self._valid_ref(namespace)
            or not self._valid_ref(name)
            or not self._valid_secret_key(key)
        ):
            raise ValueError("invalid_secret_ref")
        if namespace != self._allowed_namespace or (name, key) not in self._allowed_secret_origins:
            raise ValueError("secret_access_denied")
        token = Path(self._token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("secret_resolution_failed")
        url = (
            f"https://{self._host}:{self._port}/api/v1/namespaces/"
            f"{quote(namespace, safe='')}/secrets/{quote(name, safe='')}"
        )
        request = Request(url, method="GET", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        status, body = self._kubernetes_transport(request, deadline, self._ca_file)
        deadline.remaining()
        if 300 <= status < 400:
            raise _SecurityPolicyError("kubernetes_redirect_forbidden")
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
        if not secret or len(secret) > 64 * 1024 or _contains_control(secret):
            raise RuntimeError("secret_resolution_failed")
        return secret

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, _SecurityPolicyError):
            return "invalid_response"
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
        if isinstance(exc, ValueError) and str(exc) in {"invalid_secret_ref", "secret_access_denied"}:
            return "invalid_response"
        return "connection_failed"

    def _provider_endpoint(self, provider: Mapping[str, Any]) -> tuple[str, str, int, str, str]:
        base_url = str(provider.get("base_url") or "").rstrip("/")
        origin = _canonical_origin(base_url, require_origin_only=False)
        parsed = urlsplit(base_url)
        host = parsed.hostname.encode("idna").decode("ascii").lower() if parsed.hostname else ""
        port = parsed.port or 443
        if host == self._host.lower():
            raise _SecurityPolicyError("kubernetes_origin_forbidden")
        authority = f"[{host}]" if ":" in host else host
        if port != 443:
            authority = f"{authority}:{port}"
        canonical_base = f"https://{authority}{parsed.path}"
        provider_type = str(provider.get("provider_type") or "")
        if provider_type in {"openai", "openai_compatible", "anthropic"}:
            probe_url = f"{canonical_base}/models"
        elif provider_type == "azure_openai":
            if not canonical_base.endswith("/openai/v1"):
                canonical_base += "/openai/v1"
            probe_url = f"{canonical_base}/models"
        else:
            raise _SecurityPolicyError("invalid_provider_type")
        host_header = authority
        return origin, host, port, host_header, probe_url

    def _resolve_public_provider_ip(self, host: str, port: int, timeout: float) -> str:
        if timeout <= 0:
            raise TimeoutError
        addresses = self._resolver(host, port, timeout)
        if not addresses:
            raise _SecurityPolicyError("public_address_required")
        parsed_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        try:
            parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
        except ValueError:
            raise _SecurityPolicyError("public_address_required") from None
        try:
            kubernetes_ip = ipaddress.ip_address(self._host)
        except ValueError:
            kubernetes_ip = None
        if any(not address.is_global or address == kubernetes_ip for address in parsed_addresses):
            raise _SecurityPolicyError("public_address_required")
        return str(parsed_addresses[0])

    def __call__(self, provider: dict[str, Any], request_options: dict[str, int]) -> dict[str, Any]:
        started = self._monotonic()
        timeout = float(min(20, max(1, int(request_options.get("timeout_seconds", 20)))))
        deadline = _Deadline(started + timeout, self._monotonic)

        try:
            reference = provider.get("secret_ref") or {}
            namespace, name, key = (reference.get(field) for field in ("namespace", "name", "key"))
            if (
                not self._valid_ref(namespace)
                or not self._valid_ref(name)
                or not self._valid_secret_key(key)
                or namespace != self._allowed_namespace
            ):
                raise _SecurityPolicyError("secret_reference_forbidden")
            origin, host, port, host_header, probe_url = self._provider_endpoint(provider)
            allowed_origins = self._allowed_secret_origins.get((name, key), frozenset())
            if origin not in allowed_origins:
                raise _SecurityPolicyError("origin_binding_mismatch")
            pinned_ip = self._resolve_public_provider_ip(host, port, deadline.remaining())
            secret = self._resolve_secret(reference, deadline)
            provider_type = str(provider.get("provider_type") or "")
            headers = {"Accept": "application/json", "Host": host_header}
            if provider_type in {"openai", "openai_compatible"}:
                headers["Authorization"] = f"Bearer {secret}"
            elif provider_type == "anthropic":
                headers.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
            elif provider_type == "azure_openai":
                headers["api-key"] = secret
            else:
                raise _SecurityPolicyError("invalid_provider_type")
            status, _body = self._provider_transport(
                Request(probe_url, method="GET", headers=headers),
                deadline,
                pinned_ip,
                host,
            )
            deadline.remaining()
            if 300 <= status < 400:
                raise _SecurityPolicyError("provider_redirect_forbidden")
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
