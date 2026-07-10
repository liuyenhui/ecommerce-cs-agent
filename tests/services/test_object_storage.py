from __future__ import annotations

import pytest

from ecommerce_cs_agent.services import object_storage as object_storage_module
from ecommerce_cs_agent.services.object_storage import (
    FilesystemObjectStorage,
    ObjectStorageUnavailable,
    ObjectStorageValidationError,
    ReferenceObjectStorage,
    S3ObjectStorage,
)
from ecommerce_cs_agent.services.product_analysis import OpenAICompatibleProductDocumentAnalyzer


def test_filesystem_object_storage_rejects_path_traversal(tmp_path) -> None:
    storage = FilesystemObjectStorage(str(tmp_path))

    with pytest.raises(ObjectStorageValidationError):
        storage.put_or_reference(
            asset_id="asset-001",
            payload={"file_ref": "../outside.txt", "content_base64": "bWFudWFs"},
        )

    assert not (tmp_path.parent / "outside.txt").exists()


def test_reference_object_storage_rejects_inline_content() -> None:
    storage = ReferenceObjectStorage()

    with pytest.raises(ObjectStorageValidationError, match="content upload requires configured object storage"):
        storage.put_or_reference(
            asset_id="asset-001",
            payload={"file_ref": "object://bucket/manual.pdf", "content_base64": "bWFudWFs"},
        )


def test_reference_object_storage_distinguishes_dependency_unavailable() -> None:
    storage = ReferenceObjectStorage()

    with pytest.raises(ObjectStorageUnavailable):
        storage.put_or_reference(asset_id="asset-001", payload={"file_ref": "fail://bucket/manual.pdf"})


def test_reference_object_storage_rejects_signed_or_credentialed_refs() -> None:
    storage = ReferenceObjectStorage()

    for file_ref in [
        "https://storage.example/manual.pdf?X-Amz-Signature=abc",
        "object://bucket/manual.pdf?token=abc",
        "object://bucket/manual.pdf?credential=abc",
        "https://user:pass@storage.example/manual.pdf",
        "object://access:secret@bucket/manual.pdf",
    ]:
        with pytest.raises(ObjectStorageValidationError):
            storage.put_or_reference(asset_id="asset-001", payload={"file_ref": file_ref})


def test_reference_object_storage_rejects_signed_source_url() -> None:
    storage = ReferenceObjectStorage()

    with pytest.raises(ObjectStorageValidationError, match="source_url"):
        storage.put_or_reference(
            asset_id="asset-001",
            payload={
                "file_ref": "object://bucket/manual.pdf",
                "source_url": "https://storage.example/manual.pdf?X-Amz-Signature=abc",
            },
        )


def test_s3_object_storage_rejects_private_endpoint() -> None:
    with pytest.raises(ObjectStorageValidationError, match="public https"):
        S3ObjectStorage(
            endpoint="http://127.0.0.1:9000",
            bucket="bucket",
            region="us-east-1",
            access_key_id="access",
            secret_access_key="secret",
        )


def test_s3_object_storage_allows_localhost_endpoint_only_in_acs_debug_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACS_DEBUG_MODE", "local-acs")

    storage = S3ObjectStorage(
        endpoint="http://127.0.0.1:19000",
        bucket="bucket",
        region="us-east-1",
        access_key_id="access",
        secret_access_key="secret",
    )

    assert storage.endpoint == "http://127.0.0.1:19000"


def test_s3_object_storage_allows_kubernetes_service_endpoint() -> None:
    storage = S3ObjectStorage(
        endpoint="http://minio.ecommerce-cs-agent-dev.svc.cluster.local:9000",
        bucket="bucket",
        region="us-east-1",
        access_key_id="access",
        secret_access_key="secret",
    )

    assert storage.endpoint == "http://minio.ecommerce-cs-agent-dev.svc.cluster.local:9000"


def test_s3_upload_keeps_object_key_in_request_path_not_connection_target(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    class _Response:
        status = 200

        def read(self) -> bytes:
            return b""

    class _Connection:
        def __init__(self, host: str, port: int | None = None, *, timeout: int) -> None:
            calls.append(("connect", (host, port, timeout)))

        def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
            calls.append(("request", (method, path, body, headers["host"])))

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            calls.append(("close", None))

    monkeypatch.setattr(object_storage_module.http_client, "HTTPSConnection", _Connection)
    storage = S3ObjectStorage(
        endpoint="https://storage.example",
        bucket="bucket",
        region="us-east-1",
        access_key_id="access",
        secret_access_key="secret",
    )

    stored = storage.put_or_reference(
        asset_id="asset-001",
        payload={"file_ref": "products/product-a/manual.pdf", "content_base64": "bWFudWFs"},
    )

    assert stored.storage_status == "stored"
    assert calls[0] == ("connect", ("storage.example", None, 20))
    assert calls[1][0] == "request"
    assert calls[1][1][1] == "/bucket/products/product-a/manual.pdf"


@pytest.mark.parametrize(
    "object_key",
    [
        "products/product-a/manual?redirect=internal",
        "products/product-a/manual#fragment",
        "products/product-a/%2e%2e%2finternal",
        "products/product-a/manual pdf",
        "products//manual.pdf",
    ],
)
def test_s3_upload_rejects_object_keys_outside_the_path_allowlist(object_key: str) -> None:
    storage = S3ObjectStorage(
        endpoint="https://storage.example",
        bucket="bucket",
        region="us-east-1",
        access_key_id="access",
        secret_access_key="secret",
    )

    with pytest.raises(ObjectStorageValidationError, match="invalid object key"):
        storage.put_or_reference(
            asset_id="asset-001",
            payload={"file_ref": object_key, "content_base64": "bWFudWFs"},
        )


def test_llm_analyzer_rejects_private_endpoint() -> None:
    with pytest.raises(ValueError, match="public https"):
        OpenAICompatibleProductDocumentAnalyzer(
            base_url="http://169.254.169.254/latest",
            api_key="key",
            model="model",
        )
