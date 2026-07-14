from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Protocol

from psycopg import OperationalError
from psycopg.errors import UndefinedTable
from psycopg.types.json import Jsonb

from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import SystemAdminSession


_TRACE_READ_ROLES = {"super_admin", "technical_support", "security_auditor"}
_RAW_TRACE_CAPABILITY = "trace:raw_payload:read"


class SystemAdminRepository(Protocol):
    def dashboard_summary(self, session: SystemAdminSession) -> dict[str, Any]:
        raise NotImplementedError

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

    def list_message_traces(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def get_message_trace(self, session: SystemAdminSession, decision_id: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_tasks(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def retry_task(self, session: SystemAdminSession, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def list_audit_logs(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def system_health(self, session: SystemAdminSession) -> dict[str, Any]:
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
        self.product_store_ids: set[str] = set()
        self.price_snapshot_store_ids: set[str] = set()
        self.approved_knowledge_store_ids: set[str] = set()
        self.active_integration_store_ids: set[str] = set()
        self.decisions: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.releases: dict[str, dict[str, Any]] = {}
        self.audit_logs: list[dict[str, Any]] = []
        self._mutation_lock = RLock()

    def dashboard_summary(self, session: SystemAdminSession) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        decisions_today = [
            item for item in self.decisions.values() if _is_in_current_utc_day(item.get("created_at"), now)
        ]
        decision_count = len(decisions_today)
        self._audit(session, "system_admin.dashboard.get", "system_dashboard", "summary", {})
        return {
            "active_organizations": sum(item.get("status") == "active" for item in self.organizations.values()),
            "active_stores": sum(item.get("status") == "active" for item in self.stores.values()),
            "decisions_today": decision_count,
            "auto_reply_rate": _rate(sum(item.get("decision_type") == "auto_reply" for item in decisions_today), decision_count),
            "handoff_rate": _rate(sum(item.get("decision_type") == "handoff" for item in decisions_today), decision_count),
            "error_rate": _rate(sum(item.get("status") in {"error", "failed"} for item in decisions_today), decision_count),
            "readiness_blockers": sum(
                item.get("status") == "active" and not self._store_is_ready(str(item["id"]))
                for item in self.stores.values()
            ),
            "pending_tasks": sum(item.get("status") in {"queued", "running"} for item in self.tasks.values()),
            "critical_alerts": sum(item.get("status") == "failed" for item in self.tasks.values()),
            "recent_releases": sorted(
                (_recent_release(item) for item in self.releases.values()),
                key=lambda item: str(item.get("published_at") or item.get("submitted_at") or ""),
                reverse=True,
            )[:5],
            "recent_releases_status": "available",
            "recent_releases_error": None,
            "generated_at": _now(),
        }

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
        items = []
        for item in self.stores.values():
            if filters.get("organization_id") and item["organization_id"] != filters["organization_id"]:
                continue
            store_id = str(item["id"])
            has_product, has_price, has_knowledge, has_api_integration = self._store_readiness_inputs(store_id)
            items.append(
                _readiness_item(
                    item["organization_id"],
                    store_id,
                    _readiness_status(has_product, has_price, has_knowledge, has_api_integration),
                    has_product,
                    has_price,
                    has_knowledge,
                    has_api_integration,
                )
            )
        return _page_response(*_slice_page(items, filters))

    def _store_readiness_inputs(self, store_id: str) -> tuple[bool, bool, bool, bool]:
        return (
            store_id in self.product_store_ids,
            store_id in self.price_snapshot_store_ids,
            store_id in self.approved_knowledge_store_ids,
            store_id in self.active_integration_store_ids,
        )

    def _store_is_ready(self, store_id: str) -> bool:
        return all(self._store_readiness_inputs(store_id))

    def list_message_traces(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._require_trace_read(session)
        _require_trace_scope(filters)
        include_raw_payload = _truthy(filters.get("include_raw_payload"))
        self._validate_raw_trace_access_with_audit(session, "list", filters, include_raw_payload)
        audit_filters = dict(filters)
        if include_raw_payload:
            audit_filters["sensitive_access"] = True
        self._audit(session, "system_admin.message_trace.list", "decision_record", "list", audit_filters)
        return _page_response(*_slice_page([], filters))

    def get_message_trace(self, session: SystemAdminSession, decision_id: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        include_raw_payload = _truthy(filters.get("include_raw_payload"))
        self._validate_raw_trace_access_with_audit(session, decision_id, filters, include_raw_payload)
        self._require_trace_read(session)
        audit_id = self._audit(
            session,
            "system_admin.message_trace.get",
            "decision_record",
            decision_id,
            {"include_raw_payload": include_raw_payload, "reason": filters.get("reason"), "sensitive_access": include_raw_payload},
        )
        return None if audit_id else None

    def list_tasks(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        self._audit(session, "system_admin.task.list", "background_task", "list", filters)
        items = list(self.tasks.values())
        for key in ("organization_id", "store_id", "task_type", "status"):
            if filters.get(key):
                items = [item for item in items if item.get(key) == filters[key]]
        persisted_items = [{**item, "retryable": bool(item.get("retryable", False))} for item in items]
        return _page_response(*_slice_page(persisted_items, filters))

    def retry_task(self, session: SystemAdminSession, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = normalize_task_retry_payload(payload)
        self._require_any_role(session, {"super_admin", "technical_support", "platform_operator"})
        with self._mutation_lock:
            task = self.tasks.get(task_id)
            if not task:
                raise api_error(404, "not_found", f"task {task_id} not found")
            replay = self._idempotency_replay("system_admin.task.retry", payload)
            if replay:
                return _task_retry_replay_response(replay, session, task_id)
            if task["status"] != "failed" or task.get("retryable") is not True:
                raise api_error(409, "idempotency_conflict", f"task {task_id} is not retryable from status {task['status']}")
            task["status"] = "queued"
            task["retryable"] = False
            task["retry_count"] = int(task.get("retry_count", 0)) + 1
            audit_id = self._audit(session, "system_admin.task.retry", "background_task", task_id, payload)
            return {"task_id": task_id, "status": "queued", "audit_log_id": audit_id}

    def list_audit_logs(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        filters = _normalize_audit_filters(filters)
        items = list(self.audit_logs)
        for key, item_key in (
            ("actor_user_id", "actor_system_user_id"),
            ("organization_id", "organization_id"),
            ("store_id", "store_id"),
            ("action", "action"),
        ):
            if filters.get(key):
                items = [
                    item for item in items
                    if str(item.get(item_key) or (item.get("actor_id") if key == "actor_user_id" else "") or "") == str(filters[key])
                ]
        if filters.get("sensitive_access") is not None:
            expected = bool(filters["sensitive_access"])
            items = [item for item in items if bool(item.get("sensitive_access")) is expected]
        if filters.get("time_from"):
            lower = _parse_filter_datetime(filters["time_from"], "time_from")
            items = [item for item in items if _parse_filter_datetime(item.get("created_at"), "created_at") >= lower]
        if filters.get("time_to"):
            upper = _parse_filter_datetime(filters["time_to"], "time_to")
            items = [item for item in items if _parse_filter_datetime(item.get("created_at"), "created_at") < upper]
        response = _page_response(*_slice_page(items, filters))
        self._audit(session, "system_admin.audit.list", "system_admin_audit_log", "list", filters)
        return response

    def system_health(self, session: SystemAdminSession) -> dict[str, Any]:
        self._audit(session, "system_admin.health.get", "system_health", "summary", {})
        return _system_health_response("degraded", [_health_dependency("api", "healthy", "in-memory system admin")])

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

    def _require_trace_read(self, session: SystemAdminSession) -> None:
        if session.role not in _TRACE_READ_ROLES:
            raise api_error(403, "forbidden", "system admin role cannot read message traces")

    def _validate_raw_trace_access(self, session: SystemAdminSession, include_raw_payload: bool, reason: Any) -> None:
        if not include_raw_payload:
            return
        if not str(reason or "").strip():
            raise api_error(422, "audit_reason_required", "reason is required when include_raw_payload=true")
        if not _has_capability(session, _RAW_TRACE_CAPABILITY):
            raise api_error(403, "raw_payload_access_denied", "system admin role cannot read raw message payload")

    def _validate_raw_trace_access_with_audit(
        self,
        session: SystemAdminSession,
        object_id: str,
        filters: dict[str, Any],
        include_raw_payload: bool,
    ) -> None:
        if not include_raw_payload:
            return
        reason = filters.get("reason")
        if str(reason or "").strip() and _has_capability(session, _RAW_TRACE_CAPABILITY):
            return
        self._audit(
            session,
            "system_admin.message_trace.raw_payload_denied",
            "decision_record",
            object_id,
            {"reason": reason, "sensitive_access": True, "role": session.role},
        )
        self._validate_raw_trace_access(session, include_raw_payload, reason)


class PostgresSystemAdminRepository:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url

    def dashboard_summary(self, session: SystemAdminSession) -> dict[str, Any]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, None, None, "system_admin.dashboard.get", "system_dashboard", "summary", {})
                cur.execute(
                    """
                    WITH organization_totals AS (
                        SELECT count(*) FILTER (WHERE status = 'active') AS active_organizations
                        FROM organization
                    ),
                    store_totals AS (
                        SELECT
                            count(*) FILTER (WHERE status = 'active') AS active_stores,
                            count(*) FILTER (
                                WHERE status = 'active'
                                  AND (
                                      NOT EXISTS (SELECT 1 FROM product WHERE product.store_id = store.id)
                                      OR NOT EXISTS (
                                          SELECT 1 FROM product_price_snapshot price WHERE price.store_id = store.id
                                      )
                                      OR NOT EXISTS (
                                          SELECT 1 FROM knowledge_entry knowledge
                                          WHERE knowledge.store_id::text = store.id::text
                                            AND knowledge.status = 'approved'
                                      )
                                      OR NOT (
                                          EXISTS (
                                              SELECT 1 FROM platform_account account
                                              WHERE account.store_id = store.id AND account.status = 'active'
                                          )
                                          OR EXISTS (
                                              SELECT 1 FROM external_api_token token
                                              WHERE token.store_id = store.id AND token.status = 'active'
                                          )
                                      )
                                  )
                            ) AS readiness_blockers
                        FROM store
                    ),
                    today_decisions AS (
                        SELECT decision_type, status
                        FROM decision_record
                        WHERE created_at >= (
                            date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                        )
                          AND created_at < (
                              (date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + INTERVAL '1 day')
                              AT TIME ZONE 'UTC'
                          )
                          AND created_at <= CURRENT_TIMESTAMP
                    ),
                    decision_totals AS (
                        SELECT
                            count(*) AS decisions_today,
                            count(*) FILTER (WHERE decision_type = 'auto_reply')::double precision
                                / NULLIF(count(*), 0) AS auto_reply_rate,
                            count(*) FILTER (WHERE decision_type = 'handoff')::double precision
                                / NULLIF(count(*), 0) AS handoff_rate,
                            count(*) FILTER (WHERE status IN ('error', 'failed'))::double precision
                                / NULLIF(count(*), 0) AS error_rate
                        FROM today_decisions
                    ),
                    task_totals AS (
                        SELECT
                            count(*) FILTER (WHERE status IN ('queued', 'running')) AS pending_tasks,
                            count(*) FILTER (WHERE status = 'failed') AS critical_alerts
                        FROM background_task
                    )
                    SELECT
                        organization_totals.active_organizations,
                        store_totals.active_stores,
                        decision_totals.decisions_today,
                        decision_totals.auto_reply_rate,
                        decision_totals.handoff_rate,
                        decision_totals.error_rate,
                        store_totals.readiness_blockers,
                        task_totals.pending_tasks,
                        task_totals.critical_alerts,
                        CURRENT_TIMESTAMP
                    FROM organization_totals, store_totals, decision_totals, task_totals
                    """
                )
                row = cur.fetchone()

        recent_releases: list[dict[str, Any]] = []
        recent_releases_status = "available"
        recent_releases_error = None
        try:
            with self._connect(self._database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT release.id::text, org.external_organization_id,
                               release.config_version_id::text, version.version_number,
                               release.status, release.published_at, release.submitted_at
                        FROM llm_release_record release
                        JOIN organization org ON org.id = release.organization_id
                        JOIN llm_config_version version ON version.id = release.config_version_id
                        ORDER BY COALESCE(release.published_at, release.submitted_at) DESC, release.id DESC
                        LIMIT 5
                        """
                    )
                    recent_releases = [_recent_release_from_row(item) for item in cur.fetchall()]
        except (OperationalError, UndefinedTable):
            recent_releases_status = "unavailable"
            recent_releases_error = "release_data_unavailable"
        return {
            "active_organizations": int(row[0] or 0),
            "active_stores": int(row[1] or 0),
            "decisions_today": int(row[2] or 0),
            "auto_reply_rate": None if row[3] is None else float(row[3]),
            "handoff_rate": None if row[4] is None else float(row[4]),
            "error_rate": None if row[5] is None else float(row[5]),
            "readiness_blockers": int(row[6] or 0),
            "pending_tasks": int(row[7] or 0),
            "critical_alerts": int(row[8] or 0),
            "recent_releases": recent_releases,
            "recent_releases_status": recent_releases_status,
            "recent_releases_error": recent_releases_error,
            "generated_at": row[9],
        }

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
                           EXISTS(SELECT 1 FROM knowledge_entry knowledge WHERE knowledge.store_id::text = st.id::text AND knowledge.status = 'approved') AS has_knowledge,
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

    def list_message_traces(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        organization_id = filters.get("organization_id")
        store_id = filters.get("store_id")
        decision_id = filters.get("decision_id")
        external_message_id = filters.get("external_message_id")
        trace_id = filters.get("trace_id")
        status = filters.get("status")
        time_from = filters.get("created_at_from") or filters.get("time_from")
        time_to = filters.get("created_at_to") or filters.get("time_to")
        page = _pagination(filters)
        include_raw_payload = _truthy(filters.get("include_raw_payload"))
        self._validate_raw_trace_access_with_audit(session, "list", filters, include_raw_payload)
        self._require_trace_read(session)
        _require_trace_scope(filters)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                audit_filters = dict(filters)
                if include_raw_payload:
                    audit_filters["sensitive_access"] = True
                self._audit(cur, session, organization_id, store_id, "system_admin.message_trace.list", "decision_record", "list", audit_filters)
                params = (
                    organization_id,
                    organization_id,
                    store_id,
                    store_id,
                    decision_id,
                    decision_id,
                    external_message_id,
                    external_message_id,
                    trace_id,
                    trace_id,
                    trace_id,
                    trace_id,
                    status,
                    status,
                    time_from,
                    time_from,
                    time_to,
                    time_to,
                )
                cur.execute(
                    """
                    SELECT count(*)
                    FROM decision_record decision
                    JOIN organization org ON org.id::text = decision.organization_id::text
                    JOIN store st ON st.id::text = decision.store_id::text AND st.organization_id::text = org.id::text
                    LEFT JOIN message msg ON msg.id::text = decision.message_id::text
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR decision.decision_id = %s)
                      AND (%s::text IS NULL OR msg.external_message_id = %s)
                      AND (%s::text IS NULL OR EXISTS (
                          SELECT 1
                          FROM decision_trace_step step
                          WHERE step.decision_id = decision.decision_id
                            AND (step.id::text = %s OR step.summary->>'trace_id' = %s OR step.summary->>'step_id' = %s)
                      ))
                      AND (%s::text IS NULL OR decision.status = %s)
                      AND (%s::timestamptz IS NULL OR decision.created_at >= %s::timestamptz)
                      AND (%s::timestamptz IS NULL OR decision.created_at <= %s::timestamptz)
                    """,
                    params,
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT decision.decision_id, org.external_organization_id, st.external_store_id,
                           decision.request_id, msg.external_message_id, decision.decision_type,
                           decision.risk_level, decision.status, decision.created_at
                    FROM decision_record decision
                    JOIN organization org ON org.id::text = decision.organization_id::text
                    JOIN store st ON st.id::text = decision.store_id::text AND st.organization_id::text = org.id::text
                    LEFT JOIN message msg ON msg.id::text = decision.message_id::text
                    WHERE (%s::text IS NULL OR org.external_organization_id = %s)
                      AND (%s::text IS NULL OR st.external_store_id = %s)
                      AND (%s::text IS NULL OR decision.decision_id = %s)
                      AND (%s::text IS NULL OR msg.external_message_id = %s)
                      AND (%s::text IS NULL OR EXISTS (
                          SELECT 1
                          FROM decision_trace_step step
                          WHERE step.decision_id = decision.decision_id
                            AND (step.id::text = %s OR step.summary->>'trace_id' = %s OR step.summary->>'step_id' = %s)
                      ))
                      AND (%s::text IS NULL OR decision.status = %s)
                      AND (%s::timestamptz IS NULL OR decision.created_at >= %s::timestamptz)
                      AND (%s::timestamptz IS NULL OR decision.created_at <= %s::timestamptz)
                    ORDER BY decision.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, page["limit"], page["offset"]),
                )
                return _page_response([_message_trace_summary_from_row(row) for row in cur.fetchall()], page["page"], page["page_size"], total)

    def get_message_trace(self, session: SystemAdminSession, decision_id: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        include_raw_payload = _truthy(filters.get("include_raw_payload"))
        self._validate_raw_trace_access_with_audit(session, decision_id, filters, include_raw_payload)
        self._require_trace_read(session)
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT decision.decision_id, org.external_organization_id, st.external_store_id,
                           decision.request_id, msg.external_message_id, msg.platform,
                           conv.external_conversation_id, decision.decision_type,
                           (decision.response_payload->>'confidence')::float,
                           decision.risk_level,
                           COALESCE(checkpoint.state, checkpoint.state_json, jsonb_build_object(
                               'request', jsonb_build_object(
                                   'request_id', decision.request_id,
                                   'platform', msg.platform,
                                   'store_id', st.external_store_id,
                                   'conversation', jsonb_build_object('external_conversation_id', conv.external_conversation_id),
                                   'message', jsonb_build_object('external_message_id', msg.external_message_id)
                               ),
                               'response', decision.response_payload
                           )) AS state_payload,
                           decision.created_at
                    FROM decision_record decision
                    JOIN organization org ON org.id::text = decision.organization_id::text
                    JOIN store st ON st.id::text = decision.store_id::text AND st.organization_id::text = org.id::text
                    LEFT JOIN message msg ON msg.id::text = decision.message_id::text
                    LEFT JOIN conversation conv ON conv.id::text = decision.conversation_id::text
                    LEFT JOIN LATERAL (
                        SELECT checkpoint.state, checkpoint.state_json
                        FROM decision_graph_checkpoint checkpoint
                        WHERE checkpoint.decision_id = decision.decision_id
                          AND (checkpoint.organization_id IS NULL OR checkpoint.organization_id::text = decision.organization_id::text)
                          AND (checkpoint.store_id IS NULL OR checkpoint.store_id::text = decision.store_id::text)
                          AND (
                              checkpoint.checkpoint_key = 'latest'
                              OR checkpoint.node_name IN ('persist_trace', 'latest')
                              OR checkpoint.checkpoint_key IS NULL
                          )
                        ORDER BY (checkpoint.checkpoint_key = 'latest') DESC, checkpoint.created_at DESC
                        LIMIT 1
                    ) checkpoint ON true
                    WHERE decision.decision_id = %s
                    """,
                    (decision_id,),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        """
                        SELECT legacy.decision_id, legacy.organization_id, legacy.store_id,
                               legacy.request_id,
                               legacy.request_payload->'message'->>'external_message_id',
                               legacy.request_payload->>'platform',
                               legacy.request_payload->'conversation'->>'external_conversation_id',
                               legacy.response_payload->>'action',
                               (legacy.response_payload->>'confidence')::float,
                               legacy.response_payload->>'risk_level',
                               legacy.state_payload,
                               legacy.created_at
                        FROM app_decision_state legacy
                        WHERE legacy.decision_id = %s
                        """,
                        (decision_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                cur.execute(
                    """
                    SELECT step.id::text, step.step_name, step.step_order, step.status, step.summary, step.created_at
                    FROM decision_trace_step step
                    WHERE step.decision_id = %s
                    ORDER BY step.step_order ASC
                    """,
                    (decision_id,),
                )
                trace_steps = cur.fetchall()
                cur.execute(
                    """
                    SELECT snapshot.context_request_id, snapshot.context_type, snapshot.source, snapshot.payload, snapshot.captured_at
                    FROM context_snapshot snapshot
                    WHERE snapshot.decision_id = %s
                    ORDER BY snapshot.captured_at ASC
                    """,
                    (decision_id,),
                )
                context_snapshots = cur.fetchall()
                cur.execute(
                    """
                    SELECT action.action_id, action.action_type, action.status, action.request_payload,
                           result.status, result.result_payload, COALESCE(result.received_at, action.updated_at)
                    FROM action_request action
                    LEFT JOIN action_result result
                      ON result.decision_id = action.decision_id
                     AND result.action_id = action.action_id
                    WHERE action.decision_id = %s
                    ORDER BY action.created_at ASC
                    """,
                    (decision_id,),
                )
                action_rows = cur.fetchall()
                organization_id = str(row[1])
                store_id = str(row[2])
                audit_id = self._audit(
                    cur,
                    session,
                    organization_id,
                    store_id,
                    "system_admin.message_trace.get",
                    "decision_record",
                    decision_id,
                    {
                        "include_raw_payload": include_raw_payload,
                        "reason": filters.get("reason"),
                        "sensitive_access": include_raw_payload,
                    },
                )
                return _message_trace_detail_from_row(row, trace_steps, context_snapshots, action_rows, audit_id, include_raw_payload)

    def system_health(self, session: SystemAdminSession) -> dict[str, Any]:
        self._require_any_role(session, {"super_admin", "technical_support", "security_auditor", "platform_operator", "release_admin"})
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(cur, session, None, None, "system_admin.health.get", "system_health", "summary", {})
                cur.execute(
                    """
                    SELECT
                        EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') AS has_pgcrypto,
                        EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') AS has_pgvector,
                        (SELECT count(*) FROM background_task WHERE status = 'failed' AND retryable = true) AS retryable_failed_tasks,
                        (SELECT count(*) FROM background_task WHERE status IN ('queued', 'running')) AS active_tasks
                    """
                )
                row = cur.fetchone()
        has_pgcrypto = bool(row[0])
        has_pgvector = bool(row[1])
        failed_tasks = int(row[2] or 0)
        active_tasks = int(row[3] or 0)
        dependencies = [
            _health_dependency("api", "healthy", "system admin API reachable"),
            _health_dependency("postgresql", "healthy" if has_pgcrypto else "degraded", "query succeeded; pgcrypto installed" if has_pgcrypto else "query succeeded; pgcrypto missing"),
            _health_dependency("pgvector", "healthy" if has_pgvector else "degraded", "extension installed" if has_pgvector else "extension missing"),
            _health_dependency("queue", "degraded" if failed_tasks else "healthy", f"retryable_failed={failed_tasks} active={active_tasks}"),
        ]
        status = "degraded" if any(item["status"] != "healthy" for item in dependencies) else "healthy"
        return _system_health_response(status, dependencies)

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
                    SELECT task.task_id, task.task_type, task.status, task.retryable,
                           org.external_organization_id, st.external_store_id,
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
        payload = normalize_task_retry_payload(payload)
        self._require_any_role(session, {"super_admin", "technical_support", "platform_operator"})
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._lock_idempotency_key(cur, "system_admin.task.retry", payload.get("idempotency_key"))
                replay = self._find_idempotency(cur, "system_admin.task.retry", payload.get("idempotency_key"))
                if replay:
                    return _task_retry_replay_response(replay, session, task_id)
                cur.execute(
                    """
                    SELECT task.status, task.retryable, org.external_organization_id, st.external_store_id
                    FROM background_task task
                    JOIN organization org ON org.id = task.organization_id
                    LEFT JOIN store st ON st.id = task.store_id AND st.organization_id = task.organization_id
                    WHERE task.task_id = %s
                    FOR UPDATE OF task
                    """,
                    (task_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise api_error(404, "not_found", f"task {task_id} not found")
                if str(row[0]) != "failed" or not bool(row[1]):
                    replay = self._find_idempotency(cur, "system_admin.task.retry", payload.get("idempotency_key"))
                    if replay:
                        return _task_retry_replay_response(replay, session, task_id)
                    raise api_error(409, "idempotency_conflict", f"task {task_id} is not retryable from status {row[0]}")
                cur.execute(
                    """
                    UPDATE background_task
                    SET status = 'queued',
                        retryable = false,
                        retry_count = retry_count + 1,
                        next_retry_at = NULL,
                        metadata = metadata || %s,
                        updated_at = now()
                    WHERE task_id = %s
                    """,
                    (Jsonb({"retry_reason": payload.get("reason")}), task_id),
                )
                audit_id = self._audit(cur, session, row[2], row[3], "system_admin.task.retry", "background_task", task_id, payload)
                return {"task_id": task_id, "status": "queued", "audit_log_id": audit_id}

    def _lock_idempotency_key(self, cur: Any, action: str, idempotency_key: Any) -> None:
        if not idempotency_key:
            return
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{action}:{idempotency_key}",),
        )

    def list_audit_logs(self, session: SystemAdminSession, filters: dict[str, Any]) -> dict[str, Any]:
        filters = _normalize_audit_filters(filters)
        organization_id = filters.get("organization_id")
        store_id = filters.get("store_id")
        actor_user_id = filters.get("actor_user_id")
        action = filters.get("action")
        sensitive_access = filters.get("sensitive_access")
        time_from = filters.get("time_from")
        time_to = filters.get("time_to")
        page = _pagination(filters)
        query_params = (
            organization_id, organization_id,
            store_id, store_id,
            actor_user_id, actor_user_id,
            action, action,
            sensitive_access, sensitive_access,
            time_from, time_from,
            time_to, time_to,
        )
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
                      AND (%s::text IS NULL OR audit.action = %s)
                      AND (%s::boolean IS NULL OR COALESCE((audit.diff_summary->>'sensitive_access')::boolean, false) = %s::boolean)
                      AND (%s::timestamptz IS NULL OR audit.created_at >= %s::timestamptz)
                      AND (%s::timestamptz IS NULL OR audit.created_at < %s::timestamptz)
                    """,
                    query_params,
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
                      AND (%s::text IS NULL OR audit.action = %s)
                      AND (%s::boolean IS NULL OR COALESCE((audit.diff_summary->>'sensitive_access')::boolean, false) = %s::boolean)
                      AND (%s::timestamptz IS NULL OR audit.created_at >= %s::timestamptz)
                      AND (%s::timestamptz IS NULL OR audit.created_at < %s::timestamptz)
                    ORDER BY audit.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*query_params, page["limit"], page["offset"]),
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
            SELECT id::text, object_id, system_admin_user_id::text
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
        return {
            "audit_log_id": str(row[0]),
            "object_id": str(row[1]),
            "actor_user_id": str(row[2]) if len(row) > 2 and row[2] is not None else "",
        }

    def _require_any_role(self, session: SystemAdminSession, roles: set[str]) -> None:
        if session.role not in roles:
            raise api_error(403, "forbidden", "system admin role cannot modify this resource")

    def _require_trace_read(self, session: SystemAdminSession) -> None:
        if session.role not in _TRACE_READ_ROLES:
            raise api_error(403, "forbidden", "system admin role cannot read message traces")

    def _validate_raw_trace_access(self, session: SystemAdminSession, include_raw_payload: bool, reason: Any) -> None:
        if not include_raw_payload:
            return
        if not str(reason or "").strip():
            raise api_error(422, "audit_reason_required", "reason is required when include_raw_payload=true")
        if not _has_capability(session, _RAW_TRACE_CAPABILITY):
            raise api_error(403, "raw_payload_access_denied", "system admin role cannot read raw message payload")

    def _validate_raw_trace_access_with_audit(
        self,
        session: SystemAdminSession,
        object_id: str,
        filters: dict[str, Any],
        include_raw_payload: bool,
    ) -> None:
        if not include_raw_payload:
            return
        reason = filters.get("reason")
        if str(reason or "").strip() and _has_capability(session, _RAW_TRACE_CAPABILITY):
            return
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._audit(
                    cur,
                    session,
                    filters.get("organization_id"),
                    filters.get("store_id"),
                    "system_admin.message_trace.raw_payload_denied",
                    "decision_record",
                    object_id,
                    {"reason": reason, "sensitive_access": True, "role": session.role},
                )
        self._validate_raw_trace_access(session, include_raw_payload, reason)


def system_admin_repository_for(settings: Settings) -> SystemAdminRepository:
    if settings.environment.lower() == "test":
        return InMemorySystemAdminRepository()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for System Admin outside test")
    return PostgresSystemAdminRepository(settings.database_url)


def _slice_page(items: list[dict[str, Any]], filters: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int, int]:
    page = _pagination(filters)
    total = len(items)
    return items[page["offset"] : page["offset"] + page["limit"]], page["page"], page["page_size"], total


def _page_response(items: list[dict[str, Any]], page: int = 1, page_size: int = 20, total: int | None = None) -> dict[str, Any]:
    page_info = {"page": page, "page_size": page_size, "total": len(items) if total is None else total}
    return {"items": items, "page": page_info, "page_info": page_info}


def _pagination(filters: dict[str, Any]) -> dict[str, int]:
    page = _bounded_int(filters.get("page"), 1, 1, 100000)
    page_size = _bounded_int(filters.get("page_size"), 20, 1, 100)
    return {"page": page, "page_size": page_size, "limit": page_size, "offset": (page - 1) * page_size}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _is_in_current_utc_day(value: Any, now: datetime) -> bool:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_start = day_start + timedelta(days=1)
    return day_start <= timestamp < next_day_start and timestamp <= now


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
        "retryable": bool(row[3]),
        "organization_id": str(row[4]),
        "store_id": str(row[5]) if row[5] is not None else None,
        "input_ref": str(row[6] or ""),
        "output_ref": str(row[7]) if row[7] is not None else None,
        "error_summary": str(row[8]) if row[8] is not None else None,
        "retry_count": int(row[9] or 0),
        "next_retry_at": _iso(row[10]) if row[10] else None,
        "created_at": _iso(row[11]),
    }


def _recent_release(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_id": str(item["release_id"]),
        "organization_id": str(item["organization_id"]),
        "config_version_id": str(item["config_version_id"]),
        "version_number": int(item["version_number"]),
        "status": str(item["status"]),
        "published_at": item.get("published_at"),
        "submitted_at": item.get("submitted_at"),
    }


def _recent_release_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return _recent_release({
        "release_id": row[0],
        "organization_id": row[1],
        "config_version_id": row[2],
        "version_number": row[3],
        "status": row[4],
        "published_at": _iso(row[5]) if row[5] is not None else None,
        "submitted_at": _iso(row[6]) if row[6] is not None else None,
    })


def _message_trace_summary_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "decision_id": str(row[0]),
        "organization_id": str(row[1]),
        "store_id": str(row[2]),
        "request_id": str(row[3]),
        "external_message_id": str(row[4]) if row[4] is not None else None,
        "action": str(row[5]),
        "risk_level": str(row[6]),
        "status": str(row[7]),
        "sensitive_access": False,
        "created_at": _iso(row[8]),
    }


def _message_trace_detail_from_row(
    row: tuple[Any, ...],
    trace_step_rows: list[tuple[Any, ...]],
    context_snapshot_rows: list[tuple[Any, ...]],
    action_rows: list[tuple[Any, ...]],
    audit_id: str,
    include_raw_payload: bool,
) -> dict[str, Any]:
    state = row[10] or {}
    request = state.get("request") or {}
    response = state.get("response") or {}
    trace_payload = dict(response.get("trace") or {})
    if trace_step_rows:
        trace_payload["steps"] = [_trace_step_from_row(item) for item in trace_step_rows]
    else:
        trace_payload.setdefault("steps", [])
    trace_payload.setdefault("graph_version", "reply-decision-graph-v1")
    trace_payload.setdefault("model_version", response.get("model_version") or "deterministic-v1")
    trace = {
        "decision_id": str(row[0]),
        "message_id": row[4],
        "external_message_id": row[4],
        "request_id": row[3],
        "platform": row[5],
        "store_id": row[2],
        "conversation_id": row[6],
            "action": row[7],
            "confidence": row[8],
            "risk_level": row[9],
            "sections": {
                "ingest": {"status": "completed"},
                "normalization": {"status": "completed"},
            "retrieval": {"status": "completed", "context_snapshots": [_context_snapshot_from_row(item, include_raw_payload) for item in context_snapshot_rows]},
            "generation": {"status": "completed"},
            "risk_and_policy": {"status": "completed"},
            "persistence": {"status": "completed", "action_requests": [_action_trace_from_row(item, include_raw_payload) for item in action_rows]},
            "feedback": {"status": "completed" if state.get("feedback") else "pending"},
        },
        "trace": trace_payload,
    }
    detail = {"trace": trace, "audit_log_id": audit_id}
    if include_raw_payload:
        detail["raw_payload"] = request
    return detail


def _trace_step_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    summary = row[4] or {}
    created_at = _iso(row[5])
    return {
        "step_id": str(summary.get("step_id") or summary.get("trace_id") or row[0]),
        "name": str(summary.get("name") or row[1]),
        "status": str(summary.get("status") or row[3]),
        "started_at": str(summary.get("started_at") or created_at),
        "ended_at": str(summary.get("ended_at") or created_at),
        "inputs_ref": list(summary.get("inputs_ref") or []),
        "outputs_ref": list(summary.get("outputs_ref") or []),
        "error": summary.get("error"),
    }


def _context_snapshot_from_row(row: tuple[Any, ...], include_raw_payload: bool) -> dict[str, Any]:
    snapshot = {
        "context_snapshot_id": str(row[0]),
        "context_type": str(row[1]),
        "source": str(row[2]),
        "captured_at": _iso(row[4]),
    }
    if include_raw_payload:
        snapshot["payload"] = row[3] or {}
    return snapshot


def _action_trace_from_row(row: tuple[Any, ...], include_raw_payload: bool) -> dict[str, Any]:
    action = {
        "action_id": str(row[0]),
        "action_type": str(row[1]),
        "status": str(row[2]),
        "result_status": str(row[4]) if row[4] is not None else None,
        "updated_at": _iso(row[6]),
    }
    if include_raw_payload:
        action["request_payload"] = row[3] or {}
        action["result_payload"] = row[5] or {}
    return action


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
        "sensitive_access": bool(diff_summary.get("sensitive_access")),
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


def _task_retry_replay_response(
    replay: dict[str, Any],
    session: SystemAdminSession,
    task_id: str,
) -> dict[str, str]:
    actor_user_id = str(
        replay.get("actor_user_id")
        or replay.get("actor_system_user_id")
        or replay.get("actor_id")
        or ""
    )
    if str(replay.get("object_id") or "") != task_id or actor_user_id != session.user_id:
        raise api_error(409, "idempotency_conflict", "idempotency key belongs to a different task or system admin")
    return {"task_id": task_id, "status": "queued", "audit_log_id": str(replay["audit_log_id"])}


def normalize_task_retry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_idempotency_key = normalized.get("idempotency_key")
    raw_reason = normalized.get("reason")
    if not isinstance(raw_idempotency_key, str) or not isinstance(raw_reason, str):
        raise api_error(422, "validation_error", "idempotency_key and reason must be strings")
    idempotency_key = raw_idempotency_key.strip()
    reason = raw_reason.strip()
    if not idempotency_key or len(idempotency_key) > 128:
        raise api_error(422, "validation_error", "idempotency_key must contain 1 to 128 characters")
    if not reason or len(reason) > 512:
        raise api_error(422, "validation_error", "reason must contain 1 to 512 characters")
    normalized["idempotency_key"] = idempotency_key
    normalized["reason"] = reason
    return normalized


def _parse_filter_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise api_error(422, "validation_error", f"{field} must be an ISO 8601 timestamp with timezone") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise api_error(422, "validation_error", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _normalize_audit_filters(filters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(filters)
    for field in ("actor_user_id", "organization_id", "store_id", "action"):
        if normalized.get(field) is None:
            continue
        value = str(normalized[field]).strip()
        if not value or len(value) > 256 or any(ord(char) < 32 for char in value):
            raise api_error(422, "validation_error", f"{field} is invalid")
        normalized[field] = value
    if normalized.get("sensitive_access") is not None:
        value = normalized["sensitive_access"]
        if isinstance(value, bool):
            normalized["sensitive_access"] = value
        elif str(value).lower() in {"true", "false"}:
            normalized["sensitive_access"] = str(value).lower() == "true"
        else:
            raise api_error(422, "validation_error", "sensitive_access must be true or false")
    parsed_bounds: dict[str, datetime] = {}
    for field in ("time_from", "time_to"):
        if normalized.get(field) is not None:
            parsed = _parse_filter_datetime(normalized[field], field)
            parsed_bounds[field] = parsed
            normalized[field] = parsed.isoformat().replace("+00:00", "Z")
    if parsed_bounds.get("time_from") and parsed_bounds.get("time_to") and parsed_bounds["time_from"] >= parsed_bounds["time_to"]:
        raise api_error(422, "validation_error", "time_from must be earlier than time_to")
    return normalized


def _truthy(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _has_capability(session: SystemAdminSession, capability: str) -> bool:
    capabilities = session.capabilities
    if capabilities is None:
        if session.role == "super_admin":
            return True
        return False
    return capability in capabilities


def _require_trace_scope(filters: dict[str, Any]) -> None:
    scoped_keys = {
        "organization_id",
        "store_id",
        "decision_id",
        "external_message_id",
        "trace_id",
        "created_at_from",
        "created_at_to",
        "time_from",
        "time_to",
    }
    if not any(filters.get(key) for key in scoped_keys):
        raise api_error(422, "tenant_scope_required", "message trace query requires a tenant, trace, message, decision, or time scope")


def _system_health_response(status: str, dependencies: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": status, "checked_at": _now(), "dependencies": dependencies}


def _health_dependency(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message, "checked_at": _now()}


def _stable_suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)
