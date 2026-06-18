from __future__ import annotations

import pytest

from ecommerce_cs_agent.services.object_storage import (
    FilesystemObjectStorage,
    ObjectStorageUnavailable,
    ObjectStorageValidationError,
    ReferenceObjectStorage,
)


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
