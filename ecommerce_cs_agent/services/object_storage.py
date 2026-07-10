from __future__ import annotations

from dataclasses import dataclass
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from http import client as http_client
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, quote, urlsplit

from ecommerce_cs_agent.services.outbound_http import validate_public_https_url


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorageValidationError(ObjectStorageError):
    pass


class ObjectStorageUnavailable(ObjectStorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    object_hash: str
    mime_type: str
    size_bytes: int | None
    storage_status: str


class ObjectStorage(Protocol):
    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> StoredObject:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


class ReferenceObjectStorage:
    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> StoredObject:
        file_ref = str(payload.get("file_ref", "")).strip()
        if not file_ref:
            raise ObjectStorageValidationError("missing file_ref")
        _ensure_payload_refs(payload)
        if file_ref.startswith("fail://"):
            raise ObjectStorageUnavailable("object storage unavailable")
        if _content_bytes(payload) is not None:
            raise ObjectStorageValidationError("content upload requires configured object storage")
        size_bytes = _size_from_payload(payload)
        return StoredObject(
            object_key=file_ref,
            object_hash=str(payload.get("file_hash", "")),
            mime_type=str(payload.get("mime_type", payload.get("content_type", "application/octet-stream"))),
            size_bytes=size_bytes,
            storage_status="referenced",
        )

    def delete(self, object_key: str) -> None:
        return None


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> StoredObject:
        if str(payload.get("file_ref", "")).startswith("fail://"):
            raise ObjectStorageUnavailable("object storage unavailable")
        _ensure_payload_refs(payload)
        content = _content_bytes(payload)
        if content is None:
            return ReferenceObjectStorage().put_or_reference(asset_id=asset_id, payload=payload)
        object_key = str(payload.get("file_ref") or f"memory://product-assets/{asset_id}")
        self.objects[object_key] = content
        return StoredObject(
            object_key=object_key,
            object_hash=str(payload.get("file_hash") or "sha256:" + hashlib.sha256(content).hexdigest()),
            mime_type=str(payload.get("mime_type", payload.get("content_type", "application/octet-stream"))),
            size_bytes=len(content),
            storage_status="stored",
        )

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


class FilesystemObjectStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> StoredObject:
        if str(payload.get("file_ref", "")).startswith("fail://"):
            raise ObjectStorageUnavailable("object storage unavailable")
        _ensure_payload_refs(payload)
        content = _content_bytes(payload)
        if content is None:
            return ReferenceObjectStorage().put_or_reference(asset_id=asset_id, payload=payload)
        object_key = str(payload.get("file_ref") or f"product-assets/{asset_id}")
        target = self._target_for(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredObject(
            object_key=object_key,
            object_hash=str(payload.get("file_hash") or "sha256:" + hashlib.sha256(content).hexdigest()),
            mime_type=str(payload.get("mime_type", payload.get("content_type", "application/octet-stream"))),
            size_bytes=len(content),
            storage_status="stored",
        )

    def delete(self, object_key: str) -> None:
        try:
            self._target_for(object_key).unlink(missing_ok=True)
        except ObjectStorageValidationError:
            return None

    def _target_for(self, object_key: str) -> Path:
        normalized = object_key.removeprefix("file://")
        relative = Path(normalized)
        if relative.is_absolute() or ".." in relative.parts or any("\x00" in part for part in relative.parts):
            raise ObjectStorageValidationError("invalid object key")
        root = self.root.resolve(strict=False)
        target = (root / relative).resolve(strict=False)
        if not target.is_relative_to(root):
            raise ObjectStorageValidationError("invalid object key")
        return target


class S3ObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        path_style: bool = True,
    ) -> None:
        self.endpoint = _validate_object_storage_endpoint(endpoint)
        self.bucket = bucket
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.path_style = path_style

    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> StoredObject:
        _ensure_payload_refs(payload)
        content = _content_bytes(payload)
        if content is None:
            return ReferenceObjectStorage().put_or_reference(asset_id=asset_id, payload=payload)
        object_key = str(payload.get("file_ref") or f"product-assets/{asset_id}")
        canonical_uri, host, connection_host, connection_port, connection_scheme = self._target_for(object_key)
        payload_hash = hashlib.sha256(content).hexdigest()
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        content_type = str(payload.get("mime_type", payload.get("content_type", "application/octet-stream")))
        headers = {
            "content-type": content_type,
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        canonical_request = "\n".join(["PUT", canonical_uri, "", canonical_headers, signed_headers, payload_hash])
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])
        signature = hmac.new(
            self._signing_key(date_stamp),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        connection_type = http_client.HTTPSConnection if connection_scheme == "https" else http_client.HTTPConnection
        connection = connection_type(connection_host, connection_port, timeout=20)
        try:
            # The connection target is a validated fixed host; canonical_uri contains only a percent-encoded object key.
            connection.request(  # lgtm[py/partial-ssrf]
                "PUT",
                canonical_uri,
                body=content,
                headers={**headers, "Authorization": authorization},
            )
            response = connection.getresponse()
            response.read()
            if response.status < 200 or response.status >= 300:
                raise ObjectStorageUnavailable("object storage is unavailable")
        except (OSError, http_client.HTTPException) as exc:
            raise ObjectStorageUnavailable("object storage is unavailable") from exc
        finally:
            connection.close()
        return StoredObject(
            object_key=object_key,
            object_hash=str(payload.get("file_hash") or "sha256:" + payload_hash),
            mime_type=content_type,
            size_bytes=len(content),
            storage_status="stored",
        )

    def delete(self, object_key: str) -> None:
        return None

    def _target_for(self, object_key: str) -> tuple[str, str, str, int | None, str]:
        _ensure_safe_object_key(object_key)
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ObjectStorageValidationError("invalid object storage endpoint")
        quoted_key = "/".join(quote(part, safe="") for part in object_key.split("/"))
        if self.path_style:
            canonical_uri = f"/{quote(self.bucket, safe='')}/{quoted_key}"
            host = parsed.netloc
            connection_host = parsed.hostname
        else:
            host = f"{self.bucket}.{parsed.netloc}"
            connection_host = f"{self.bucket}.{parsed.hostname}"
            canonical_uri = f"/{quoted_key}"
        return canonical_uri, host, connection_host, parsed.port, parsed.scheme

    def _signing_key(self, date_stamp: str) -> bytes:
        key = ("AWS4" + self.secret_access_key).encode("utf-8")
        for value in (date_stamp, self.region, "s3", "aws4_request"):
            key = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
        return key


def _content_bytes(payload: dict[str, Any]) -> bytes | None:
    if "content_base64" in payload:
        try:
            return base64.b64decode(str(payload["content_base64"]), validate=True)
        except ValueError as exc:
            raise ObjectStorageValidationError("invalid content_base64") from exc
    if "content" in payload:
        return str(payload["content"]).encode("utf-8")
    return None


def _size_from_payload(payload: dict[str, Any]) -> int | None:
    raw = payload.get("size_bytes", payload.get("content_length"))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ObjectStorageValidationError("invalid size_bytes") from exc


def _ensure_payload_refs(payload: dict[str, Any]) -> None:
    for field in ("file_ref", "source_url"):
        value = payload.get(field)
        if value:
            _ensure_public_object_ref(str(value), field)
    file_ref = payload.get("file_ref")
    if file_ref and not urlsplit(str(file_ref)).scheme:
        _ensure_safe_object_key(str(file_ref))


def _ensure_safe_object_key(object_key: str) -> None:
    relative = Path(object_key)
    if relative.is_absolute() or ".." in relative.parts or any("\x00" in part for part in relative.parts):
        raise ObjectStorageValidationError("invalid object key")


def _validate_object_storage_endpoint(endpoint: str) -> str:
    try:
        return validate_public_https_url(endpoint, field="object storage endpoint")
    except ValueError as exc:
        parsed = urlsplit(endpoint.strip())
        if parsed.username or parsed.password:
            raise ObjectStorageValidationError("object storage endpoint must not contain credentials") from exc
        host = (parsed.hostname or "").lower().rstrip(".")
        if _is_local_acs_debug_endpoint(parsed.scheme, host):
            return endpoint.rstrip("/")
        if parsed.scheme in {"http", "https"} and _is_kubernetes_service_host(host):
            return endpoint.rstrip("/")
        raise ObjectStorageValidationError(
            "object storage endpoint must be a public https URL or Kubernetes service URL"
        ) from exc


def _is_local_acs_debug_endpoint(scheme: str, host: str) -> bool:
    return os.environ.get("ACS_DEBUG_MODE") == "local-acs" and scheme == "http" and host in {"127.0.0.1", "localhost", "::1"}


def _is_kubernetes_service_host(host: str) -> bool:
    return host.endswith(".svc") or ".svc." in host


def _ensure_public_object_ref(object_ref: str, field: str) -> None:
    parsed = urlsplit(object_ref)
    if parsed.username or parsed.password:
        raise ObjectStorageValidationError(f"{field} must not contain temporary credentials")
    credential_keys = {
        "access_key",
        "accesskey",
        "awsaccesskeyid",
        "credential",
        "expires",
        "signature",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
        "x-oss-signature",
        "x-oss-security-token",
    }
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in credential_keys:
            raise ObjectStorageValidationError(f"{field} must not contain temporary credentials")
