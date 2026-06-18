from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit


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
