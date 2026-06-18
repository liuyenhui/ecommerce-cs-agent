from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import SystemAdminSession


class SystemAdminRepository(Protocol):
    def list_users(self, session: SystemAdminSession) -> dict[str, Any]:
        raise NotImplementedError

    def create_user(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def list_organizations(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def create_organization(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def list_stores(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def create_store(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def store_readiness(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def list_tasks(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def retry_task(self, session: SystemAdminSession, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def list_audit_logs(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class InMemorySystemAdminRepository:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {
            "sysadmin-001": _system_user("sysadmin-001", "system-admin@example.test", "System Admin", ["super_admin"])
        }
        self.organizations: dict[str, dict[str, Any]] = {
            "org-001": {
                "id": "org-001",
                "organization_id": "org-001",
                "name": "Demo Organization",
                "status": "active",
                "metadata": {},
                "external_ref": "org-001",
                "contact": {},
                "created_at": _now(),
            }
        }
        self.stores: dict[str, dict[str, Any]] = {
            "store-001": {
                "id": "store-001",
                "store_id": "store-001",
                "organization_id": "org-001",
                "name": "Demo PDD Store",
                "platform": "pdd",
                "status": "active",
                "metadata": {},
                "external_store_id": "store-001",
                "readiness_status": "blocked",
                "created_at": _now(),
            }
        }
        self.tasks: dict[str, dict[str, Any]] = {}
        self.audit_logs: list[dict[str, Any]] = []

    def list_users(self, session: SystemAdminSession) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "security_auditor"})
        self._audit(session, "system_admin.user.list", "system_admin_user", "list", {})
        return _page_response(*_slice_page(list(self.users.values()), {}))

    def create_user(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin"})
        replay = self._idempotency_replay("system_admin.user.create", payload)
        if replay:
            return {"user": self.users[replay["object_id"]], "audit_log_id": replay["audit_log_id"]}
        user_id = f"sysadmin-{_stable_suffix(str(payload.get('email', uuid.uuid4().hex)))}"
        user = _system_user(
            user_id,
            str(payload["email"]),
            str(payload["display_name"]),
            list(payload.get("roles") or ["platform_operator"]),
        )
        self.users[user_id] = user
        audit_id = self._audit(session, "system_admin.user.create", "system_admin_user", user_id, payload)
        return {"user": user, "audit_log_id": audit_id}

    def list_organizations(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._audit(session, "system_admin.organization.list", "organization", "list", filters)
        items = list(self.organizations.values())
        status = filters.get("status")
        if status:
            items = [item for item in items if item["status"] == status]
        return _page_response(*_slice_page(items, filters))

    def create_organization(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "platform_operator"})
        replay = self._idempotency_replay("system_admin.organization.create", payload)
        if replay:
            return {"organization": self.organizations[replay["object_id"]], "audit_log_id": replay["audit_log_id"]}
        organization_id = str(payload.get("external_ref") or f"org-{_stable_suffix(str(payload['name']))}")
        organization = {
            "id": organization_id,
            "organization_id": organization_id,
            "name": str(payload["name"]),
            "status": str(payload["status"]),
            "metadata": {},
            "external_ref": organization_id,
            "contact": payload.get("contact", {}),
            "created_at": _now(),
        }
        self.organizations[organization_id] = organization
        audit_id = self._audit(session, "system_admin.organization.create", "organization", organization_id, payload)
        return {"organization": organization, "audit_log_id": audit_id}

    def list_stores(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._audit(session, "system_admin.store.list", "store", "list", filters)
        items = list(self.stores.values())
        if filters.get("organization_id"):
            items = [item for item in items if item["organization_id"] == filters["organization_id"]]
        if filters.get("store_id"):
            items = [item for item in items if item["id"] == filters["store_id"]]
        if filters.get("status"):
            items = [item for item in items if item["status"] == filters["status"]]
        return _page_response(*_slice_page(items, filters))

    def create_store(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "platform_operator"})
        replay = self._idempotency_replay("system_admin.store.create", payload)
        if replay:
            return {"store": self.stores[replay["object_id"]], "audit_log_id": replay["audit_log_id"]}
        organization_id = str(payload["organization_id"])
        if organization_id not in self.organizations:
            raise api_error(404, "not_found", "organization not found")
        store_id = str(payload.get("external_store_id") or f"store-{_stable_suffix(organization_id + str(payload['name']))}")
        store = {
            "id": store_id,
            "store_id": store_id,
            "organization_id": organization_id,
            "name": str(payload["name"]),
            "platform": str(payload["platform"]),
            "status": str(payload["status"]),
            "metadata": {},
            "external_store_id": store_id,
            "readiness_status": "blocked",
            "created_at": _now(),
        }
        self.stores[store_id] = store
        audit_id = self._audit(session, "system_admin.store.create", "store", store_id, payload)
        return {"store": store, "audit_log_id": audit_id}

    def store_readiness(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._audit(session, "system_admin.readiness.list", "store_readiness", "list", filters)
        items = [
            _readiness_item(item["organization_id"], item["id"], "blocked", False, False, False, False)
            for item in self.stores.values()
            if not filters.get("organization_id") or item["organization_id"] == filters["organization_id"]
        ]
        return _page_response(*_slice_page(items, filters))

    def list_tasks(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._audit(session, "system_admin.task.list", "background_task", "list", filters)
        items = list(self.tasks.values())
        for key in ("organization_id", "store_id", "task_type", "status"):
            if filters.get(key):
                items = [item for item in items if item.get(key) == filters[key]]
        return _page_response(*_slice_page(items, filters))

    def retry_task(self, session: SystemAdminSession, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "technical_support", "platform_operator"})
        task = self.tasks.get(task_id)
        if not task:
            raise api_error(404, "not_found", f"task {task_id} not found")
        if task["status"] != "failed":
            replay = self._idempotency_replay("system_admin.task.retry", payload)
            if replay and replay["object_id"] == task_id:
                return {"task_id": task_id, "status": "queued", "audit_log_id": replay["audit_log_id"]}
            raise api_error(409, "idempotency_conflict", f"task {task_id} is not retryable from status {task['status']}")
        task["status"] = "queued"
        task["retry_count"] = int(task.get("retry_count", 0)) + 1
        audit_id = self._audit(session, "system_admin.task.retry", "background_task", task_id, payload)
        return {"task_id": task_id, "status": "queued", "audit_log_id": audit_id}

    def list_audit_logs(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._audit(session, "system_admin.audit.list", "system_admin_audit_log", "list", filters)
        return _page_response(*_slice_page(self.audit_logs, filters))

    def _audit(
        self,
        session: SystemAdminSession,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> str:
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        self.audit_logs.insert(
            0,
            _audit_log(
                audit_id,
                session.user_id,
                None,
                None,
                action,
                object_type,
                object_id,
                diff_summary.get("reason"),
                diff_summary,
            ),
        )
        return audit_id

    def _idempotency_replay(self, action: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        idempotency_key = payload.get("idempotency_key")
        if not idempotency_key:
            return None
        for item in self.audit_logs:
            if item["action"] == action and item["diff_summary"].get("idempotency_key") == idempotency_key:
                return item
        return None

    def _require_any_role(self, session: SystemAdminSession, roles: set[str]) -> None:
        if session.role not in roles:
            raise api_error(403, "forbidden", "system admin role cannot modify this resource")


class PostgresSystemAdminRepository:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url

    def list_users(self, session: SystemAdminSession) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "security_auditor"})
        page = _pagination({})
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, None, None, "system_admin.user.list", "system_admin_user", "list", {})
                cur.execute(
                    """
                    SELECT count(*)
                    FROM system_admin_user
                    """
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT id, email, display_name, role, status, created_at, roles
                    FROM system_admin_user
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (page["limit"], page["offset"]),
                )
                return _page_response([_system_user_from_row(row) for row in cur.fetchall()], page["page"], page["page_size"], total)

    def create_user(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin"})
        roles = list(payload.get("roles") or ["platform_operator"])
        role = roles[0]
        password_hash = str(payload.get("password_hash") or "disabled:bootstrap-required")
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                replay = self._find_idempotency(cur, "system_admin.user.create", payload.get("idempotency_key"))
                if replay:
                    cur.execute(
                        """
                        SELECT id, email, display_name, role, status, created_at, roles
                        FROM system_admin_user
                        WHERE id::text = %s
                        """,
                        (replay["object_id"],),
                    )
                    return {"user": _system_user_from_row(cur.fetchone()), "audit_log_id": replay["audit_log_id"]}
                cur.execute(
                    """
                    INSERT INTO system_admin_user (email, password_hash, display_name, role, roles, status)
                    VALUES (%s, %s, %s, %s, %s, 'active')
                    ON CONFLICT (email)
                    DO UPDATE SET display_name = EXCLUDED.display_name, role = EXCLUDED.role, roles = EXCLUDED.roles, updated_at = now()
                    RETURNING id, email, display_name, role, status, created_at, roles
                    """,
                    (payload["email"], password_hash, payload["display_name"], role, roles),
                )
                user = _system_user_from_row(cur.fetchone())
                audit_id = self._audit(
                    cur,
                    session,
                    None,
                    None,
                    "system_admin.user.create",
                    "system_admin_user",
                    user["system_user_id"],
                    payload,
                )
                return {"user": user, "audit_log_id": audit_id}

    def list_organizations(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        status = filters.get("status")
        page = _pagination(filters)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, None, None, "system_admin.organization.list", "organization", "list", filters)
                cur.execute(
                    """
                    SELECT count(*)
                    FROM organization
                    WHERE (%s::text IS NULL OR status = %s)
                    """,
                    (status, status),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT external_organization_id, name, status, settings, created_at
                    FROM organization
                    WHERE (%s::text IS NULL OR status = %s)
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (status, status, page["limit"], page["offset"]),
                )
                return _page_response([_organization_from_row(row) for row in cur.fetchall()], page["page"], page["page_size"], total)

    def create_organization(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "platform_operator"})
        organization_id = str(payload.get("external_ref") or f"org-{_stable_suffix(str(payload['name']))}")
        settings = {"external_ref": organization_id, "contact": payload.get("contact", {}), "reason": payload.get("reason")}
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                replay = self._find_idempotency(cur, "system_admin.organization.create", payload.get("idempotency_key"))
                if replay:
                    cur.execute(
                        """
                        SELECT external_organization_id, name, status, settings, created_at
                        FROM organization
                        WHERE external_organization_id = %s
                        """,
                        (replay["object_id"],),
                    )
                    return {"organization": _organization_from_row(cur.fetchone()), "audit_log_id": replay["audit_log_id"]}
                cur.execute(
                    """
                    INSERT INTO organization (external_organization_id, name, status, settings)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (external_organization_id) WHERE external_organization_id IS NOT NULL
                    DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status, settings = organization.settings || EXCLUDED.settings, updated_at = now()
                    RETURNING external_organization_id, name, status, settings, created_at
                    """,
                    (organization_id, payload["name"], payload["status"], Jsonb(settings)),
                )
                organization = _organization_from_row(cur.fetchone())
                audit_id = self._audit(
                    cur,
                    session,
                    organization_id,
                    None,
                    "system_admin.organization.create",
                    "organization",
                    organization_id,
                    payload,
                )
                return {"organization": organization, "audit_log_id": audit_id}

    def list_stores(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        organization_id = filters.get("organization_id")
        store_id = filters.get("store_id")
        status = filters.get("status")
        page = _pagination(filters)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, organization_id, store_id, "system_admin.store.list", "store", "list", filters)
                cur.execute(
                    """
                    SELECT count(*)
                    FROM store st
                    JOIN organization org ON org.id = st.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR st.status = %s)
                    """,
                    (organization_id, organization_id, store_id, store_id, status, status),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT org.external_organization_id, st.external_store_id, st.name, st.platform, st.status, st.settings, st.created_at,
                           EXISTS(SELECT 1 FROM product p WHERE p.store_id = st.id) AS has_product
                    FROM store st
                    JOIN organization org ON org.id = st.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR st.status = %s)
                    ORDER BY st.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (organization_id, organization_id, store_id, store_id, status, status, page["limit"], page["offset"]),
                )
                return _page_response([_store_from_row(row) for row in cur.fetchall()], page["page"], page["page_size"], total)

    def create_store(self, session: SystemAdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "platform_operator"})
        organization_id = str(payload["organization_id"])
        store_id = str(payload.get("external_store_id") or f"store-{_stable_suffix(organization_id + str(payload['name']))}")
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                replay = self._find_idempotency(cur, "system_admin.store.create", payload.get("idempotency_key"))
                if replay:
                    cur.execute(
                        """
                        SELECT org.external_organization_id, st.external_store_id, st.name, st.platform, st.status, st.settings, st.created_at,
                               EXISTS(SELECT 1 FROM product p WHERE p.store_id = st.id) AS has_product
                        FROM store st
                        JOIN organization org ON org.id = st.organization_id
                        WHERE st.external_store_id = %s
                        """,
                        (replay["object_id"],),
                    )
                    return {"store": _store_from_row(cur.fetchone()), "audit_log_id": replay["audit_log_id"]}
                cur.execute(
                    """
                    SELECT id FROM organization WHERE external_organization_id = %s
                    """,
                    (organization_id,),
                )
                if not cur.fetchone():
                    raise api_error(404, "not_found", "organization not found")
                cur.execute(
                    """
                    INSERT INTO store (organization_id, name, platform, external_store_id, status, settings)
                    VALUES ((SELECT id FROM organization WHERE external_organization_id = %s), %s, %s, %s, %s, %s)
                    ON CONFLICT (organization_id, platform, external_store_id)
                    DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status, settings = store.settings || EXCLUDED.settings, updated_at = now()
                    RETURNING
                        (SELECT external_organization_id FROM organization WHERE id = store.organization_id),
                        external_store_id, name, platform, status, settings, created_at,
                        EXISTS(SELECT 1 FROM product p WHERE p.store_id = store.id)
                    """,
                    (
                        organization_id,
                        payload["name"],
                        payload["platform"],
                        store_id,
                        payload["status"],
                        Jsonb({"reason": payload.get("reason")}),
                    ),
                )
                store = _store_from_row(cur.fetchone())
                audit_id = self._audit(cur, session, organization_id, store_id, "system_admin.store.create", "store", store_id, payload)
                return {"store": store, "audit_log_id": audit_id}

    def store_readiness(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        organization_id = filters.get("organization_id")
        store_id = filters.get("store_id")
        status = filters.get("status")
        page = _pagination(filters)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, organization_id, store_id, "system_admin.readiness.list", "store_readiness", "list", filters)
                cur.execute(
                    """
                    SELECT count(*)
                    FROM store st
                    JOIN organization org ON org.id = st.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                    """,
                    (organization_id, organization_id, store_id, store_id),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT org.external_organization_id, st.external_store_id,
                           EXISTS(SELECT 1 FROM product p WHERE p.store_id = st.id) AS has_product,
                           EXISTS(SELECT 1 FROM product_price_snapshot price WHERE price.store_id = st.id) AS has_price,
                           EXISTS(SELECT 1 FROM knowledge_entry knowledge WHERE knowledge.store_id = st.id AND knowledge.status = 'approved') AS has_knowledge,
                           (
                               EXISTS(SELECT 1 FROM platform_account account WHERE account.store_id = st.id AND account.status = 'active')
                               OR EXISTS(SELECT 1 FROM external_api_token token WHERE token.store_id = st.id AND token.status = 'active')
                           ) AS has_api_integration
                    FROM store st
                    JOIN organization org ON org.id = st.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                    ORDER BY st.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (organization_id, organization_id, store_id, store_id, page["limit"], page["offset"]),
                )
                items = [
                    _readiness_item(
                        str(row[0]),
                        str(row[1]),
                        _readiness_status(bool(row[2]), bool(row[3]), bool(row[4]), bool(row[5])),
                        bool(row[2]),
                        bool(row[3]),
                        bool(row[4]),
                        bool(row[5]),
                    )
                    for row in cur.fetchall()
                ]
                if status:
                    items = [item for item in items if item["status"] == status]
                    total = len(items)
                return _page_response(items, page["page"], page["page_size"], total)

    def list_tasks(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        organization_id = filters.get("organization_id")
        store_id = filters.get("store_id")
        task_type = filters.get("task_type")
        status = filters.get("status")
        page = _pagination(filters)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, organization_id, store_id, "system_admin.task.list", "background_task", "list", filters)
                cur.execute(
                    """
                    SELECT count(*)
                    FROM background_task task
                    JOIN organization org ON org.id = task.organization_id
                    LEFT JOIN store st ON st.id = task.store_id AND st.organization_id = task.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR task.task_type = %s)
                      AND (%s::text IS NULL OR task.status = %s)
                    """,
                    (organization_id, organization_id, store_id, store_id, task_type, task_type, status, status),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT task.task_id, task.task_type, task.status, org.external_organization_id, st.external_store_id,
                           task.input_ref, task.output_ref, task.error_summary, task.retry_count, task.next_retry_at, task.created_at
                    FROM background_task task
                    JOIN organization org ON org.id = task.organization_id
                    LEFT JOIN store st ON st.id = task.store_id AND st.organization_id = task.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR task.task_type = %s)
                      AND (%s::text IS NULL OR task.status = %s)
                    ORDER BY task.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (organization_id, organization_id, store_id, store_id, task_type, task_type, status, status, page["limit"], page["offset"]),
                )
                return _page_response([_task_from_row(row) for row in cur.fetchall()], page["page"], page["page_size"], total)

    def retry_task(self, session: SystemAdminSession, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "technical_support", "platform_operator"})
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                replay = self._find_idempotency(cur, "system_admin.task.retry", payload.get("idempotency_key"))
                if replay and replay["object_id"] == task_id:
                    return {"task_id": task_id, "status": "queued", "audit_log_id": replay["audit_log_id"]}
                cur.execute(
                    """
                    SELECT task.status, task.retryable, org.external_organization_id, st.external_store_id
                    FROM background_task task
                    JOIN organization org ON org.id = task.organization_id
                    LEFT JOIN store st ON st.id = task.store_id AND st.organization_id = task.organization_id
                    WHERE task.task_id = %s
                    """,
                    (task_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise api_error(404, "not_found", f"task {task_id} not found")
                if str(row[0]) != "failed" or not bool(row[1]):
                    raise api_error(409, "idempotency_conflict", f"task {task_id} is not retryable from status {row[0]}")
                cur.execute(
                    """
                    UPDATE background_task
                    SET status = 'queued',
                        retry_count = retry_count + 1,
                        idempotency_key = %s,
                        next_retry_at = NULL,
                        metadata = metadata || %s,
                        updated_at = now()
                    WHERE task_id = %s
                    """,
                    (payload["idempotency_key"], Jsonb({"retry_reason": payload.get("reason")}), task_id),
                )
                audit_id = self._audit(cur, session, row[2], row[3], "system_admin.task.retry", "background_task", task_id, payload)
                return {"task_id": task_id, "status": "queued", "audit_log_id": audit_id}

    def list_audit_logs(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        organization_id = filters.get("organization_id")
        store_id = filters.get("store_id")
        actor_user_id = filters.get("actor_user_id")
        page = _pagination(filters)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*)
                    FROM system_admin_audit_log audit
                    LEFT JOIN organization org ON org.id = audit.organization_id
                    LEFT JOIN store st ON st.id = audit.store_id AND st.organization_id = audit.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR audit.system_admin_user_id::text = %s)
                    """,
                    (organization_id, organization_id, store_id, store_id, actor_user_id, actor_user_id),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT audit.id, audit.system_admin_user_id, org.external_organization_id, st.external_store_id,
                           audit.action, audit.object_type, audit.object_id, audit.diff_summary, audit.created_at
                    FROM system_admin_audit_log audit
                    LEFT JOIN organization org ON org.id = audit.organization_id
                    LEFT JOIN store st ON st.id = audit.store_id AND st.organization_id = audit.organization_id
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR audit.system_admin_user_id::text = %s)
                    ORDER BY audit.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (organization_id, organization_id, store_id, store_id, actor_user_id, actor_user_id, page["limit"], page["offset"]),
                )
                rows = [_audit_from_row(row) for row in cur.fetchall()]
                self._audit(cur, session, organization_id, store_id, "system_admin.audit.list", "system_admin_audit_log", "list", filters)
                return _page_response(rows, page["page"], page["page_size"], total)

    def _audit(
        self,
        cur: Any,
        session: SystemAdminSession,
        organization_id: str | None,
        store_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> str:
        audit_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO system_admin_audit_log (
                id, system_admin_user_id, organization_id, store_id, action, object_type, object_id, diff_summary, idempotency_key
            )
            VALUES (
                %s,
                %s,
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                audit_id,
                session.user_id,
                organization_id,
                organization_id,
                store_id,
                action,
                object_type,
                object_id,
                Jsonb(diff_summary),
                diff_summary.get("idempotency_key"),
            ),
        )
        return audit_id

    def _find_idempotency(self, cur: Any, action: str, idempotency_key: Any) -> dict[str, str] | None:
        if not idempotency_key:
            return None
        cur.execute(
            """
            SELECT id::text, object_id
            FROM system_admin_audit_log
            WHERE action = %s AND idempotency_key = %s
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (action, str(idempotency_key)),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"audit_log_id": str(row[0]), "object_id": str(row[1])}

    def _require_any_role(self, session: SystemAdminSession, roles: set[str]) -> None:
        if session.role not in roles:
            raise api_error(403, "forbidden", "system admin role cannot modify this resource")


def system_admin_repository_for(settings: Settings) -> SystemAdminRepository:
    if settings.database_url and settings.environment.lower() not in {"test"}:
        return PostgresSystemAdminRepository(settings.database_url)
    return InMemorySystemAdminRepository()


def _slice_page(items: list[dict[str, Any]], filters: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int, int]:
    page = _pagination(filters)
    total = len(items)
    return items[page["offset"] : page["offset"] + page["limit"]], page["page"], page["page_size"], total


def _page_response(items: list[dict[str, Any]], page: int = 1, page_size: int = 50, total: int | None = None) -> dict[str, Any]:
    page_info = {"page": page, "page_size": page_size, "total": len(items) if total is None else total}
    return {"items": items, "page": page_info, "page_info": page_info}


def _pagination(filters: dict[str, Any]) -> dict[str, int]:
    page = _bounded_int(filters.get("page"), 1, 1, 100000)
    page_size = _bounded_int(filters.get("page_size"), 50, 1, 100)
    return {"page": page, "page_size": page_size, "limit": page_size, "offset": (page - 1) * page_size}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _system_user(user_id: str, email: str, display_name: str, roles: list[str], status: str = "active") -> dict[str, Any]:
    return {
        "id": user_id,
        "system_user_id": user_id,
        "email": email,
        "name": display_name,
        "display_name": display_name,
        "role": roles[0] if roles else "platform_operator",
        "roles": roles,
        "status": status,
        "last_login_at": None,
    }


def _system_user_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    roles = list(row[6] or []) if len(row) > 6 else []
    if not roles:
        roles = [str(row[3])]
    return _system_user(str(row[0]), str(row[1]), str(row[2]), roles, str(row[4]))


def _organization_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    settings = row[3] or {}
    organization_id = str(row[0] or f"org-{row[1]}")
    return {
        "id": organization_id,
        "organization_id": organization_id,
        "name": str(row[1]),
        "status": str(row[2]),
        "metadata": settings,
        "external_ref": settings.get("external_ref") or organization_id,
        "contact": settings.get("contact") or {},
        "created_at": _iso(row[4]),
    }


def _store_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    readiness_status = "ready" if bool(row[7]) else "blocked"
    return {
        "id": str(row[1]),
        "store_id": str(row[1]),
        "organization_id": str(row[0]),
        "name": str(row[2]),
        "platform": str(row[3]),
        "status": str(row[4]),
        "metadata": row[5] or {},
        "external_store_id": str(row[1]),
        "readiness_status": readiness_status,
        "created_at": _iso(row[6]),
    }


def _task_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "task_id": str(row[0]),
        "task_type": str(row[1]),
        "status": str(row[2]),
        "organization_id": str(row[3]),
        "store_id": str(row[4]) if row[4] is not None else None,
        "input_ref": str(row[5] or ""),
        "output_ref": str(row[6]) if row[6] is not None else None,
        "error_summary": str(row[7]) if row[7] is not None else None,
        "retry_count": int(row[8] or 0),
        "next_retry_at": _iso(row[9]) if row[9] else None,
        "created_at": _iso(row[10]),
    }


def _audit_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    diff = row[7] or {}
    return _audit_log(
        str(row[0]),
        str(row[1]) if row[1] is not None else None,
        str(row[2]) if row[2] is not None else None,
        str(row[3]) if row[3] is not None else None,
        str(row[4]),
        str(row[5]),
        str(row[6] or ""),
        diff.get("reason"),
        diff,
        _iso(row[8]),
    )


def _audit_log(
    audit_id: str,
    actor_system_user_id: str | None,
    organization_id: str | None,
    store_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    reason: str | None,
    diff_summary: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": audit_id,
        "audit_log_id": audit_id,
        "actor_id": actor_system_user_id,
        "actor_system_user_id": actor_system_user_id,
        "actor_admin_user_id": None,
        "organization_id": organization_id,
        "store_id": store_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "reason": reason,
        "diff_summary": diff_summary,
        "sensitive_access": False,
        "created_at": created_at or _now(),
    }


def _readiness_item(
    organization_id: str,
    store_id: str,
    status: str,
    has_product: bool,
    has_price: bool,
    has_knowledge: bool,
    has_api_integration: bool,
) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "store_id": store_id,
        "status": status,
        "updated_at": _now(),
        "checks": [
            _check("product_content", has_product, "商品资料已配置", "缺少商品资料"),
            _check("price_snapshot", has_price, "价格快照已配置", "缺少价格快照"),
            _check("knowledge_review", has_knowledge, "已审核知识可召回", "缺少已审核知识"),
            _check("rules", True, "v1 默认规则已启用", "缺少规则配置", missing_status="warning"),
            _check("action_capabilities", True, "v1 动作边界已启用", "缺少动作能力配置", missing_status="warning"),
            _check("api_integration", has_api_integration, "API 接入已配置", "缺少 API 接入凭据", missing_status="warning"),
        ],
    }


def _check(
    code: str,
    ok: bool,
    ok_message: str,
    blocked_message: str,
    *,
    missing_status: str = "blocked",
) -> dict[str, str]:
    status = "pass" if ok else missing_status
    message = ok_message if ok else blocked_message
    return {"code": code, "name": code, "status": status, "message": message, "reason": message}


def _readiness_status(has_product: bool, has_price: bool, has_knowledge: bool, has_api_integration: bool) -> str:
    if has_product and has_price and has_knowledge and has_api_integration:
        return "ready"
    if has_product:
        return "warning"
    return "blocked"


def _stable_suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)
