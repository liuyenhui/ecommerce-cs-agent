from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app
from tests.admin_fixtures import create_test_app
from ecommerce_cs_agent.core.config import Settings


def _admin_cookie(client: TestClient) -> str:
    response = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    return response.headers["set-cookie"].split(";", 1)[0]


def test_product_asset_markdown_price_snapshot_and_review_flow_are_persisted() -> None:
    client = TestClient(create_test_app())
    cookie = _admin_cookie(client)
    headers = {"Cookie": cookie}

    product_response = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-001",
            "store_id": "store-001",
            "external_product_id": "sku-stage3",
            "title": "阶段三商品",
        },
    )
    product = product_response.json()
    asset = client.post(
        "/v1/product-content/assets",
        headers=headers,
        json={
            "product_id": product["product_id"],
            "asset_type": "manual",
            "file_ref": "object://bucket/manual.pdf",
            "file_hash": "sha256:abc",
            "version": "v1",
            "metadata": {"pages": 2},
        },
    )
    markdown = client.post(
        f"/v1/product-content/assets/{asset.json()['asset_id']}/markdown",
        headers=headers,
        json={
            "markdown_text": "# 说明\n材质为棉。",
            "conversion_status": "converted",
            "source_map": {"page": 1},
        },
    )
    price = client.post(
        "/v1/product-content/price-snapshots",
        headers=headers,
        json={
            "product_id": product["product_id"],
            "store_id": "store-001",
            "source": "admin",
            "current_price": 19.9,
            "currency": "CNY",
            "effective_at": "2026-06-18T00:00:00Z",
            "status": "active",
        },
    )
    review = client.post(
        f"/v1/product-content/knowledge-candidates/{markdown.json()['candidate_ids'][0]}/reviews",
        headers=headers,
        json={"action": "approve", "reviewed_content": "材质为棉。", "reason": "verified", "tags": ["material"]},
    )
    health = client.get(f"/v1/product-content/products/{product['product_id']}/health", headers=headers)

    assert product_response.status_code == 201
    assert asset.status_code == 201
    assert asset.json()["asset_id"].startswith("asset-")
    assert asset.json()["review_status"] == "pending"
    assert asset.json()["object_key"] == "object://bucket/manual.pdf"
    assert asset.json()["object_hash"] == "sha256:abc"
    assert asset.json()["storage_status"] == "referenced"
    assert markdown.status_code == 201
    assert markdown.json()["conversion_status"] == "converted"
    assert markdown.json()["candidate_ids"][0].startswith("candidate-")
    assert price.status_code == 201
    assert price.json()["status"] == "active"
    assert review.status_code == 201
    assert review.json()["knowledge_entry_id"].startswith("knowledge-")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"


def test_product_list_is_scoped_to_current_customer_store() -> None:
    client = TestClient(create_test_app())
    cookie = _admin_cookie(client)
    headers = {"Cookie": cookie}

    first = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-001",
            "store_id": "store-001",
            "external_product_id": "sku-visible",
            "title": "可见商品",
        },
    )
    client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-001",
            "store_id": "store-other",
            "external_product_id": "sku-hidden",
            "title": "其他店铺商品",
        },
    )

    response = client.get("/v1/product-content/products?store_id=store-001", headers=headers)

    assert first.status_code == 201
    assert response.status_code == 200
    assert response.json()["page_info"]["total"] == 1
    assert response.json()["items"] == [
        {
            "product_id": first.json()["product_id"],
            "store_id": "store-001",
            "external_product_id": "sku-visible",
            "title": "可见商品",
            "status": "active",
            "health_status": "healthy",
            "updated_at": response.json()["items"][0]["updated_at"],
        }
    ]


def test_product_import_draft_upload_analyzes_without_creating_product() -> None:
    client = TestClient(create_test_app(Settings(environment="test", object_storage_backend="memory")))
    cookie = _admin_cookie(client)
    headers = {"Cookie": cookie}
    content = "标题: AI 提取商品\n外部商品ID: sku-ai-draft\n材质为棉。"

    response = client.post(
        "/v1/product-content/product-import-drafts",
        headers=headers,
        json={
            "store_id": "store-001",
            "file_name": "manual.txt",
            "mime_type": "text/plain",
            "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "idempotency_key": "draft-upload-001",
        },
    )
    products = client.get("/v1/product-content/products?store_id=store-001", headers=headers)
    audit = client.get("/v1/admin/audit-logs", headers=headers)

    assert response.status_code == 201
    assert response.json()["draft_id"].startswith("draft-")
    assert response.json()["status"] == "draft"
    assert response.json()["analysis_status"] == "fallback"
    assert response.json()["draft_product"]["external_product_id"] == "sku-ai-draft"
    assert response.json()["draft_product"]["title"] == "AI 提取商品"
    assert products.status_code == 200
    assert products.json()["items"] == []
    assert "content_base64" not in str(audit.json()["items"])


def test_product_import_draft_confirm_creates_product_asset_idempotently() -> None:
    client = TestClient(create_test_app(Settings(environment="test", object_storage_backend="memory")))
    cookie = _admin_cookie(client)
    headers = {"Cookie": cookie}
    upload = client.post(
        "/v1/product-content/product-import-drafts",
        headers=headers,
        json={
            "store_id": "store-001",
            "file_name": "manual.txt",
            "mime_type": "text/plain",
            "content_base64": base64.b64encode("标题: 草稿商品\n外部商品ID: sku-confirm".encode("utf-8")).decode("ascii"),
            "idempotency_key": "draft-upload-002",
        },
    )

    first = client.post(
        f"/v1/product-content/product-import-drafts/{upload.json()['draft_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": "confirm-001",
            "draft_product": {
                "external_product_id": "sku-confirm",
                "title": "确认后商品",
                "status": "active",
                "attributes": {"material": "cotton"},
            },
        },
    )
    second = client.post(
        f"/v1/product-content/product-import-drafts/{upload.json()['draft_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": "confirm-001",
            "draft_product": {
                "external_product_id": "sku-confirm",
                "title": "确认后商品",
                "status": "active",
                "attributes": {"material": "cotton"},
            },
        },
    )
    products = client.get("/v1/product-content/products?store_id=store-001", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["product_id"] == first.json()["product_id"]
    assert first.json()["asset_id"].startswith("asset-")
    assert first.json()["analysis_status"] == "fallback"
    assert products.json()["page_info"]["total"] == 1
    assert products.json()["items"][0]["title"] == "确认后商品"


def test_product_asset_storage_unavailable_returns_503_contract_error() -> None:
    client = TestClient(create_test_app())
    cookie = _admin_cookie(client)
    headers = {"Cookie": cookie}

    product = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-001",
            "store_id": "store-001",
            "external_product_id": "sku-storage-failure",
            "title": "存储失败商品",
        },
    ).json()
    response = client.post(
        "/v1/product-content/assets",
        headers=headers,
        json={
            "product_id": product["product_id"],
            "asset_type": "manual",
            "file_ref": "fail://bucket/manual.pdf",
            "file_hash": "sha256:abc",
            "version": "v1",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "object_storage_unavailable"


def test_product_asset_invalid_inline_content_returns_422_contract_error() -> None:
    client = TestClient(create_test_app())
    cookie = _admin_cookie(client)
    headers = {"Cookie": cookie}

    product = client.post(
        "/v1/product-content/products",
        headers=headers,
        json={
            "organization_id": "org-001",
            "store_id": "store-001",
            "external_product_id": "sku-invalid-content",
            "title": "非法内容商品",
        },
    ).json()
    response = client.post(
        "/v1/product-content/assets",
        headers=headers,
        json={
            "product_id": product["product_id"],
            "asset_type": "manual",
            "file_ref": "object://bucket/manual.pdf",
            "content_base64": "not-base64",
            "version": "v1",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "object_storage_error"
