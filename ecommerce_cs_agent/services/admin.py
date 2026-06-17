from __future__ import annotations

import uuid
from datetime import datetime, timezone
import hashlib
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.core.config import Settings


class AdminRepository(Protocol):
    def upsert_product(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def review_knowledge_candidate(self, candidate_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_asset(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_asset_markdown(self, asset_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_price_snapshot(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def list_audit_logs(self, scope: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def product_health(self, product_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def system_health(self) -> dict[str, Any]:
        raise NotImplementedError

    def store_readiness(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.products: dict[str, dict[str, Any]] = {}
        self.assets: dict[str, dict[str, Any]] = {}
        self.markdowns: dict[str, dict[str, Any]] = {}
        self.price_snapshots: dict[str, dict[str, Any]] = {}
        self.knowledge_candidates: dict[str, dict[str, Any]] = {}
        self.audit_logs: list[dict[str, Any]] = []

    def upsert_product(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product = _product_from_payload(payload)
        self.products[product["product_id"]] = product
        self._audit("admin", product["organization_id"], product["store_id"], actor_id, "product.upsert", "product", product["product_id"], payload)
        return product

    def review_knowledge_candidate(self, candidate_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        accepted = payload.get("accepted")
        if accepted is None:
            accepted = payload.get("action", "approve") == "approve"
        candidate = {
            "candidate_id": candidate_id,
            "organization_id": payload.get("organization_id", "org-001"),
            "store_id": payload.get("store_id", "store-001"),
            "product_id": payload.get("product_id"),
            "candidate_text": payload.get("reviewed_content", payload.get("candidate_text", "")),
            "review_status": "accepted" if accepted else "rejected",
            "source_payload": payload,
            "reviewed_at": _now(),
            "knowledge_entry_id": f"knowledge-{candidate_id}" if accepted else None,
        }
        self.knowledge_candidates[candidate_id] = candidate
        self._audit("admin", candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, payload)
        return candidate

    def create_asset(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product = self.products.get(str(payload.get("product_id")))
        organization_id = product["organization_id"] if product else str(payload.get("organization_id", "org-001"))
        store_id = product["store_id"] if product else str(payload.get("store_id", "store-001"))
        asset_id = f"asset-{_stable_product_suffix(organization_id, store_id, str(payload.get('file_hash', payload.get('file_ref', 'asset'))))}"
        asset = {
            "asset_id": asset_id,
            "product_id": str(payload.get("product_id")),
            "organization_id": organization_id,
            "store_id": store_id,
            "asset_type": str(payload.get("asset_type", "other")),
            "file_ref": str(payload.get("file_ref", "")),
            "file_hash": str(payload.get("file_hash", "")),
            "version": str(payload.get("version", "v1")),
            "review_status": "pending",
            "metadata": payload.get("metadata", {}),
        }
        self.assets[asset_id] = asset
        self._audit("admin", organization_id, store_id, actor_id, "product_asset.create", "product_asset", asset_id, payload)
        return asset

    def create_asset_markdown(self, asset_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        asset = self.assets.get(asset_id)
        if not asset:
            raise KeyError("asset not found")
        markdown_id = f"markdown-{asset_id.removeprefix('asset-')}"
        candidate_id = f"candidate-{asset_id.removeprefix('asset-')}"
        markdown = {
            "markdown_id": markdown_id,
            "asset_id": asset_id,
            "conversion_status": str(payload.get("conversion_status", "converted")),
            "markdown_text": str(payload.get("markdown_text", "")),
            "candidate_ids": [candidate_id],
        }
        self.markdowns[markdown_id] = markdown
        self.knowledge_candidates[candidate_id] = {
            "candidate_id": candidate_id,
            "organization_id": asset["organization_id"],
            "store_id": asset["store_id"],
            "product_id": asset["product_id"],
            "candidate_text": markdown["markdown_text"],
            "review_status": "pending",
            "source_payload": payload,
            "reviewed_at": None,
        }
        self._audit("admin", asset["organization_id"], asset["store_id"], actor_id, "product_asset.markdown.create", "product_asset_markdown", markdown_id, payload)
        return markdown

    def create_price_snapshot(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product_id = str(payload.get("product_id"))
        product = self.products.get(product_id)
        organization_id = product["organization_id"] if product else str(payload.get("organization_id", "org-001"))
        store_id = str(payload.get("store_id", product["store_id"] if product else "store-001"))
        snapshot_id = f"price-{_stable_product_suffix(organization_id, store_id, product_id + str(payload.get('effective_at', '')))}"
        snapshot = {
            "price_snapshot_id": snapshot_id,
            "product_id": product_id,
            "sku_id": payload.get("sku_id"),
            "status": str(payload.get("status", "active")),
            "current_price": payload.get("current_price"),
            "currency": payload.get("currency", "CNY"),
        }
        self.price_snapshots[snapshot_id] = snapshot
        self._audit("admin", organization_id, store_id, actor_id, "price_snapshot.create", "product_price_snapshot", snapshot_id, payload)
        return snapshot

    def list_audit_logs(self, scope: str) -> list[dict[str, Any]]:
        return [item for item in self.audit_logs if item["scope"] == scope]

    def product_health(self, product_id: str) -> dict[str, Any]:
        product = self.products.get(product_id)
        has_active_price = any(item["product_id"] == product_id and item["status"] == "active" for item in self.price_snapshots.values())
        return {
            "product_id": product_id,
            "status": "healthy" if product else "warning",
            "checks": [
                {"name": "product_exists", "status": "pass" if product else "warning"},
                {"name": "active_price_snapshot", "status": "pass" if has_active_price else "warning"},
            ],
        }

    def system_health(self) -> dict[str, Any]:
        return _system_health("degraded", "in-memory repository")

    def store_readiness(self) -> list[dict[str, Any]]:
        has_product = bool(self.products)
        return [_readiness_item("ready" if has_product else "blocked", has_product)]

    def _audit(
        self,
        scope: str,
        organization_id: str | None,
        store_id: str | None,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> None:
        self.audit_logs.insert(
            0,
            _audit_log(scope, organization_id, store_id, actor_id, action, object_type, object_id, diff_summary),
        )


class PostgresAdminRepository:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url

    def upsert_product(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product = _product_from_payload(payload)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._upsert_tenant_store(cur, product["organization_id"], product["store_id"], str(payload.get("platform", "pdd")))
                cur.execute(
                    """
                    INSERT INTO product (
                        public_product_id, organization_id, store_id, external_product_id,
                        title, status, attributes
                    )
                    VALUES (
                        %s,
                        (SELECT id FROM organization WHERE external_organization_id = %s),
                        (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                          WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (organization_id, store_id, external_product_id)
                    DO UPDATE SET
                        public_product_id = EXCLUDED.public_product_id,
                        title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        attributes = EXCLUDED.attributes,
                        updated_at = now()
                    """,
                    (
                        product["product_id"],
                        product["organization_id"],
                        product["organization_id"],
                        product["store_id"],
                        product["external_product_id"],
                        product["title"],
                        product["status"],
                        Jsonb(product["attributes"]),
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO app_product (
                        product_id, organization_id, store_id, external_product_id,
                        title, status, attributes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (organization_id, store_id, external_product_id)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        attributes = EXCLUDED.attributes,
                        updated_at = now()
                    RETURNING product_id, organization_id, store_id, external_product_id, title, status, attributes
                    """,
                    (
                        product["product_id"],
                        product["organization_id"],
                        product["store_id"],
                        product["external_product_id"],
                        product["title"],
                        product["status"],
                        Jsonb(product["attributes"]),
                    ),
                )
                row = cur.fetchone()
                saved = _product_from_row(row) if row else product
                self._canonical_audit(cur, saved["organization_id"], saved["store_id"], actor_id, "product.upsert", "product", saved["product_id"], payload)
                self._audit(cur, "admin", saved["organization_id"], saved["store_id"], actor_id, "product.upsert", "product", saved["product_id"], payload)
                return saved

    def review_knowledge_candidate(self, candidate_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        status = "accepted" if payload.get("accepted", True) else "rejected"
        organization_id = str(payload.get("organization_id", "org-001"))
        store_id = str(payload.get("store_id", "store-001"))
        product_id = payload.get("product_id")
        candidate_text = str(payload.get("candidate_text", ""))
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._upsert_tenant_store(cur, organization_id, store_id, str(payload.get("platform", "pdd")))
                cur.execute(
                    """
                    INSERT INTO product_knowledge_candidate (
                        public_candidate_id, organization_id, store_id, product_id,
                        source_type, source_ref, candidate_text, review_status
                    )
                    VALUES (
                        %s,
                        (SELECT id FROM organization WHERE external_organization_id = %s),
                        (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                          WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                        (SELECT id FROM product WHERE public_product_id = %s),
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (public_candidate_id) WHERE public_candidate_id IS NOT NULL
                    DO UPDATE SET
                        candidate_text = EXCLUDED.candidate_text,
                        review_status = EXCLUDED.review_status
                    """,
                    (
                        candidate_id,
                        organization_id,
                        organization_id,
                        store_id,
                        product_id,
                        str(payload.get("source_type", "admin")),
                        str(payload.get("source_ref", candidate_id)),
                        candidate_text,
                        status,
                    ),
                )
                if status == "accepted":
                    cur.execute(
                        """
                        INSERT INTO knowledge_entry (
                            organization_id, store_id, product_id, source_product_candidate_id,
                            scope, title, content, source_type, metadata, status
                        )
                        VALUES (
                            (SELECT id FROM organization WHERE external_organization_id = %s),
                            (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                              WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                            (SELECT id FROM product WHERE public_product_id = %s),
                            (SELECT id FROM product_knowledge_candidate WHERE public_candidate_id = %s),
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            'approved'
                        )
                        ON CONFLICT (organization_id, store_id, source_product_candidate_id)
                        DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            status = 'approved',
                            updated_at = now()
                        """,
                        (
                            organization_id,
                            organization_id,
                            store_id,
                            product_id,
                            candidate_id,
                            str(payload.get("scope", "product")),
                            str(payload.get("title", "")),
                            candidate_text,
                            str(payload.get("source_type", "admin")),
                            Jsonb(payload),
                        ),
                    )
                cur.execute(
                    """
                    INSERT INTO app_knowledge_candidate (
                        candidate_id, organization_id, store_id, product_id,
                        candidate_text, review_status, source_payload, reviewed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (candidate_id)
                    DO UPDATE SET
                        review_status = EXCLUDED.review_status,
                        source_payload = EXCLUDED.source_payload,
                        reviewed_at = now()
                    RETURNING candidate_id, organization_id, store_id, product_id, candidate_text, review_status, source_payload, reviewed_at
                    """,
                    (
                        candidate_id,
                        organization_id,
                        store_id,
                        product_id,
                        candidate_text,
                        status,
                        Jsonb(payload),
                    ),
                )
                row = cur.fetchone()
                candidate = _candidate_from_row(row) if row else {
                    "candidate_id": candidate_id,
                    "organization_id": organization_id,
                    "store_id": store_id,
                    "product_id": product_id,
                    "candidate_text": candidate_text,
                    "review_status": status,
                    "source_payload": payload,
                    "reviewed_at": _now(),
                }
                self._canonical_audit(cur, candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, payload)
                self._audit(cur, "admin", candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, payload)
                return candidate

    def create_asset(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product_id = str(payload.get("product_id"))
        organization_id = str(payload.get("organization_id", "org-001"))
        store_id = str(payload.get("store_id", "store-001"))
        asset_id = f"asset-{_stable_product_suffix(organization_id, store_id, str(payload.get('file_hash', payload.get('file_ref', 'asset'))))}"
        asset = {
            "asset_id": asset_id,
            "product_id": product_id,
            "organization_id": organization_id,
            "store_id": store_id,
            "asset_type": str(payload.get("asset_type", "other")),
            "file_ref": str(payload.get("file_ref", "")),
            "file_hash": str(payload.get("file_hash", "")),
            "version": str(payload.get("version", "v1")),
            "review_status": "pending",
            "metadata": payload.get("metadata", {}),
        }
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._upsert_tenant_store(cur, organization_id, store_id, str(payload.get("platform", "pdd")))
                cur.execute(
                    """
                    INSERT INTO product_asset (
                        public_asset_id, organization_id, store_id, product_id,
                        asset_type, object_key, source_url, metadata
                    )
                    VALUES (
                        %s,
                        (SELECT id FROM organization WHERE external_organization_id = %s),
                        (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                          WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                        (SELECT id FROM product WHERE public_product_id = %s),
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (public_asset_id) WHERE public_asset_id IS NOT NULL
                    DO UPDATE SET metadata = EXCLUDED.metadata
                    """,
                    (
                        asset_id,
                        organization_id,
                        organization_id,
                        store_id,
                        product_id,
                        asset["asset_type"],
                        asset["file_ref"],
                        payload.get("source_url"),
                        Jsonb({**asset["metadata"], "file_hash": asset["file_hash"], "version": asset["version"]}),
                    ),
                )
                self._canonical_audit(cur, organization_id, store_id, actor_id, "product_asset.create", "product_asset", asset_id, payload)
        return asset

    def create_asset_markdown(self, asset_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        markdown_id = f"markdown-{asset_id.removeprefix('asset-')}"
        candidate_id = f"candidate-{asset_id.removeprefix('asset-')}"
        markdown = {
            "markdown_id": markdown_id,
            "asset_id": asset_id,
            "conversion_status": str(payload.get("conversion_status", "converted")),
            "markdown_text": str(payload.get("markdown_text", "")),
            "candidate_ids": [candidate_id],
        }
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO product_asset_markdown (
                        organization_id, store_id, product_asset_id, markdown, review_status
                    )
                    VALUES (
                        (SELECT organization_id FROM product_asset WHERE public_asset_id = %s),
                        (SELECT store_id FROM product_asset WHERE public_asset_id = %s),
                        (SELECT id FROM product_asset WHERE public_asset_id = %s),
                        %s,
                        'pending'
                    )
                    ON CONFLICT (product_asset_id)
                    DO UPDATE SET markdown = EXCLUDED.markdown, review_status = EXCLUDED.review_status
                    """,
                    (asset_id, asset_id, asset_id, markdown["markdown_text"]),
                )
                cur.execute(
                    """
                    INSERT INTO product_knowledge_candidate (
                        public_candidate_id, organization_id, store_id, product_id,
                        source_type, source_ref, candidate_text, review_status
                    )
                    VALUES (
                        %s,
                        (SELECT organization_id FROM product_asset WHERE public_asset_id = %s),
                        (SELECT store_id FROM product_asset WHERE public_asset_id = %s),
                        (SELECT product_id FROM product_asset WHERE public_asset_id = %s),
                        'asset_markdown',
                        %s,
                        %s,
                        'pending'
                    )
                    ON CONFLICT (public_candidate_id) WHERE public_candidate_id IS NOT NULL
                    DO UPDATE SET candidate_text = EXCLUDED.candidate_text, review_status = 'pending'
                    """,
                    (candidate_id, asset_id, asset_id, asset_id, markdown_id, markdown["markdown_text"]),
                )
                self._canonical_audit(cur, "org-001", "store-001", actor_id, "product_asset.markdown.create", "product_asset_markdown", markdown_id, payload)
        return markdown

    def create_price_snapshot(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id", "org-001"))
        store_id = str(payload.get("store_id", "store-001"))
        product_id = str(payload.get("product_id"))
        snapshot_id = f"price-{_stable_product_suffix(organization_id, store_id, product_id + str(payload.get('effective_at', '')))}"
        snapshot = {
            "price_snapshot_id": snapshot_id,
            "product_id": product_id,
            "sku_id": payload.get("sku_id"),
            "status": str(payload.get("status", "active")),
            "current_price": payload.get("current_price"),
            "currency": payload.get("currency", "CNY"),
        }
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._upsert_tenant_store(cur, organization_id, store_id, str(payload.get("platform", "pdd")))
                cur.execute(
                    """
                    INSERT INTO product_price_snapshot (
                        public_price_snapshot_id, organization_id, store_id, product_id,
                        currency, price_amount, captured_at, source
                    )
                    VALUES (
                        %s,
                        (SELECT id FROM organization WHERE external_organization_id = %s),
                        (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                          WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                        (SELECT id FROM product WHERE public_product_id = %s),
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (public_price_snapshot_id) WHERE public_price_snapshot_id IS NOT NULL
                    DO UPDATE SET price_amount = EXCLUDED.price_amount, source = EXCLUDED.source
                    """,
                    (
                        snapshot_id,
                        organization_id,
                        organization_id,
                        store_id,
                        product_id,
                        snapshot["currency"],
                        snapshot["current_price"],
                        payload.get("effective_at"),
                        payload.get("source", "admin"),
                    ),
                )
                self._canonical_audit(cur, organization_id, store_id, actor_id, "price_snapshot.create", "product_price_snapshot", snapshot_id, payload)
        return snapshot

    def list_audit_logs(self, scope: str) -> list[dict[str, Any]]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                if scope == "admin":
                    cur.execute(
                        """
                        SELECT audit.id, org.external_organization_id, st.external_store_id,
                               COALESCE(audit.admin_user_id::text, audit.diff_summary->>'actor_id'),
                               audit.action, audit.object_type, audit.object_id,
                               audit.diff_summary, false, audit.created_at
                        FROM admin_audit_log audit
                        JOIN organization org ON org.id = audit.organization_id
                        LEFT JOIN store st ON st.id = audit.store_id
                        ORDER BY audit.created_at DESC
                        LIMIT 50
                        """
                    )
                    rows = cur.fetchall()
                    if rows:
                        return [_canonical_admin_audit_from_row(row) for row in rows]
                cur.execute(
                    """
                    SELECT audit_log_id, scope, organization_id, store_id, actor_id, action,
                           object_type, object_id, diff_summary, created_at
                    FROM app_audit_log
                    WHERE scope = %s
                    ORDER BY created_at DESC
                    LIMIT 50
                    """,
                    (scope,),
                )
                return [_audit_from_row(row) for row in cur.fetchall()]

    def product_health(self, product_id: str) -> dict[str, Any]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM app_product WHERE product_id = %s", (product_id,))
                exists = cur.fetchone() is not None
        return {
            "product_id": product_id,
            "status": "healthy" if exists else "warning",
            "checks": [{"name": "product_exists", "status": "pass" if exists else "warning"}],
        }

    def system_health(self) -> dict[str, Any]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return _system_health("healthy", "postgresql reachable")

    def store_readiness(self) -> list[dict[str, Any]]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM product")
                has_product = int(cur.fetchone()[0]) > 0
        return [_readiness_item("ready" if has_product else "blocked", has_product)]

    def _upsert_tenant_store(self, cur: Any, organization_id: str, store_id: str, platform: str) -> None:
        cur.execute(
            """
            INSERT INTO organization (external_organization_id, name, settings)
            VALUES (%s, %s, %s)
            ON CONFLICT (external_organization_id) WHERE external_organization_id IS NOT NULL
            DO UPDATE SET updated_at = now()
            """,
            (organization_id, organization_id, Jsonb({"external_organization_id": organization_id})),
        )
        cur.execute(
            """
            INSERT INTO store (organization_id, name, platform, external_store_id, settings)
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (organization_id, platform, external_store_id)
            DO UPDATE SET updated_at = now()
            """,
            (organization_id, store_id, platform, store_id, Jsonb({"external_store_id": store_id})),
        )

    def _canonical_audit(
        self,
        cur: Any,
        organization_id: str,
        store_id: str | None,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> None:
        cur.execute(
            """
            INSERT INTO admin_audit_log (
                organization_id, store_id, admin_user_id, action, object_type, object_id, diff_summary
            )
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                NULL,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                organization_id,
                organization_id,
                store_id,
                action,
                object_type,
                object_id,
                Jsonb({**diff_summary, "actor_id": actor_id}),
            ),
        )

    def _audit(
        self,
        cur: Any,
        scope: str,
        organization_id: str | None,
        store_id: str | None,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> None:
        audit = _audit_log(scope, organization_id, store_id, actor_id, action, object_type, object_id, diff_summary)
        cur.execute(
            """
            INSERT INTO app_audit_log (
                audit_log_id, scope, organization_id, store_id, actor_id,
                action, object_type, object_id, diff_summary
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                audit["id"],
                scope,
                organization_id,
                store_id,
                actor_id,
                action,
                object_type,
                object_id,
                Jsonb(diff_summary),
            ),
        )


def admin_repository_for(settings: Settings) -> AdminRepository:
    if settings.database_url and settings.environment.lower() not in {"test"}:
        return PostgresAdminRepository(settings.database_url)
    return InMemoryAdminRepository()


def _product_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    external_product_id = str(payload.get("external_product_id", "local"))
    organization_id = str(payload.get("organization_id", "org-001"))
    store_id = str(payload.get("store_id", "store-001"))
    product_id = str(
        payload.get("product_id")
        or f"product-{_stable_product_suffix(organization_id, store_id, external_product_id)}"
    )
    return {
        "product_id": product_id,
        "organization_id": organization_id,
        "store_id": store_id,
        "external_product_id": external_product_id,
        "title": str(payload.get("title", "")),
        "status": str(payload.get("status", "active")),
        "attributes": payload.get("attributes", {}),
        "sku_ids": payload.get("sku_ids", []),
    }


def _stable_product_suffix(organization_id: str, store_id: str, external_product_id: str) -> str:
    digest = hashlib.sha256(f"{organization_id}|{store_id}|{external_product_id}".encode("utf-8")).hexdigest()
    return digest[:16]


def _product_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "product_id": row[0],
        "organization_id": row[1],
        "store_id": row[2],
        "external_product_id": row[3],
        "title": row[4],
        "status": row[5],
        "attributes": row[6],
        "sku_ids": [],
    }


def _candidate_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "candidate_id": row[0],
        "organization_id": row[1],
        "store_id": row[2],
        "product_id": row[3],
        "candidate_text": row[4],
        "review_status": row[5],
        "source_payload": row[6],
        "reviewed_at": _iso(row[7]),
    }


def _audit_log(
    scope: str,
    organization_id: str | None,
    store_id: str | None,
    actor_id: str,
    action: str,
    object_type: str,
    object_id: str,
    diff_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "scope": scope,
        "organization_id": organization_id,
        "store_id": store_id,
        "actor_id": actor_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "diff_summary": diff_summary,
        "created_at": _now(),
    }


def _audit_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "scope": row[1],
        "organization_id": row[2],
        "store_id": row[3],
        "actor_id": row[4],
        "action": row[5],
        "object_type": row[6],
        "object_id": row[7],
        "diff_summary": row[8],
        "created_at": _iso(row[9]),
    }


def _canonical_admin_audit_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "scope": "admin",
        "organization_id": row[1],
        "store_id": row[2],
        "actor_id": row[3],
        "action": row[4],
        "object_type": row[5],
        "object_id": row[6],
        "diff_summary": row[7],
        "sensitive_access": bool(row[8]),
        "created_at": _iso(row[9]),
    }


def _system_health(status: str, detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "checked_at": _now(),
        "dependencies": [
            {"name": "api", "status": "healthy", "detail": "local app responds"},
            {"name": "postgresql", "status": "healthy" if status == "healthy" else "degraded", "detail": detail},
        ],
    }


def _readiness_item(status: str, has_product: bool) -> dict[str, Any]:
    return {
        "organization_id": "org-001",
        "store_id": "store-001",
        "status": status,
        "checks": [
            {
                "name": "product_content",
                "status": "pass" if has_product else "warning",
                "reason": "商品资料已配置" if has_product else "本地样例资料未完整配置",
            }
        ],
    }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)
