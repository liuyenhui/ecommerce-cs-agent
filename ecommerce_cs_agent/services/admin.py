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
        self.knowledge_candidates: dict[str, dict[str, Any]] = {}
        self.audit_logs: list[dict[str, Any]] = []

    def upsert_product(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        product = _product_from_payload(payload)
        self.products[product["product_id"]] = product
        self._audit("admin", product["organization_id"], product["store_id"], actor_id, "product.upsert", "product", product["product_id"], payload)
        return product

    def review_knowledge_candidate(self, candidate_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        candidate = {
            "candidate_id": candidate_id,
            "organization_id": payload.get("organization_id", "org-001"),
            "store_id": payload.get("store_id", "store-001"),
            "product_id": payload.get("product_id"),
            "candidate_text": payload.get("candidate_text", ""),
            "review_status": "accepted" if payload.get("accepted", True) else "rejected",
            "source_payload": payload,
            "reviewed_at": _now(),
        }
        self.knowledge_candidates[candidate_id] = candidate
        self._audit("admin", candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, payload)
        return candidate

    def list_audit_logs(self, scope: str) -> list[dict[str, Any]]:
        return [item for item in self.audit_logs if item["scope"] == scope]

    def product_health(self, product_id: str) -> dict[str, Any]:
        product = self.products.get(product_id)
        return {
            "product_id": product_id,
            "status": "healthy" if product else "warning",
            "checks": [{"name": "product_exists", "status": "pass" if product else "warning"}],
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
                saved = _product_from_row(row)
                self._audit(cur, "admin", saved["organization_id"], saved["store_id"], actor_id, "product.upsert", "product", saved["product_id"], payload)
                return saved

    def review_knowledge_candidate(self, candidate_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        status = "accepted" if payload.get("accepted", True) else "rejected"
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
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
                        payload.get("organization_id", "org-001"),
                        payload.get("store_id", "store-001"),
                        payload.get("product_id"),
                        payload.get("candidate_text", ""),
                        status,
                        Jsonb(payload),
                    ),
                )
                row = cur.fetchone()
                candidate = _candidate_from_row(row)
                self._audit(cur, "admin", candidate["organization_id"], candidate["store_id"], actor_id, "knowledge.review", "knowledge_candidate", candidate_id, payload)
                return candidate

    def list_audit_logs(self, scope: str) -> list[dict[str, Any]]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
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
                cur.execute("SELECT count(*) FROM app_product")
                has_product = int(cur.fetchone()[0]) > 0
        return [_readiness_item("ready" if has_product else "blocked", has_product)]

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
