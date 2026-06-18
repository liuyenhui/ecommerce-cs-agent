from __future__ import annotations

import uuid
from datetime import datetime, timezone
import hashlib
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.embeddings import DeterministicEmbeddingProvider
from ecommerce_cs_agent.services.object_storage import (
    FilesystemObjectStorage,
    InMemoryObjectStorage,
    ObjectStorage,
    ReferenceObjectStorage,
)


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

    def recall_knowledge(self, organization_id: str, store_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    def system_health(self) -> dict[str, Any]:
        raise NotImplementedError

    def store_readiness(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class InMemoryAdminRepository:
    def __init__(self, object_storage: ObjectStorage | None = None, embedding_provider: DeterministicEmbeddingProvider | None = None) -> None:
        self.products: dict[str, dict[str, Any]] = {}
        self.assets: dict[str, dict[str, Any]] = {}
        self.markdowns: dict[str, dict[str, Any]] = {}
        self.price_snapshots: dict[str, dict[str, Any]] = {}
        self.knowledge_candidates: dict[str, dict[str, Any]] = {}
        self.knowledge_entries: dict[str, dict[str, Any]] = {}
        self.knowledge_embeddings: dict[str, dict[str, Any]] = {}
        self.audit_logs: list[dict[str, Any]] = []
        self._object_storage = object_storage or InMemoryObjectStorage()
        self._embedding_provider = embedding_provider or DeterministicEmbeddingProvider()

    def upsert_product(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product = _product_from_payload(payload)
        self.products[product["product_id"]] = product
        self._audit("admin", product["organization_id"], product["store_id"], actor_id, "product.upsert", "product", product["product_id"], _safe_diff_summary(payload))
        return product

    def review_knowledge_candidate(self, candidate_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        accepted = payload.get("accepted")
        if accepted is None:
            accepted = payload.get("action", "approve") == "approve"
        existing_candidate = self.knowledge_candidates.get(candidate_id)
        candidate_text = str(
            payload.get(
                "reviewed_content",
                payload.get("candidate_text", existing_candidate.get("candidate_text", "") if existing_candidate else ""),
            )
        )
        knowledge_entry_id = f"knowledge-{candidate_id}" if accepted else None
        organization_id = (
            existing_candidate.get("organization_id")
            if existing_candidate
            else payload.get("organization_id", "org-001")
        )
        store_id = existing_candidate.get("store_id") if existing_candidate else payload.get("store_id", "store-001")
        product_id = existing_candidate.get("product_id") if existing_candidate else payload.get("product_id")
        candidate = {
            "candidate_id": candidate_id,
            "organization_id": organization_id,
            "store_id": store_id,
            "product_id": product_id,
            "candidate_text": candidate_text,
            "review_status": "accepted" if accepted else "rejected",
            "source_payload": payload,
            "reviewed_at": _now(),
            "knowledge_entry_id": knowledge_entry_id,
        }
        self.knowledge_candidates[candidate_id] = candidate
        if knowledge_entry_id:
            embedding = self._embedding_provider.embed(candidate_text)
            self.knowledge_entries[knowledge_entry_id] = {
                "knowledge_entry_id": knowledge_entry_id,
                "candidate_id": candidate_id,
                "content": candidate_text,
                "status": "approved",
            }
            self.knowledge_embeddings[knowledge_entry_id] = {
                "knowledge_entry_id": knowledge_entry_id,
                "embedding_model": embedding.model,
                "chunk_text": candidate_text,
                "chunk_index": 0,
            }
        elif existing_candidate and existing_candidate.get("knowledge_entry_id"):
            entry_id = str(existing_candidate["knowledge_entry_id"])
            if entry_id in self.knowledge_entries:
                self.knowledge_entries[entry_id]["status"] = "disabled"
            self.knowledge_embeddings.pop(entry_id, None)
        self._audit("admin", candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, _safe_diff_summary(payload))
        return candidate

    def create_asset(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product = self.products.get(str(payload.get("product_id")))
        organization_id = product["organization_id"] if product else str(payload.get("organization_id", "org-001"))
        store_id = product["store_id"] if product else str(payload.get("store_id", "store-001"))
        asset_id = f"asset-{_stable_product_suffix(organization_id, store_id, str(payload.get('file_hash', payload.get('file_ref', 'asset'))))}"
        stored = self._object_storage.put_or_reference(asset_id=asset_id, payload=payload)
        asset = {
            "asset_id": asset_id,
            "product_id": str(payload.get("product_id")),
            "organization_id": organization_id,
            "store_id": store_id,
            "asset_type": str(payload.get("asset_type", "other")),
            "file_ref": stored.object_key,
            "file_hash": stored.object_hash,
            "version": str(payload.get("version", "v1")),
            "review_status": "pending",
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "storage_status": stored.storage_status,
            "metadata": payload.get("metadata", {}),
        }
        self.assets[asset_id] = asset
        self._audit("admin", organization_id, store_id, actor_id, "product_asset.create", "product_asset", asset_id, _safe_diff_summary(payload))
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
        self._audit("admin", asset["organization_id"], asset["store_id"], actor_id, "product_asset.markdown.create", "product_asset_markdown", markdown_id, _safe_diff_summary(payload))
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
        self._audit("admin", organization_id, store_id, actor_id, "price_snapshot.create", "product_price_snapshot", snapshot_id, _safe_diff_summary(payload))
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

    def recall_knowledge(self, organization_id: str, store_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_text = query.lower()
        entries: list[dict[str, Any]] = []
        for entry_id, entry in self.knowledge_entries.items():
            candidate = self.knowledge_candidates.get(str(entry.get("candidate_id")))
            if not candidate or candidate.get("review_status") != "accepted":
                continue
            if candidate.get("organization_id") != organization_id or candidate.get("store_id") != store_id:
                continue
            content = str(entry.get("content", ""))
            if query_text and query_text not in content.lower():
                continue
            embedding = self.knowledge_embeddings.get(entry_id, {})
            entries.append(
                {
                    "knowledge_entry_id": entry_id,
                    "product_id": candidate.get("product_id"),
                    "scope": "product",
                    "content": content,
                    "embedding_model": embedding.get("embedding_model"),
                    "chunk_index": embedding.get("chunk_index", 0),
                }
            )
        return entries[:limit]

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
    def __init__(
        self,
        database_url: str,
        object_storage: ObjectStorage | None = None,
        embedding_provider: DeterministicEmbeddingProvider | None = None,
    ) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url
        self._object_storage = object_storage or ReferenceObjectStorage()
        self._embedding_provider = embedding_provider or DeterministicEmbeddingProvider()

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
        accepted = payload.get("accepted")
        if accepted is None:
            accepted = payload.get("action", "approve") == "approve"
        status = "accepted" if accepted else "rejected"
        organization_id = str(payload.get("organization_id", "org-001"))
        store_id = str(payload.get("store_id", "store-001"))
        product_id = payload.get("product_id")
        candidate_text = str(payload.get("reviewed_content", payload.get("candidate_text", "")))
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                existing_candidate = self._get_candidate_context(cur, candidate_id)
                if existing_candidate:
                    organization_id = existing_candidate["organization_id"]
                    store_id = existing_candidate["store_id"]
                    product_id = existing_candidate["product_id"]
                    if not candidate_text:
                        candidate_text = existing_candidate["candidate_text"]
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
                        RETURNING id::text
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
                            Jsonb(_safe_diff_summary(payload)),
                        ),
                    )
                    entry_row = cur.fetchone()
                    knowledge_entry_id = str(entry_row[0]) if entry_row else f"knowledge-{candidate_id}"
                    embedding = self._embedding_provider.embed(candidate_text)
                    cur.execute(
                        """
                        INSERT INTO knowledge_embedding (
                            organization_id, store_id, knowledge_entry_id,
                            embedding, embedding_model, chunk_text, chunk_index
                        )
                        VALUES (
                            (SELECT id FROM organization WHERE external_organization_id = %s),
                            (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                              WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                            (SELECT id FROM knowledge_entry WHERE id::text = %s),
                            %s::vector,
                            %s,
                            %s,
                            0
                        )
                        ON CONFLICT (knowledge_entry_id, chunk_index)
                        DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model,
                            chunk_text = EXCLUDED.chunk_text,
                            created_at = now()
                        """,
                        (
                            organization_id,
                            organization_id,
                            store_id,
                            knowledge_entry_id,
                            embedding.to_pgvector(),
                            embedding.model,
                            candidate_text,
                        ),
                    )
                else:
                    knowledge_entry_id = None
                    cur.execute(
                        """
                        UPDATE knowledge_entry
                        SET status = 'disabled', updated_at = now()
                        WHERE source_product_candidate_id = (
                            SELECT id FROM product_knowledge_candidate WHERE public_candidate_id = %s
                        )
                        """,
                        (candidate_id,),
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
                        Jsonb(_safe_diff_summary(payload)),
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
                candidate["knowledge_entry_id"] = knowledge_entry_id
                safe_payload = _safe_diff_summary(payload)
                self._canonical_audit(cur, candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, safe_payload)
                self._audit(cur, "admin", candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, safe_payload)
                return candidate

    def create_asset(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product_id = str(payload.get("product_id"))
        organization_id = str(payload.get("organization_id", "org-001"))
        store_id = str(payload.get("store_id", "store-001"))
        asset_id = f"asset-{_stable_product_suffix(organization_id, store_id, str(payload.get('file_hash', payload.get('file_ref', 'asset'))))}"
        stored = self._object_storage.put_or_reference(asset_id=asset_id, payload=payload)
        asset = {
            "asset_id": asset_id,
            "product_id": product_id,
            "organization_id": organization_id,
            "store_id": store_id,
            "asset_type": str(payload.get("asset_type", "other")),
            "file_ref": stored.object_key,
            "file_hash": stored.object_hash,
            "version": str(payload.get("version", "v1")),
            "review_status": "pending",
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "storage_status": stored.storage_status,
            "metadata": payload.get("metadata", {}),
        }
        try:
            with self._connect(self._database_url) as conn:
                with conn.cursor() as cur:
                    self._upsert_tenant_store(cur, organization_id, store_id, str(payload.get("platform", "pdd")))
                    cur.execute(
                        """
                        INSERT INTO product_asset (
                            public_asset_id, organization_id, store_id, product_id,
                            asset_type, object_key, source_url, object_hash, mime_type, size_bytes,
                            storage_status, metadata
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
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        ON CONFLICT (public_asset_id) WHERE public_asset_id IS NOT NULL
                        DO UPDATE SET
                            object_key = EXCLUDED.object_key,
                            object_hash = EXCLUDED.object_hash,
                            mime_type = EXCLUDED.mime_type,
                            size_bytes = EXCLUDED.size_bytes,
                            storage_status = EXCLUDED.storage_status,
                            metadata = EXCLUDED.metadata
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
                            asset["file_hash"],
                            asset["mime_type"],
                            asset["size_bytes"],
                            asset["storage_status"],
                            Jsonb({**asset["metadata"], "file_hash": asset["file_hash"], "version": asset["version"]}),
                        ),
                    )
                    self._canonical_audit(
                        cur,
                        organization_id,
                        store_id,
                        actor_id,
                        "product_asset.create",
                        "product_asset",
                        asset_id,
                        _safe_diff_summary(payload),
                    )
        except Exception:
            if asset["storage_status"] == "stored":
                self._object_storage.delete(asset["file_ref"])
            raise
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
                cur.execute(
                    """
                    SELECT org.external_organization_id, st.external_store_id
                    FROM product_asset asset
                    JOIN organization org ON org.id = asset.organization_id
                    JOIN store st ON st.id = asset.store_id
                    WHERE asset.public_asset_id = %s
                    """,
                    (asset_id,),
                )
                tenant_row = cur.fetchone()
                if tenant_row:
                    self._canonical_audit(
                        cur,
                        str(tenant_row[0]),
                        str(tenant_row[1]),
                        actor_id,
                        "product_asset.markdown.create",
                        "product_asset_markdown",
                        markdown_id,
                        _safe_diff_summary(payload),
                    )
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
                self._canonical_audit(cur, organization_id, store_id, actor_id, "price_snapshot.create", "product_price_snapshot", snapshot_id, _safe_diff_summary(payload))
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
                cur.execute(
                    """
                    SELECT
                        EXISTS(SELECT 1 FROM product WHERE public_product_id = %s),
                        EXISTS(
                            SELECT 1
                            FROM product_price_snapshot price
                            JOIN product product_row ON product_row.id = price.product_id
                            WHERE product_row.public_product_id = %s
                        )
                    """,
                    (product_id, product_id),
                )
                row = cur.fetchone()
                exists = bool(row and row[0])
                has_price_snapshot = bool(row and row[1])
                if not exists:
                    cur.execute("SELECT 1 FROM app_product WHERE product_id = %s", (product_id,))
                    exists = cur.fetchone() is not None
        return {
            "product_id": product_id,
            "status": "healthy" if exists else "warning",
            "checks": [
                {"name": "product_exists", "status": "pass" if exists else "warning"},
                {"name": "price_snapshot_exists", "status": "pass" if has_price_snapshot else "warning"},
            ],
        }

    def recall_knowledge(self, organization_id: str, store_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entry.id::text, product.public_product_id, entry.scope, entry.content,
                           embedding.embedding_model, embedding.chunk_index
                    FROM knowledge_entry entry
                    JOIN organization org ON org.id = entry.organization_id
                    JOIN store st ON st.id = entry.store_id
                    LEFT JOIN product product ON product.id = entry.product_id
                    LEFT JOIN product_knowledge_candidate candidate
                      ON candidate.id = entry.source_product_candidate_id
                    LEFT JOIN knowledge_embedding embedding
                      ON embedding.knowledge_entry_id = entry.id AND embedding.chunk_index = 0
                    WHERE org.external_organization_id = %s
                      AND st.external_store_id = %s
                      AND entry.status = 'approved'
                      AND candidate.review_status = 'accepted'
                      AND (%s = '' OR entry.content ILIKE '%%' || %s || '%%')
                    ORDER BY entry.updated_at DESC
                    LIMIT %s
                    """,
                    (organization_id, store_id, query, query, limit),
                )
                return [
                    {
                        "knowledge_entry_id": str(row[0]),
                        "product_id": row[1],
                        "scope": row[2],
                        "content": row[3],
                        "embedding_model": row[4],
                        "chunk_index": row[5],
                    }
                    for row in cur.fetchall()
                ]

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

    def _get_candidate_context(self, cur: Any, candidate_id: str) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT org.external_organization_id, st.external_store_id,
                   product.public_product_id, candidate.candidate_text
            FROM product_knowledge_candidate candidate
            JOIN organization org ON org.id = candidate.organization_id
            JOIN store st ON st.id = candidate.store_id
            LEFT JOIN product product ON product.id = candidate.product_id
            WHERE candidate.public_candidate_id = %s
            """,
            (candidate_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "organization_id": str(row[0]),
            "store_id": str(row[1]),
            "product_id": str(row[2]) if row[2] is not None else None,
            "candidate_text": str(row[3] or ""),
        }

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
    object_storage = _object_storage_for(settings)
    embedding_provider = DeterministicEmbeddingProvider()
    if settings.database_url and settings.environment.lower() not in {"test"}:
        return PostgresAdminRepository(settings.database_url, object_storage=object_storage, embedding_provider=embedding_provider)
    return InMemoryAdminRepository(object_storage=object_storage, embedding_provider=embedding_provider)


def _object_storage_for(settings: Settings) -> ObjectStorage:
    backend = getattr(settings, "object_storage_backend", "reference").lower()
    if backend == "filesystem":
        return FilesystemObjectStorage(getattr(settings, "object_storage_root", ".object-storage"))
    if backend == "memory":
        return InMemoryObjectStorage()
    return ReferenceObjectStorage()


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


def _safe_diff_summary(payload: dict[str, Any]) -> dict[str, Any]:
    redacted_keys = {"content_base64", "content", "raw_payload", "authorization", "cookie"}
    summary: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in redacted_keys:
            summary[key] = "<redacted>"
        else:
            summary[key] = value
    return summary


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
