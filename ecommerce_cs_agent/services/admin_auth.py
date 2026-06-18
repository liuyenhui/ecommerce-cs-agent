from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.api.auth import Principal
from ecommerce_cs_agent.api.errors import api_error
from ecommerce_cs_agent.core.config import Settings


@dataclass
class AdminSession:
    token: str
    user_id: str
    active_organization_id: str
    active_store_id: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass
class SystemAdminSession:
    token: str
    user_id: str
    email: str
    display_name: str
    role: str
    expires_at: datetime
    revoked_at: datetime | None = None


class InMemoryAdminAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.organizations: dict[str, dict[str, Any]] = {
            "org-001": {"id": "org-001", "name": "Demo Organization", "status": "active", "metadata": {}}
        }
        self.stores: dict[str, dict[str, Any]] = {
            "store-001": {
                "id": "store-001",
                "organization_id": "org-001",
                "name": "Demo PDD Store",
                "platform": "pdd",
                "status": "active",
                "metadata": {},
                "settings": {},
            }
        }
        self.users: dict[str, dict[str, Any]] = {
            "admin-001": {
                "user_id": "admin-001",
                "email": settings.admin_initial_email,
                "display_name": "Customer Admin",
                "roles": ["owner"],
                "organization_ids": ["org-001"],
                "store_ids": ["store-001"],
                "status": "active",
                "last_login_at": None,
            }
        }
        self.sessions: dict[str, AdminSession] = {
            settings.admin_session: AdminSession(
                token=settings.admin_session,
                user_id="admin-001",
                active_organization_id="org-001",
                active_store_id="store-001",
                expires_at=_now_dt() + timedelta(days=1),
            )
        }
        self.audit_logs: list[dict[str, Any]] = []
        self.invitations: dict[str, dict[str, Any]] = {}

    def login(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        email = payload.get("email")
        password = payload.get("password")
        if not _password_matches(email, password, self.settings.admin_initial_email, self.settings.admin_initial_password_hash):
            raise api_error(401, "unauthorized", "invalid admin credentials")
        organization_id = str(payload.get("organization_id") or "org-001")
        if organization_id not in self.organizations:
            raise api_error(403, "forbidden", "admin user cannot access organization")
        token = secrets.token_urlsafe(32)
        self.sessions[token] = AdminSession(
            token=token,
            user_id="admin-001",
            active_organization_id=organization_id,
            active_store_id="store-001",
            expires_at=_now_dt() + timedelta(hours=8),
        )
        self.users["admin-001"]["last_login_at"] = _now()
        self._audit("admin-001", organization_id, None, "auth.login", "admin_session", "current", {"reason": "login"})
        return self.me(self.sessions[token]), token

    def logout(self, token: str) -> None:
        session = self.sessions.get(token)
        if not session or session.revoked_at:
            raise api_error(401, "unauthorized", "missing customer admin session")
        session.revoked_at = _now_dt()
        self._audit(session.user_id, session.active_organization_id, session.active_store_id, "auth.logout", "admin_session", "current", {"reason": "logout"})

    def require_session(self, cookie: str | None, authorization: str | None) -> tuple[Principal, AdminSession]:
        if authorization and authorization.startswith("Bearer "):
            raise api_error(403, "forbidden", "external API token cannot access customer admin")
        token = _parse_cookie(cookie).get("agent_admin_session")
        session = self.sessions.get(token or "")
        if not session or session.revoked_at or session.expires_at <= _now_dt():
            raise api_error(401, "unauthorized", "missing customer admin session")
        user = self.users[session.user_id]
        principal = Principal(
            "customer_admin",
            session.user_id,
            session.active_organization_id,
            session.active_store_id,
            user["roles"][0],
        )
        return principal, session

    def me(self, session: AdminSession) -> dict[str, Any]:
        user = self.users[session.user_id]
        return {
            "user": user,
            "organizations": self.list_organizations(session)["organizations"],
            "stores": self.list_stores(session, session.active_organization_id)["stores"],
            "active_organization_id": session.active_organization_id,
            "active_store_id": session.active_store_id,
        }

    def list_organizations(self, session: AdminSession) -> dict[str, Any]:
        user = self.users[session.user_id]
        organizations = [self.organizations[item] for item in user.get("organization_ids", []) if item in self.organizations]
        return {"organizations": organizations, "items": organizations, "page": _page(len(organizations))}

    def list_stores(self, session: AdminSession, organization_id: str | None = None) -> dict[str, Any]:
        self._assert_org_access(session, organization_id or session.active_organization_id)
        user = self.users[session.user_id]
        stores = [
            self.stores[item]
            for item in user.get("store_ids", [])
            if item in self.stores and self.stores[item]["organization_id"] == (organization_id or session.active_organization_id)
        ]
        public = [{key: value for key, value in item.items() if key != "settings"} for item in stores]
        return {"stores": public, "items": public, "page": _page(len(public))}

    def update_store_settings(self, session: AdminSession, store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or session.active_organization_id)
        self._assert_store_access(session, organization_id, store_id)
        settings_patch = payload.get("settings") or {}
        self.stores[store_id]["settings"].update(settings_patch)
        audit_id = self._audit(session.user_id, organization_id, store_id, "store.settings.update", "store", store_id, payload)
        return {
            "store_id": store_id,
            "organization_id": organization_id,
            "settings": dict(self.stores[store_id]["settings"]),
            "updated_at": _now(),
            "audit_log_id": audit_id,
        }

    def list_users(self, session: AdminSession, organization_id: str | None = None) -> dict[str, Any]:
        organization_id = organization_id or session.active_organization_id
        self._assert_org_access(session, organization_id)
        users = [
            user for user in self.users.values()
            if organization_id in user.get("organization_ids", [])
        ]
        return {"items": users, "page_info": _page_info(len(users)), "page": _page(len(users))}

    def create_invitation(self, session: AdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or session.active_organization_id)
        self._assert_org_access(session, organization_id)
        invitation_id = f"inv-{uuid.uuid4().hex[:12]}"
        invitation = {
            "invitation_id": invitation_id,
            "organization_id": organization_id,
            "email": payload.get("email", ""),
            "roles": payload.get("roles", []),
            "store_ids": payload.get("store_ids", []),
            "status": "pending",
            "expires_at": (_now_dt() + timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "audit_log_id": self._audit(session.user_id, organization_id, None, "admin.invitation.create", "admin_invitation", invitation_id, payload),
        }
        self.invitations[invitation_id] = invitation
        return invitation

    def update_roles(self, session: AdminSession, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or session.active_organization_id)
        self._assert_org_access(session, organization_id)
        user = self.users.get(user_id)
        if not user:
            raise api_error(404, "not_found", "admin user not found")
        user["roles"] = payload.get("roles", user["roles"])
        user["store_ids"] = payload.get("store_ids", user.get("store_ids", []))
        audit_id = self._audit(session.user_id, organization_id, None, "admin.user.roles.update", "admin_user", user_id, payload)
        return {"user": user, "audit_log_id": audit_id}

    def list_audit_logs(self, session: AdminSession, organization_id: str | None = None) -> dict[str, Any]:
        organization_id = organization_id or session.active_organization_id
        self._assert_org_access(session, organization_id)
        items = [item for item in self.audit_logs if item.get("organization_id") == organization_id]
        return {"items": items, "page": _page(len(items)), "page_info": _page_info(len(items))}

    def _assert_org_access(self, session: AdminSession, organization_id: str) -> None:
        if organization_id not in self.users[session.user_id].get("organization_ids", []):
            raise api_error(403, "forbidden", "admin user cannot access organization")

    def _assert_store_access(self, session: AdminSession, organization_id: str, store_id: str) -> None:
        self._assert_org_access(session, organization_id)
        store = self.stores.get(store_id)
        if not store or store["organization_id"] != organization_id or store_id not in self.users[session.user_id].get("store_ids", []):
            raise api_error(403, "forbidden", "admin user cannot access store")

    def _audit(
        self,
        actor_id: str,
        organization_id: str,
        store_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> str:
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        self.audit_logs.insert(
            0,
            {
                "id": audit_id,
                "audit_log_id": audit_id,
                "scope": "admin",
                "organization_id": organization_id,
                "store_id": store_id,
                "actor_id": actor_id,
                "actor_admin_user_id": actor_id,
                "action": action,
                "object_type": object_type,
                "object_id": object_id,
                "reason": diff_summary.get("reason"),
                "diff_summary": diff_summary,
                "sensitive_access": False,
                "created_at": _now(),
            },
        )
        return audit_id


class PostgresAdminAuthService:
    def __init__(self, settings: Settings) -> None:
        import psycopg

        self.settings = settings
        self._connect = psycopg.connect

    def login(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        email = str(payload.get("email", ""))
        password = payload.get("password")
        organization_id = str(payload.get("organization_id") or "org-001")
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                self._bootstrap_initial_admin(cur, organization_id)
                cur.execute(
                    """
                    SELECT admin.id, org.id, st.id, admin.email, admin.password_hash,
                           admin.display_name, membership.roles,
                           org.external_organization_id, st.external_store_id
                    FROM admin_user admin
                    JOIN organization org ON org.id = admin.organization_id
                    JOIN admin_membership membership ON membership.admin_user_id = admin.id
                     AND membership.organization_id = org.id
                     AND membership.status = 'active'
                    LEFT JOIN store st ON st.organization_id = org.id
                    WHERE admin.email = %s
                      AND org.external_organization_id = %s
                      AND admin.status = 'active'
                    LIMIT 1
                    """,
                    (email, organization_id),
                )
                row = cur.fetchone()
                if not row or not _password_matches(email, password, row[3], row[4]):
                    raise api_error(401, "unauthorized", "invalid admin credentials")
                token = secrets.token_urlsafe(32)
                session_hash = _hash_session(token)
                cur.execute(
                    """
                    INSERT INTO admin_session (
                        organization_id, admin_user_id, session_hash, active_store_id,
                        expires_at, last_seen_at, request_metadata
                    )
                    VALUES (%s, %s, %s, %s, now() + interval '8 hours', now(), %s)
                    """,
                    (row[1], row[0], session_hash, row[2], Jsonb({"source": "admin_login"})),
                )
                session = AdminSession(
                    token=token,
                    user_id=str(row[0]),
                    active_organization_id=str(row[7]),
                    active_store_id=str(row[8]),
                    expires_at=_now_dt() + timedelta(hours=8),
                )
                return self._auth_response_from_row(row, session), token

    def logout(self, token: str) -> None:
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE admin_session
                    SET revoked_at = now()
                    WHERE session_hash = %s AND revoked_at IS NULL
                    """,
                    (_hash_session(token),),
                )

    def require_session(self, cookie: str | None, authorization: str | None) -> tuple[Principal, AdminSession]:
        if authorization and authorization.startswith("Bearer "):
            raise api_error(403, "forbidden", "external API token cannot access customer admin")
        token = _parse_cookie(cookie).get("agent_admin_session")
        if not token:
            raise api_error(401, "unauthorized", "missing customer admin session")
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT admin.id, org.id, st.id, admin.email, admin.display_name,
                           membership.roles, org.external_organization_id, st.external_store_id
                    FROM admin_session session
                    JOIN admin_user admin ON admin.id = session.admin_user_id
                    JOIN organization org ON org.id = session.organization_id
                    JOIN admin_membership membership ON membership.admin_user_id = admin.id
                     AND membership.organization_id = org.id
                     AND membership.status = 'active'
                    LEFT JOIN store st ON st.id = session.active_store_id
                    WHERE session.session_hash = %s
                      AND session.revoked_at IS NULL
                      AND session.expires_at > now()
                      AND admin.status = 'active'
                    LIMIT 1
                    """,
                    (_hash_session(token),),
                )
                row = cur.fetchone()
                if not row:
                    raise api_error(401, "unauthorized", "missing customer admin session")
                session = AdminSession(
                    token=token,
                    user_id=str(row[0]),
                    active_organization_id=str(row[6]),
                    active_store_id=str(row[7]),
                    expires_at=_now_dt() + timedelta(hours=1),
                )
                roles = list(row[5] or ["owner"])
                principal = Principal("customer_admin", session.user_id, session.active_organization_id, session.active_store_id, roles[0])
                return principal, session

    def me(self, session: AdminSession) -> dict[str, Any]:
        return {
            "user": {
                "user_id": session.user_id,
                "email": self.settings.admin_initial_email,
                "display_name": "Customer Admin",
                "roles": ["owner"],
                "organization_ids": [session.active_organization_id],
                "store_ids": [session.active_store_id],
                "status": "active",
                "last_login_at": None,
            },
            "organizations": [{"id": session.active_organization_id, "name": session.active_organization_id, "status": "active", "metadata": {}}],
            "stores": [{"id": session.active_store_id, "organization_id": session.active_organization_id, "name": session.active_store_id, "platform": "pdd", "status": "active", "metadata": {}}],
            "active_organization_id": session.active_organization_id,
            "active_store_id": session.active_store_id,
        }

    def list_organizations(self, session: AdminSession) -> dict[str, Any]:
        items = self.me(session)["organizations"]
        return {"organizations": items, "items": items, "page": _page(len(items))}

    def list_stores(self, session: AdminSession, organization_id: str | None = None) -> dict[str, Any]:
        if organization_id and organization_id != session.active_organization_id:
            raise api_error(403, "forbidden", "admin user cannot access organization")
        items = self.me(session)["stores"]
        return {"stores": items, "items": items, "page": _page(len(items))}

    def update_store_settings(self, session: AdminSession, store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or session.active_organization_id)
        settings_patch = payload.get("settings") or {}
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE store
                    SET settings = settings || %s::jsonb,
                        updated_at = now()
                    WHERE external_store_id = %s
                      AND organization_id = (
                        SELECT id FROM organization WHERE external_organization_id = %s
                      )
                    """,
                    (Jsonb(settings_patch), store_id, organization_id),
                )
                audit_id = self._audit(cur, session, organization_id, store_id, "store.settings.update", "store", store_id, payload)
        return {
            "store_id": store_id,
            "organization_id": organization_id,
            "settings": settings_patch,
            "updated_at": _now(),
            "audit_log_id": audit_id,
        }

    def list_users(self, session: AdminSession, organization_id: str | None = None) -> dict[str, Any]:
        return {"items": [self.me(session)["user"]], "page_info": _page_info(1), "page": _page(1)}

    def create_invitation(self, session: AdminSession, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or session.active_organization_id)
        invitation_id = f"inv-{uuid.uuid4().hex[:12]}"
        expires_at = (_now_dt() + timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_invitation (
                        organization_id, email, display_name, roles, store_ids,
                        status, token_hash, idempotency_key, invited_by_admin_user_id, expires_at
                    )
                    VALUES (
                        (SELECT id FROM organization WHERE external_organization_id = %s),
                        %s,
                        %s,
                        %s,
                        ARRAY(
                            SELECT st.id FROM store st
                            JOIN organization org ON org.id = st.organization_id
                            WHERE org.external_organization_id = %s
                              AND st.external_store_id = ANY(%s)
                        )::uuid[],
                        'pending',
                        %s,
                        %s,
                        %s,
                        now() + interval '7 days'
                    )
                    ON CONFLICT (organization_id, idempotency_key)
                    DO UPDATE SET roles = EXCLUDED.roles, store_ids = EXCLUDED.store_ids
                    """,
                    (
                        organization_id,
                        payload.get("email"),
                        payload.get("display_name"),
                        list(payload.get("roles", [])),
                        organization_id,
                        list(payload.get("store_ids", [])),
                        _hash_session(invitation_id),
                        payload.get("idempotency_key"),
                        session.user_id,
                    ),
                )
                audit_id = self._audit(cur, session, organization_id, None, "admin.invitation.create", "admin_invitation", invitation_id, payload)
        return {
            "invitation_id": invitation_id,
            "organization_id": organization_id,
            "email": payload.get("email"),
            "roles": payload.get("roles", []),
            "store_ids": payload.get("store_ids", []),
            "status": "pending",
            "expires_at": expires_at,
            "audit_log_id": audit_id,
        }

    def update_roles(self, session: AdminSession, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = str(payload.get("organization_id") or session.active_organization_id)
        roles = list(payload.get("roles", []))
        store_ids = list(payload.get("store_ids", []))
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_membership (organization_id, admin_user_id, roles, store_ids)
                    VALUES (
                        (SELECT id FROM organization WHERE external_organization_id = %s),
                        %s,
                        %s,
                        ARRAY(
                            SELECT st.id FROM store st
                            JOIN organization org ON org.id = st.organization_id
                            WHERE org.external_organization_id = %s
                              AND st.external_store_id = ANY(%s)
                        )::uuid[]
                    )
                    ON CONFLICT (organization_id, admin_user_id)
                    DO UPDATE SET roles = EXCLUDED.roles, store_ids = EXCLUDED.store_ids, updated_at = now()
                    """,
                    (organization_id, user_id, roles, organization_id, store_ids),
                )
                audit_id = self._audit(cur, session, organization_id, None, "admin.user.roles.update", "admin_user", user_id, payload)
        return {
            "user": {
                "user_id": user_id,
                "email": self.settings.admin_initial_email,
                "display_name": "Customer Admin",
                "roles": roles,
                "organization_ids": [organization_id],
                "store_ids": store_ids,
                "status": "active",
                "last_login_at": None,
            },
            "audit_log_id": audit_id,
        }

    def list_audit_logs(self, session: AdminSession, organization_id: str | None = None) -> dict[str, Any]:
        return {"items": [], "page": _page(0), "page_info": _page_info(0)}

    def _audit(
        self,
        cur: Any,
        session: AdminSession,
        organization_id: str,
        store_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> str:
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        cur.execute(
            """
            INSERT INTO admin_audit_log (
                organization_id, store_id, admin_user_id, action, object_type, object_id, diff_summary
            )
            VALUES (
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
                organization_id,
                organization_id,
                store_id,
                session.user_id,
                action,
                object_type,
                object_id,
                Jsonb({**diff_summary, "audit_log_id": audit_id}),
            ),
        )
        return audit_id

    def _bootstrap_initial_admin(self, cur: Any, organization_id: str) -> None:
        cur.execute(
            """
            INSERT INTO organization (external_organization_id, name, settings)
            VALUES (%s, %s, %s)
            ON CONFLICT (external_organization_id) WHERE external_organization_id IS NOT NULL
            DO UPDATE SET updated_at = now()
            """,
            (organization_id, organization_id, Jsonb({"bootstrap": True})),
        )
        cur.execute(
            """
            INSERT INTO store (organization_id, name, platform, external_store_id)
            VALUES ((SELECT id FROM organization WHERE external_organization_id = %s), 'store-001', 'pdd', 'store-001')
            ON CONFLICT (organization_id, platform, external_store_id)
            DO UPDATE SET updated_at = now()
            """,
            (organization_id,),
        )
        cur.execute(
            """
            INSERT INTO admin_user (organization_id, email, password_hash, display_name, role)
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                %s,
                %s,
                'Customer Admin',
                'owner'
            )
            ON CONFLICT (organization_id, email)
            DO UPDATE SET password_hash = EXCLUDED.password_hash, updated_at = now()
            """,
            (organization_id, self.settings.admin_initial_email, self.settings.admin_initial_password_hash),
        )
        cur.execute(
            """
            INSERT INTO admin_membership (organization_id, admin_user_id, roles, store_ids)
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT admin.id FROM admin_user admin
                  JOIN organization org ON org.id = admin.organization_id
                  WHERE org.external_organization_id = %s AND admin.email = %s),
                ARRAY['owner']::text[],
                ARRAY[(SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.external_store_id = 'store-001')]::uuid[]
            )
            ON CONFLICT (organization_id, admin_user_id)
            DO UPDATE SET roles = EXCLUDED.roles, store_ids = EXCLUDED.store_ids, updated_at = now()
            """,
            (organization_id, organization_id, self.settings.admin_initial_email, organization_id),
        )

    def _auth_response_from_row(self, row: tuple[Any, ...], session: AdminSession) -> dict[str, Any]:
        roles = list(row[6] or ["owner"])
        return {
            "user": {
                "user_id": str(row[0]),
                "email": row[3],
                "display_name": row[5],
                "roles": roles,
                "organization_ids": [str(row[7])],
                "store_ids": [str(row[8])],
                "status": "active",
                "last_login_at": None,
            },
            "organizations": [{"id": str(row[7]), "name": str(row[7]), "status": "active", "metadata": {}}],
            "stores": [{"id": str(row[8]), "organization_id": str(row[7]), "name": str(row[8]), "platform": "pdd", "status": "active", "metadata": {}}],
            "active_organization_id": session.active_organization_id,
            "active_store_id": session.active_store_id,
        }


class InMemorySystemAdminAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.users: dict[str, dict[str, Any]] = {
            "sysadmin-001": {
                "id": "sysadmin-001",
                "email": settings.system_admin_initial_email,
                "name": "System Admin",
                "role": "super_admin",
                "status": "active",
            }
        }
        self.sessions: dict[str, SystemAdminSession] = {
            settings.system_admin_session: SystemAdminSession(
                token=settings.system_admin_session,
                user_id="sysadmin-001",
                email=settings.system_admin_initial_email,
                display_name="System Admin",
                role="super_admin",
                expires_at=_now_dt() + timedelta(days=1),
            )
        }

    def login(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not _password_matches(
            payload.get("email"),
            payload.get("password"),
            self.settings.system_admin_initial_email,
            self.settings.system_admin_initial_password_hash,
        ):
            raise api_error(401, "unauthorized", "invalid system admin credentials")
        token = secrets.token_urlsafe(32)
        self.sessions[token] = SystemAdminSession(
            token=token,
            user_id="sysadmin-001",
            email=self.settings.system_admin_initial_email,
            display_name="System Admin",
            role="super_admin",
            expires_at=_now_dt() + timedelta(hours=8),
        )
        return self.me(self.sessions[token]), token

    def logout(self, token: str) -> None:
        session = self.sessions.get(token)
        if not session or session.revoked_at:
            raise api_error(401, "unauthorized", "missing system admin session")
        session.revoked_at = _now_dt()

    def require_session(self, cookie: str | None, authorization: str | None) -> tuple[Principal, SystemAdminSession]:
        if authorization and authorization.startswith("Bearer "):
            raise api_error(403, "forbidden", "external API token cannot access system admin")
        cookies = _parse_cookie(cookie)
        if "agent_admin_session" in cookies and "agent_system_admin_session" not in cookies:
            raise api_error(403, "forbidden", "customer admin session cannot access system admin")
        token = cookies.get("agent_system_admin_session")
        session = self.sessions.get(token or "")
        if not session or session.revoked_at or session.expires_at <= _now_dt():
            raise api_error(401, "unauthorized", "missing system admin session")
        principal = Principal("system_admin", session.user_id, None, None, session.role)
        return principal, session

    def me(self, session: SystemAdminSession) -> dict[str, Any]:
        return {
            "user": {
                "id": session.user_id,
                "email": session.email,
                "name": session.display_name,
                "role": session.role,
                "status": "active",
            },
            "permissions": ["system:read", "system:write"],
        }


class PostgresSystemAdminAuthService:
    def __init__(self, settings: Settings) -> None:
        import psycopg

        self.settings = settings
        self._connect = psycopg.connect

    def login(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        email = str(payload.get("email", ""))
        password = payload.get("password")
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                self._bootstrap_initial_system_admin(cur)
                cur.execute(
                    """
                    SELECT id, email, password_hash, display_name, role
                    FROM system_admin_user
                    WHERE email = %s AND status = 'active'
                    LIMIT 1
                    """,
                    (email,),
                )
                row = cur.fetchone()
                if not row or not _password_matches(email, password, row[1], row[2]):
                    raise api_error(401, "unauthorized", "invalid system admin credentials")
                token = secrets.token_urlsafe(32)
                cur.execute(
                    """
                    INSERT INTO system_admin_session (
                        system_admin_user_id, session_hash, expires_at
                    )
                    VALUES (%s, %s, now() + interval '8 hours')
                    """,
                    (row[0], _hash_session(token)),
                )
                self._audit(cur, str(row[0]), "auth.login", "system_admin_session", "current", {"reason": "login"})
                session = SystemAdminSession(
                    token=token,
                    user_id=str(row[0]),
                    email=str(row[1]),
                    display_name=str(row[3]),
                    role=str(row[4]),
                    expires_at=_now_dt() + timedelta(hours=8),
                )
                return self.me(session), token

    def logout(self, token: str) -> None:
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE system_admin_session
                    SET revoked_at = now()
                    WHERE session_hash = %s AND revoked_at IS NULL
                    RETURNING system_admin_user_id
                    """,
                    (_hash_session(token),),
                )
                row = cur.fetchone()
                if row:
                    self._audit(cur, str(row[0]), "auth.logout", "system_admin_session", "current", {"reason": "logout"})

    def require_session(self, cookie: str | None, authorization: str | None) -> tuple[Principal, SystemAdminSession]:
        if authorization and authorization.startswith("Bearer "):
            raise api_error(403, "forbidden", "external API token cannot access system admin")
        cookies = _parse_cookie(cookie)
        if "agent_admin_session" in cookies and "agent_system_admin_session" not in cookies:
            raise api_error(403, "forbidden", "customer admin session cannot access system admin")
        token = cookies.get("agent_system_admin_session")
        if not token:
            raise api_error(401, "unauthorized", "missing system admin session")
        with self._connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT admin.id, admin.email, admin.display_name, admin.role
                    FROM system_admin_session session
                    JOIN system_admin_user admin ON admin.id = session.system_admin_user_id
                    WHERE session.session_hash = %s
                      AND session.revoked_at IS NULL
                      AND session.expires_at > now()
                      AND admin.status = 'active'
                    LIMIT 1
                    """,
                    (_hash_session(token),),
                )
                row = cur.fetchone()
                if not row:
                    raise api_error(401, "unauthorized", "missing system admin session")
                session = SystemAdminSession(
                    token=token,
                    user_id=str(row[0]),
                    email=str(row[1]),
                    display_name=str(row[2]),
                    role=str(row[3]),
                    expires_at=_now_dt() + timedelta(hours=1),
                )
                return Principal("system_admin", session.user_id, None, None, session.role), session

    def me(self, session: SystemAdminSession) -> dict[str, Any]:
        return {
            "user": {
                "id": session.user_id,
                "email": session.email,
                "name": session.display_name,
                "role": session.role,
                "status": "active",
            },
            "permissions": ["system:read", "system:write"],
        }

    def _bootstrap_initial_system_admin(self, cur: Any) -> None:
        cur.execute(
            """
            INSERT INTO system_admin_user (email, password_hash, display_name, role)
            VALUES (%s, %s, 'System Admin', 'super_admin')
            ON CONFLICT (email)
            DO UPDATE SET password_hash = EXCLUDED.password_hash, updated_at = now()
            """,
            (self.settings.system_admin_initial_email, self.settings.system_admin_initial_password_hash),
        )

    def _audit(
        self,
        cur: Any,
        user_id: str,
        action: str,
        object_type: str,
        object_id: str,
        diff_summary: dict[str, Any],
    ) -> None:
        cur.execute(
            """
            INSERT INTO system_admin_audit_log (
                system_admin_user_id, action, object_type, object_id, diff_summary
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, action, object_type, object_id, Jsonb(diff_summary)),
        )


def admin_auth_service_for(settings: Settings) -> InMemoryAdminAuthService | PostgresAdminAuthService:
    if settings.database_url and settings.environment.lower() not in {"test"}:
        return PostgresAdminAuthService(settings)
    return InMemoryAdminAuthService(settings)


def system_admin_auth_service_for(settings: Settings) -> InMemorySystemAdminAuthService | PostgresSystemAdminAuthService:
    if settings.database_url and settings.environment.lower() not in {"test"}:
        return PostgresSystemAdminAuthService(settings)
    return InMemorySystemAdminAuthService(settings)


def _password_matches(email: Any, password: Any, expected_email: str, stored_hash: str) -> bool:
    if email != expected_email or not isinstance(password, str):
        return False
    if stored_hash.startswith("plain:"):
        return password == stored_hash.removeprefix("plain:")
    return False


def _parse_cookie(cookie: str | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not cookie:
        return parsed
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _hash_session(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _page(total: int) -> dict[str, int]:
    return {"page": 1, "page_size": 50, "total": total}


def _page_info(total: int) -> dict[str, int]:
    return {"page": 1, "page_size": 50, "total": total}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().replace(microsecond=0).isoformat().replace("+00:00", "Z")
