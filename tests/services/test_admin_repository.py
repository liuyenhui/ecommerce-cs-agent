from __future__ import annotations

from typing import Any

import pytest

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin import PostgresAdminRepository, admin_repository_for
from ecommerce_cs_agent.services.embeddings import DeterministicEmbeddingProvider
from ecommerce_cs_agent.services.object_storage import (
    FilesystemObjectStorage,
    ObjectStorageError,
    ObjectStorageUnavailable,
    ObjectStorageValidationError,
)


def test_postgres_admin_repository_dual_writes_product_to_canonical_and_compat_tables() -> None:
    connection = _FakeConnection()
    repository = PostgresAdminRepository("postgresql://example", object_storage=_TrackingObjectStorage())
    repository._connect = lambda _url: connection

    product = repository.upsert_product(
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "external_product_id": "sku-001",
            "title": "测试商品",
            "status": "active",
            "attributes": {"color": "red"},
        },
        actor_id="admin-001",
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert product["product_id"].startswith("product-")
    assert "INSERT INTO organization" in executed_sql
    assert "INSERT INTO store" in executed_sql
    assert "INSERT INTO product " in executed_sql
    assert "INSERT INTO app_product" in executed_sql
    assert "INSERT INTO admin_audit_log" in executed_sql
    assert "INSERT INTO app_audit_log" in executed_sql


def test_postgres_admin_repository_accepting_candidate_creates_knowledge_entry_and_audit() -> None:
    connection = _FakeConnection()
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    candidate = repository.review_knowledge_candidate(
        "candidate-001",
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "product_id": "product-001",
            "candidate_text": "材质为棉。",
            "accepted": True,
        },
        actor_id="admin-001",
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert candidate["candidate_id"] == "candidate-001"
    assert candidate["review_status"] == "accepted"
    assert "INSERT INTO product_knowledge_candidate" in executed_sql
    assert "INSERT INTO knowledge_entry" in executed_sql
    assert "INSERT INTO knowledge_embedding" in executed_sql
    assert "INSERT INTO app_knowledge_candidate" in executed_sql
    assert "INSERT INTO admin_audit_log" in executed_sql


def test_postgres_admin_repository_review_reuses_existing_candidate_tenant_and_product() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            [("org-real", "store-real", "product-real", "原候选内容。")],
        ]
    )
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    candidate = repository.review_knowledge_candidate(
        "candidate-001",
        {"action": "approve", "reviewed_content": "审核后内容。", "product_id": "product-wrong"},
        actor_id="admin-001",
    )

    flattened_params = [item for _sql, params in connection.executed for item in params]
    assert candidate["organization_id"] == "org-real"
    assert candidate["store_id"] == "store-real"
    assert candidate["product_id"] == "product-real"
    assert "product-wrong" not in flattened_params
    assert "org-001" not in flattened_params
    assert "store-001" not in flattened_params


def test_in_memory_repository_review_reuses_existing_candidate_context() -> None:
    repository = admin_repository_for(Settings(environment="test", object_storage_backend="memory"))
    product = repository.upsert_product(
        {
            "organization_id": "org-real",
            "store_id": "store-real",
            "external_product_id": "sku-real",
            "title": "真实商品",
        },
        actor_id="admin-001",
    )
    asset = repository.create_asset(
        {
            "organization_id": "org-real",
            "store_id": "store-real",
            "product_id": product["product_id"],
            "asset_type": "manual",
            "file_ref": "object://bucket/manual.pdf",
            "file_hash": "sha256:abc",
            "version": "v1",
        },
        actor_id="admin-001",
    )
    markdown = repository.create_asset_markdown(
        asset["asset_id"],
        {"markdown_text": "材质为棉。", "conversion_status": "converted"},
        actor_id="admin-001",
    )

    candidate = repository.review_knowledge_candidate(
        markdown["candidate_ids"][0],
        {"action": "approve", "reviewed_content": "审核后内容。", "product_id": "product-wrong"},
        actor_id="admin-001",
    )

    assert candidate["organization_id"] == "org-real"
    assert candidate["store_id"] == "store-real"
    assert candidate["product_id"] == product["product_id"]


def test_postgres_admin_repository_rejecting_candidate_does_not_create_embedding() -> None:
    connection = _FakeConnection()
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    candidate = repository.review_knowledge_candidate(
        "candidate-001",
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "product_id": "product-001",
            "candidate_text": "未确认内容。",
            "accepted": False,
        },
        actor_id="admin-001",
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert candidate["review_status"] == "rejected"
    assert "INSERT INTO product_knowledge_candidate" in executed_sql
    assert "INSERT INTO knowledge_entry" not in executed_sql
    assert "INSERT INTO knowledge_embedding" not in executed_sql


def test_postgres_admin_repository_rejecting_candidate_disables_existing_knowledge_entry() -> None:
    connection = _FakeConnection(fetch_rows=[[("org-real", "store-real", "product-real", "原候选内容。")]])
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    repository.review_knowledge_candidate(
        "candidate-001",
        {"action": "reject", "reason": "obsolete"},
        actor_id="admin-001",
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "UPDATE knowledge_entry" in executed_sql
    assert "status = 'disabled'" in executed_sql


def test_postgres_admin_repository_persists_assets_markdown_candidates_and_price_snapshots() -> None:
    connection = _FakeConnection(fetch_rows=[[("org-001", "store-001")]])
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    asset = repository.create_asset(
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "product_id": "product-001",
            "asset_type": "manual",
            "file_ref": "object://bucket/manual.pdf",
            "file_hash": "sha256:abc",
            "version": "v1",
        },
        actor_id="admin-001",
    )
    markdown = repository.create_asset_markdown(
        asset["asset_id"],
        {"markdown_text": "材质为棉。", "conversion_status": "converted"},
        actor_id="admin-001",
    )
    price = repository.create_price_snapshot(
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "product_id": "product-001",
            "current_price": 19.9,
            "currency": "CNY",
            "source": "admin",
            "effective_at": "2026-06-18T00:00:00Z",
            "status": "active",
        },
        actor_id="admin-001",
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert asset["asset_id"].startswith("asset-")
    assert markdown["candidate_ids"][0].startswith("candidate-")
    assert price["price_snapshot_id"].startswith("price-")
    assert "INSERT INTO product_asset" in executed_sql
    assert "object_hash" in executed_sql
    assert "mime_type" in executed_sql
    assert "size_bytes" in executed_sql
    assert "storage_status" in executed_sql
    assert "INSERT INTO product_asset_markdown" in executed_sql
    assert "INSERT INTO product_knowledge_candidate" in executed_sql
    assert "INSERT INTO product_price_snapshot" in executed_sql
    assert "SELECT org.external_organization_id, st.external_store_id" in executed_sql


def test_postgres_admin_repository_redacts_inline_content_from_asset_audit() -> None:
    connection = _FakeConnection()
    repository = PostgresAdminRepository("postgresql://example", object_storage=_TrackingObjectStorage())
    repository._connect = lambda _url: connection

    repository.create_asset(
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "product_id": "product-001",
            "asset_type": "manual",
            "file_ref": "object://bucket/manual.pdf",
            "file_hash": "sha256:abc",
            "version": "v1",
            "content_base64": "bWFudWFs",
        },
        actor_id="admin-001",
    )

    flattened_params = [item for _sql, params in connection.executed for item in params]
    assert "bWFudWFs" not in flattened_params
    assert any(
        getattr(item, "obj", {}).get("content_base64") == "<redacted>"
        for item in flattened_params
        if hasattr(item, "obj")
    )


def test_postgres_admin_repository_surfaces_object_storage_failures_before_db_write() -> None:
    connection = _FakeConnection()
    repository = PostgresAdminRepository("postgresql://example", object_storage=_FailingObjectStorage())
    repository._connect = lambda _url: connection

    with pytest.raises(ObjectStorageError):
        repository.create_asset(
            {
                "organization_id": "org-001",
                "store_id": "store-001",
                "product_id": "product-001",
                "asset_type": "manual",
                "file_ref": "object://bucket/manual.pdf",
                "file_hash": "sha256:abc",
                "version": "v1",
            },
            actor_id="admin-001",
        )

    assert connection.executed == []


def test_postgres_admin_repository_removes_stored_object_when_db_write_fails() -> None:
    connection = _FailingConnection()
    storage = _TrackingObjectStorage()
    repository = PostgresAdminRepository("postgresql://example", object_storage=storage)
    repository._connect = lambda _url: connection

    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.create_asset(
            {
                "organization_id": "org-001",
                "store_id": "store-001",
                "product_id": "product-001",
                "asset_type": "manual",
                "file_ref": "object://bucket/manual.pdf",
                "file_hash": "sha256:abc",
                "version": "v1",
                "content_base64": "bWFudWFs",
            },
            actor_id="admin-001",
        )

    assert storage.deleted == ["object://bucket/manual.pdf"]


def test_deterministic_embedding_provider_is_stable_and_pgvector_compatible() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=8)

    first = provider.embed("材质为棉。")
    second = provider.embed("材质为棉。")

    assert first.model == "deterministic-hash-v1"
    assert first.vector == second.vector
    assert first.to_pgvector().startswith("[")
    assert first.to_pgvector().endswith("]")


def test_admin_repository_for_honors_filesystem_storage_without_database(tmp_path) -> None:
    repository = admin_repository_for(
        Settings(environment="test", object_storage_backend="filesystem", object_storage_root=str(tmp_path))
    )

    asset = repository.create_asset(
        {
            "organization_id": "org-001",
            "store_id": "store-001",
            "product_id": "product-001",
            "asset_type": "manual",
            "file_ref": "manuals/manual.txt",
            "content_base64": "bWFudWFs",
            "version": "v1",
        },
        actor_id="admin-001",
    )

    assert asset["storage_status"] == "stored"
    assert (tmp_path / "manuals" / "manual.txt").read_text() == "manual"


def test_postgres_repository_recalls_only_approved_knowledge_entries() -> None:
    repository = PostgresAdminRepository("postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            [
                (
                    "knowledge-001",
                    "product-001",
                    "product",
                    "材质为棉。",
                    "deterministic-hash-v1",
                    0,
                )
            ]
        ]
    )
    repository._connect = lambda _url: connection

    entries = repository.recall_knowledge("org-001", "store-001", "材质", limit=3)

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert entries == [
        {
            "knowledge_entry_id": "knowledge-001",
            "product_id": "product-001",
            "scope": "product",
            "content": "材质为棉。",
            "embedding_model": "deterministic-hash-v1",
            "chunk_index": 0,
        }
    ]
    assert "entry.status = 'approved'" in executed_sql
    assert "candidate.review_status = 'accepted'" in executed_sql


def test_postgres_admin_repository_reads_canonical_audit_before_compat_audit() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            [
                (
                    "audit-001",
                    "org-001",
                    "store-001",
                    "admin-001",
                    "product.upsert",
                    "product",
                    "product-001",
                    {"reason": "test"},
                    False,
                    "2026-06-18T00:00:00Z",
                )
            ]
        ]
    )
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    logs = repository.list_audit_logs("admin")

    assert logs[0]["id"] == "audit-001"
    assert logs[0]["scope"] == "admin"
    assert logs[0]["actor_id"] == "admin-001"
    assert "FROM admin_audit_log" in connection.executed[0][0]


def test_postgres_admin_repository_product_health_reads_canonical_product_before_compat() -> None:
    connection = _FakeConnection(fetch_rows=[[(True, True)]])
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    health = repository.product_health("product-001")

    assert health["status"] == "healthy"
    assert health["checks"] == [
        {"name": "product_exists", "status": "pass"},
        {"name": "price_snapshot_exists", "status": "pass"},
    ]
    assert "FROM product WHERE public_product_id" in connection.executed[0][0]
    assert not any("FROM app_product" in sql for sql, _params in connection.executed)


def test_postgres_admin_repository_product_health_falls_back_to_compat_product() -> None:
    connection = _FakeConnection(fetch_rows=[[(False, False)], [(1,)]])
    repository = PostgresAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    health = repository.product_health("product-legacy")

    assert health["status"] == "healthy"
    assert health["checks"][0] == {"name": "product_exists", "status": "pass"}
    assert health["checks"][1] == {"name": "price_snapshot_exists", "status": "warning"}
    assert "FROM product WHERE public_product_id" in connection.executed[0][0]
    assert "FROM app_product" in connection.executed[1][0]


class _FakeConnection:
    def __init__(self, fetch_rows: list[list[tuple[Any, ...]]] | None = None) -> None:
        self.fetch_rows = fetch_rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.connection.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        if self.connection.fetch_rows:
            rows = self.connection.fetch_rows.pop(0)
            if rows:
                return rows[0]
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        if self.connection.fetch_rows:
            return self.connection.fetch_rows.pop(0)
        return []


class _FailingObjectStorage:
    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> object:
        raise ObjectStorageUnavailable("object storage unavailable")


class _TrackingObjectStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def put_or_reference(self, *, asset_id: str, payload: dict[str, Any]) -> object:
        from ecommerce_cs_agent.services.object_storage import StoredObject

        return StoredObject(
            object_key=str(payload["file_ref"]),
            object_hash=str(payload["file_hash"]),
            mime_type="text/plain",
            size_bytes=6,
            storage_status="stored",
        )

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


class _FailingConnection:
    def __enter__(self) -> "_FailingConnection":
        raise RuntimeError("database unavailable")

    def __exit__(self, *_exc: object) -> None:
        return None
