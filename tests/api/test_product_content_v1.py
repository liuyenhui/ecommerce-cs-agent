from __future__ import annotations

from fastapi.testclient import TestClient

from ecommerce_cs_agent.api.app import create_app


def _admin_cookie(client: TestClient) -> str:
    response = client.post(
        "/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "admin-password"},
    )
    return response.headers["set-cookie"].split(";", 1)[0]


def test_product_asset_markdown_price_snapshot_and_review_flow_are_persisted() -> None:
    client = TestClient(create_app())
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


def test_product_asset_storage_unavailable_returns_503_contract_error() -> None:
    client = TestClient(create_app())
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
    client = TestClient(create_app())
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
