from __future__ import annotations

from typing import Any

from ecommerce_cs_agent.services.admin import PostgresAdminRepository


def test_postgres_admin_repository_dual_writes_product_to_canonical_and_compat_tables() -> None:
    connection = _FakeConnection()
    repository = PostgresAdminRepository("postgresql://example")
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
    assert "INSERT INTO app_knowledge_candidate" in executed_sql
    assert "INSERT INTO admin_audit_log" in executed_sql


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
    assert "INSERT INTO product_asset_markdown" in executed_sql
    assert "INSERT INTO product_knowledge_candidate" in executed_sql
    assert "INSERT INTO product_price_snapshot" in executed_sql
    assert "SELECT org.external_organization_id, st.external_store_id" in executed_sql


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
