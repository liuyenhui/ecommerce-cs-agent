from __future__ import annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from fastapi import HTTPException

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.admin_auth import (
    AdminSession,
    PostgresAdminAuthService,
    PostgresSystemAdminAuthService,
    SystemAdminSession,
    _password_matches,
    admin_auth_service_for,
    system_admin_auth_service_for,
)
from ecommerce_cs_agent.services.system_admin import InMemorySystemAdminRepository, PostgresSystemAdminRepository, _audit_from_row


def test_admin_auth_service_uses_postgres_when_database_url_is_configured() -> None:
    settings = Settings(database_url="postgresql://example", environment="production")

    service = admin_auth_service_for(settings)

    assert isinstance(service, PostgresAdminAuthService)


def test_system_admin_auth_service_uses_postgres_when_database_url_is_configured() -> None:
    settings = Settings(database_url="postgresql://example", environment="production")

    service = system_admin_auth_service_for(settings)

    assert isinstance(service, PostgresSystemAdminAuthService)


def test_admin_auth_password_matches_bcrypt_hashes() -> None:
    bcrypt_hash = "$2b$12$L6BD2bTFvmSDL.o8ItsGrOAyTY5SCUOpHFvqMKr/pOBDa3cGWPvNG"

    assert _password_matches("admin@example.test", "password", "admin@example.test", bcrypt_hash)
    assert not _password_matches("admin@example.test", "wrong", "admin@example.test", bcrypt_hash)
    assert not _password_matches("other@example.test", "password", "admin@example.test", bcrypt_hash)


def test_postgres_launch_login_commits_bootstrap_before_loading_session_context() -> None:
    source = inspect.getsource(PostgresAdminAuthService.login_launch)

    assert "conn.commit()" in source
    assert source.index("conn.commit()") < source.index("return self.me(session), token")


def test_postgres_admin_auth_login_bootstraps_user_and_persists_hashed_session() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "admin-uuid",
                "org-uuid",
                "store-uuid",
                "admin@example.test",
                "plain:admin-password",
                "Customer Admin",
                ["owner"],
                "org-001",
                "store-001",
            )
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, token = service.login({"email": "admin@example.test", "password": "admin-password"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response["user"]["user_id"] == "admin-uuid"
    assert token
    assert token != settings.admin_session
    assert "INSERT INTO organization" in executed_sql
    assert "INSERT INTO admin_user" in executed_sql
    assert "INSERT INTO admin_membership" in executed_sql
    assert "INSERT INTO admin_session" in executed_sql
    session_insert = [item for item in connection.executed if "INSERT INTO admin_session" in item[0]][0]
    assert token not in str(session_insert[1])


def test_postgres_admin_auth_login_returns_store_display_name() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "admin-uuid",
                "org-uuid",
                "store-uuid",
                "admin@example.test",
                "plain:admin-password",
                "Customer Admin",
                ["owner"],
                None,
                "org-001",
                "972824439",
                "宠萌洗护用品店",
            )
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, _token = service.login({"email": "admin@example.test", "password": "admin-password"})

    assert response["stores"][0]["id"] == "972824439"
    assert response["stores"][0]["name"] == "宠萌洗护用品店"


def test_postgres_admin_auth_login_does_not_filter_by_request_organization_id() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "admin-uuid",
                "org-uuid",
                "store-uuid",
                "admin@example.test",
                "plain:admin-password",
                "Customer Admin",
                ["owner"],
                "org-001",
                "store-001",
            )
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, _token = service.login(
        {"email": "admin@example.test", "password": "admin-password", "organization_id": "org-other"}
    )

    login_select = [sql for sql, _params in connection.executed if "SELECT admin.id, org.id, st.id" in sql][0]
    executed_params = " ".join(str(params) for _sql, params in connection.executed)
    assert response["active_organization_id"] == "org-001"
    assert "org.external_organization_id = %s" not in login_select
    assert "org-other" not in executed_params


def test_postgres_admin_auth_require_session_queries_hashed_active_session() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "admin-uuid",
                "org-uuid",
                "store-uuid",
                "admin@example.test",
                "Customer Admin",
                ["owner"],
                "org-001",
                "store-001",
            )
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection

    principal, session = service.require_session("agent_admin_session=session-token", None)

    assert principal.user_id == "admin-uuid"
    assert session.active_organization_id == "org-001"
    assert "FROM admin_session" in connection.executed[0][0]
    assert "session-token" not in str(connection.executed[0][1])


def test_postgres_admin_auth_store_invitation_roles_write_to_db_and_audit() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection()
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    settings_response = service.update_store_settings(
        session,
        "store-001",
        {"organization_id": "org-001", "settings": {"assist_enabled": True}, "reason": "enable"},
    )
    invitation = service.create_invitation(
        session,
        {
            "organization_id": "org-001",
            "email": "invitee@example.test",
            "roles": ["store_operator"],
            "store_ids": ["store-001"],
            "reason": "invite",
            "idempotency_key": "invite-001",
        },
    )
    role_update = service.update_roles(
        session,
        "admin-uuid",
        {"organization_id": "org-001", "roles": ["owner"], "store_ids": ["store-001"], "reason": "owner"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert settings_response["settings"]["assist_enabled"] is True
    assert invitation["status"] == "pending"
    assert role_update["user"]["user_id"] == "admin-uuid"
    assert "UPDATE store" in executed_sql
    assert "INSERT INTO admin_invitation" in executed_sql
    assert "INSERT INTO admin_membership" in executed_sql
    assert executed_sql.count("INSERT INTO admin_audit_log") >= 3


def test_postgres_admin_auth_me_reads_organizations_stores_and_users_from_db() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            [("org-001", "Acme", "active", {"tier": "dev"})],
            (1,),
            [("store-001", "org-001", "PDD Store", "pdd", "active", {"assist_enabled": True})],
            (1,),
            [("admin-uuid", "admin@example.test", "Customer Admin", "active", ["owner"], "org-001", ["store-001"])],
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    me = service.me(session)

    assert me["user"]["email"] == "admin@example.test"
    assert me["organizations"][0]["name"] == "Acme"
    assert me["stores"][0]["metadata"]["assist_enabled"] is True
    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "FROM admin_membership membership" in executed_sql
    assert "JOIN store st ON st.organization_id = org.id" in executed_sql
    assert "JOIN admin_membership membership ON membership.admin_user_id = admin.id" in executed_sql


def test_postgres_admin_auth_list_audit_logs_reads_db_and_enforces_org_access() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "audit-001",
                    "org-001",
                    "store-001",
                    "admin-uuid",
                    "store.settings.update",
                    "store",
                    "store-001",
                    {"reason": "test"},
                    False,
                    "2026-06-18T00:00:00Z",
                )
            ],
        ]
    )
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    logs = service.list_audit_logs(session, "org-001")

    assert logs["items"][0]["id"] == "audit-001"
    assert logs["items"][0]["actor_id"] == "admin-uuid"
    assert "FROM admin_audit_log audit" in connection.executed[1][0]


def test_postgres_admin_auth_rejects_cross_org_db_list_access() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(fetch_rows=[None])
    service = PostgresAdminAuthService(settings)
    service._connect = lambda _url: connection
    session = AdminSession(
        token="session-token",
        user_id="admin-uuid",
        active_organization_id="org-001",
        active_store_id="store-001",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    with pytest.raises(HTTPException) as exc:
        service.list_stores(session, "org-other")

    assert exc.value.status_code == 403


def test_postgres_system_admin_auth_login_persists_hashed_session_and_audit() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "sysadmin-uuid",
                "system-admin@example.test",
                "plain:system-admin-password",
                "System Admin",
                "super_admin",
            )
        ]
    )
    service = PostgresSystemAdminAuthService(settings)
    service._connect = lambda _url: connection

    response, token = service.login(
        {"email": "system-admin@example.test", "password": "system-admin-password"}
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response["user"]["id"] == "sysadmin-uuid"
    assert token
    assert token != settings.system_admin_session
    assert "INSERT INTO system_admin_user" in executed_sql
    assert "INSERT INTO system_admin_session" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql
    session_insert = [item for item in connection.executed if "INSERT INTO system_admin_session" in item[0]][0]
    assert token not in str(session_insert[1])


def test_postgres_system_admin_auth_require_session_queries_hashed_active_session() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(
        fetch_rows=[
            (
                "sysadmin-uuid",
                "system-admin@example.test",
                "System Admin",
                "super_admin",
            )
        ]
    )
    service = PostgresSystemAdminAuthService(settings)
    service._connect = lambda _url: connection

    principal, session = service.require_session("agent_system_admin_session=session-token", None)

    assert principal.kind == "system_admin"
    assert principal.user_id == "sysadmin-uuid"
    assert principal.role == "super_admin"
    assert session.email == "system-admin@example.test"
    assert "FROM system_admin_session" in connection.executed[0][0]
    assert "session-token" not in str(connection.executed[0][1])


def test_postgres_system_admin_auth_logout_revokes_session_and_writes_audit() -> None:
    settings = Settings(database_url="postgresql://example")
    connection = _FakeConnection(fetch_rows=[("sysadmin-uuid",)])
    service = PostgresSystemAdminAuthService(settings)
    service._connect = lambda _url: connection

    service.logout("session-token")

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "UPDATE system_admin_session" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql
    assert "session-token" not in str(connection.executed[0][1])


def test_postgres_system_admin_repository_lists_and_creates_org_store_with_audit() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [("org-001", "Acme", "active", {"contact": {"email": "ops@example.test"}}, "2026-06-18T00:00:00Z")],
            ("org-new", "New Tenant", "active", {"contact": {}, "external_ref": "org-new"}, "2026-06-18T00:00:01Z"),
            ("org-new-uuid",),
            ("org-new", "store-new", "New Store", "pdd", "active", {"reason": "onboard"}, "2026-06-18T00:00:02Z", False),
            (1,),
            [("org-new", "store-new", "New Store", "pdd", "active", {"reason": "onboard"}, "2026-06-18T00:00:02Z", False)],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    session = _system_session()

    orgs = repository.list_organizations(session, {"status": "active"})
    created_org = repository.create_organization(
        session,
        {"name": "New Tenant", "status": "active", "external_ref": "org-new", "reason": "onboard"},
    )
    created_store = repository.create_store(
        session,
        {
            "organization_id": "org-new",
            "name": "New Store",
            "platform": "pdd",
            "external_store_id": "store-new",
            "status": "active",
            "reason": "onboard",
        },
    )
    stores = repository.list_stores(session, {"organization_id": "org-new"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert orgs["items"][0]["id"] == "org-001"
    assert created_org["organization"]["id"] == "org-new"
    assert created_store["store"]["id"] == "store-new"
    assert stores["items"][0]["organization_id"] == "org-new"
    assert "FROM organization" in executed_sql
    assert "INSERT INTO organization" in executed_sql
    assert "INSERT INTO store" in executed_sql
    assert executed_sql.count("INSERT INTO system_admin_audit_log") >= 4


def test_postgres_system_admin_repository_creates_user_with_audit() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (
                "sysadmin-new",
                "new-system-admin@example.test",
                "New System Admin",
                "technical_support",
                "active",
                "2026-06-18T00:00:00Z",
            )
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    response = repository.create_user(
        _system_session(),
        {
            "email": "new-system-admin@example.test",
            "display_name": "New System Admin",
            "roles": ["technical_support"],
            "reason": "support coverage",
        },
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert response["user"]["system_user_id"] == "sysadmin-new"
    assert response["user"]["roles"] == ["technical_support"]
    assert response["audit_log_id"]
    assert "INSERT INTO system_admin_user" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_system_admin_repository_rejects_user_creation_for_release_admin() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")

    with pytest.raises(HTTPException) as exc:
        repository.create_user(
            _system_session(role="release_admin"),
            {
                "email": "new-system-admin@example.test",
                "display_name": "New System Admin",
                "roles": ["technical_support"],
                "reason": "support coverage",
            },
        )

    assert exc.value.status_code == 403


def test_postgres_system_admin_repository_replays_create_organization_idempotently() -> None:
    organization_row = (
        "org-idem",
        "Idem Tenant",
        "active",
        {"contact": {}, "external_ref": "org-idem"},
        "2026-06-18T00:00:00Z",
    )
    connection = _FakeConnection(fetch_rows=[None, organization_row, ("audit-001", "org-idem"), organization_row])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    payload = {
        "name": "Idem Tenant",
        "status": "active",
        "external_ref": "org-idem",
        "reason": "onboard",
        "idempotency_key": "org-idem-key",
    }

    first = repository.create_organization(_system_session(), payload)
    second = repository.create_organization(_system_session(), payload)

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert first["organization"]["organization_id"] == "org-idem"
    assert second["organization"]["organization_id"] == "org-idem"
    assert second["audit_log_id"] == "audit-001"
    assert executed_sql.count("INSERT INTO organization") == 1


def test_postgres_system_admin_repository_lists_tasks_and_retries_failed_task() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "task-001",
                    "embedding",
                    "failed",
                    True,
                    "org-001",
                    "store-001",
                    "asset-001",
                    None,
                    "provider timeout",
                    0,
                    None,
                    "2026-06-18T00:00:00Z",
                )
            ],
            None,
            ("failed", True, "org-001", "store-001"),
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    session = _system_session()

    tasks = repository.list_tasks(session, {"organization_id": "org-001", "status": "failed"})
    retry = repository.retry_task(
        session,
        "task-001",
        {"idempotency_key": "retry-001", "reason": "manual retry"},
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert tasks["items"][0]["task_id"] == "task-001"
    assert tasks["items"][0]["retryable"] is True
    assert tasks["items"][0]["error_summary"] == "provider timeout"
    assert retry["task_id"] == "task-001"
    assert retry["status"] == "queued"
    assert retry["audit_log_id"]
    assert "FROM background_task task" in executed_sql
    assert "pg_advisory_xact_lock" in executed_sql
    assert "FOR UPDATE" in executed_sql
    assert "UPDATE background_task" in executed_sql
    assert "retryable = false" in executed_sql
    update_sql = next(sql for sql, _params in connection.executed if "UPDATE background_task" in sql)
    assert "idempotency_key = %s" not in update_sql
    assert "retry-001" in str(connection.executed)


def test_postgres_system_admin_repository_replays_task_retry_idempotently() -> None:
    connection = _FakeConnection(fetch_rows=[None, ("failed", True, "org-001", "store-001"), ("audit-001", "task-001", "sysadmin-uuid")])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection
    payload = {"idempotency_key": "retry-001", "reason": "manual retry"}

    first = repository.retry_task(_system_session(), "task-001", payload)
    second = repository.retry_task(_system_session(), "task-001", payload)

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert first["status"] == "queued"
    assert second == {"task_id": "task-001", "status": "queued", "audit_log_id": "audit-001"}
    assert executed_sql.count("UPDATE background_task") == 1


def test_postgres_task_retry_replays_same_key_after_controlled_lock_interleaving() -> None:
    connection = _FakeConnection(fetch_rows=[
        None,
        ("queued", True, "org-001", "store-001"),
        ("audit-001", "task-001", "sysadmin-uuid"),
    ])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    replay = repository.retry_task(
        _system_session(),
        "task-001",
        {"idempotency_key": "retry-race", "reason": "concurrent retry"},
    )

    assert replay == {"task_id": "task-001", "status": "queued", "audit_log_id": "audit-001"}
    assert "UPDATE background_task" not in "\n".join(sql for sql, _params in connection.executed)


def test_postgres_task_retry_same_key_is_concurrently_replayed_once() -> None:
    class SharedState:
        def __init__(self) -> None:
            self.initial_reads = threading.Barrier(2)
            self.idempotency_lock = threading.Lock()
            self.task_lock = threading.Lock()
            self.status = "failed"
            self.audit: tuple[str, str, str] | None = None
            self.update_count = 0

    state = SharedState()

    class Connection:
        def __init__(self) -> None:
            self.owns_task_lock = False
            self.owns_idempotency_lock = False

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            if self.owns_task_lock:
                self.task_lock_release()
            if self.owns_idempotency_lock:
                self.owns_idempotency_lock = False
                state.idempotency_lock.release()

        def task_lock_release(self) -> None:
            self.owns_task_lock = False
            state.task_lock.release()

        def cursor(self):
            return Cursor(self)

    class Cursor:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection
            self.last_query = ""

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            if "pg_advisory_xact_lock" in sql:
                state.idempotency_lock.acquire()
                self.connection.owns_idempotency_lock = True
                self.last_query = "advisory"
            elif "FROM system_admin_audit_log" in sql:
                self.last_query = "idempotency"
            elif "FOR UPDATE OF task" in sql:
                state.task_lock.acquire()
                self.connection.owns_task_lock = True
                self.last_query = "task"
            elif "UPDATE background_task" in sql:
                state.status = "queued"
                state.update_count += 1
                self.last_query = "update"
            elif "INSERT INTO system_admin_audit_log" in sql:
                state.audit = (str(params[0]), str(params[7]), str(params[1]))
                self.last_query = "audit"

        def fetchone(self):
            if self.last_query == "idempotency":
                if state.audit is not None:
                    return state.audit
                if not self.connection.owns_idempotency_lock:
                    state.initial_reads.wait(timeout=3)
                return None
            if self.last_query == "task":
                return (state.status, True, "org-001", "store-001")
            return None

    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: Connection()
    payload = {"idempotency_key": "retry-concurrent", "reason": "concurrent retry"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(repository.retry_task, _system_session(), "task-001", payload) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]

    assert results[0] == results[1]
    assert results[0]["status"] == "queued"
    assert state.update_count == 1


@pytest.mark.parametrize(
    "replay_row",
    [
        ("audit-other-task", "task-other", "sysadmin-uuid"),
        ("audit-other-actor", "task-001", "other-sysadmin"),
    ],
)
def test_postgres_task_retry_rejects_cross_task_or_cross_actor_key_replay(replay_row: tuple[str, str, str]) -> None:
    connection = _FakeConnection(fetch_rows=[replay_row])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc_info:
        repository.retry_task(
            _system_session(),
            "task-001",
            {"idempotency_key": "retry-shared", "reason": "manual retry"},
        )

    assert exc_info.value.status_code == 409
    assert "UPDATE background_task" not in "\n".join(sql for sql, _params in connection.executed)


def test_postgres_task_retry_with_different_key_conflicts_after_another_retry_wins_lock() -> None:
    connection = _FakeConnection(fetch_rows=[None, ("queued", True, "org-001", "store-001"), None])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc_info:
        repository.retry_task(
            _system_session(),
            "task-001",
            {"idempotency_key": "retry-different", "reason": "concurrent retry"},
        )

    assert exc_info.value.status_code == 409
    assert "UPDATE background_task" not in "\n".join(sql for sql, _params in connection.executed)


def test_postgres_system_admin_repository_readiness_reads_db_and_returns_all_checks() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [("org-001", "store-001", True, False, True, True)],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    readiness = repository.store_readiness(_system_session(), {"organization_id": "org-001"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    item = readiness["items"][0]
    assert item["organization_id"] == "org-001"
    assert item["store_id"] == "store-001"
    assert item["status"] == "warning"
    assert {check["code"] for check in item["checks"]} == {
        "product_content",
        "price_snapshot",
        "knowledge_review",
        "api_integration",
    }
    assert len(item["checks"]) == 4
    assert "FROM store st" in executed_sql
    assert "platform_account" in executed_sql
    assert "external_api_token" in executed_sql
    assert "knowledge.store_id::text = st.id::text" in executed_sql


def test_in_memory_readiness_filters_before_global_total_and_pagination() -> None:
    repository = InMemorySystemAdminRepository()
    repository.stores = {
        "ready-first": {"id": "ready-first", "organization_id": "org-001", "status": "active"},
        **{
            f"blocked-{index}": {"id": f"blocked-{index}", "organization_id": "org-001", "status": "active"}
            for index in range(1, 7)
        },
    }
    repository.product_store_ids = {"ready-first"}
    repository.price_snapshot_store_ids = {"ready-first"}
    repository.approved_knowledge_store_ids = {"ready-first"}
    repository.active_integration_store_ids = {"ready-first"}

    response = repository.store_readiness(
        _system_session(),
        {"status": "blocked", "page": "1", "page_size": "5"},
    )

    assert response["page_info"] == {"page": 1, "page_size": 5, "total": 6}
    assert len(response["items"]) == 5
    assert {item["status"] for item in response["items"]} == {"blocked"}
    assert "ready-first" not in {item["store_id"] for item in response["items"]}


def test_postgres_readiness_applies_status_to_count_and_items_before_pagination() -> None:
    rows = [("org-001", f"blocked-{index}", False, False, False, False) for index in range(1, 6)]
    connection = _FakeConnection(fetch_rows=[(6,), rows])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    response = repository.store_readiness(
        _system_session(),
        {"status": "blocked", "page": "1", "page_size": "5"},
    )

    select_queries = [(sql, params) for sql, params in connection.executed if "WITH readiness_inputs AS" in sql]
    assert response["page_info"] == {"page": 1, "page_size": 5, "total": 6}
    assert len(response["items"]) == 5
    assert len(select_queries) == 2
    for sql, params in select_queries:
        assert "readiness_status = %s" in sql
        assert params[:6] == (None, None, None, None, "blocked", "blocked")
    assert select_queries[1][1][-2:] == (5, 0)


def test_postgres_system_admin_repository_lists_message_traces_with_audit() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "decision-001",
                    "org-001",
                    "store-001",
                    "req-001",
                    "msg-001",
                    "candidate",
                    "low",
                    "completed",
                    "2026-06-18T00:00:00Z",
                )
            ],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    filters = {
        "organization_id": "org-001",
        "store_id": "store-001",
        "external_message_id": "msg-001",
        "trace_id": "trace-001",
        "created_at_from": "2026-06-18T00:00:00Z",
        "created_at_to": "2026-06-19T00:00:00Z",
    }
    traces = repository.list_message_traces(_system_session(role="technical_support"), filters)

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert traces["items"][0]["decision_id"] == "decision-001"
    assert traces["items"][0]["request_id"] == "req-001"
    assert traces["items"][0]["external_message_id"] == "msg-001"
    assert traces["items"][0]["action"] == "candidate"
    assert traces["items"][0]["sensitive_access"] is False
    assert traces["page_info"]["total"] == 1
    assert "FROM decision_record decision" in executed_sql
    assert "LEFT JOIN message msg" in executed_sql
    assert "decision_trace_step step" in executed_sql
    assert "st.id::text = decision.store_id::text" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql
    assert "trace-001" in str(connection.executed)
    assert "2026-06-18T00:00:00Z" in str(connection.executed)


def test_postgres_system_admin_repository_restricts_message_trace_access() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")

    with pytest.raises(HTTPException) as forbidden:
        repository.list_message_traces(_system_session(role="release_admin"), {"organization_id": "org-001"})
    with pytest.raises(HTTPException) as unscoped:
        repository.list_message_traces(_system_session(role="technical_support"), {})

    assert forbidden.value.status_code == 403
    assert forbidden.value.detail["error"]["code"] == "forbidden"
    assert unscoped.value.status_code == 422
    assert unscoped.value.detail["error"]["code"] == "tenant_scope_required"


def test_postgres_system_admin_repository_gets_message_trace_detail_with_audit() -> None:
    state_payload = {
        "request": {
            "request_id": "req-001",
            "platform": "pdd",
            "store_id": "forged-store",
            "conversation": {"external_conversation_id": "forged-conv"},
            "message": {"external_message_id": "forged-msg", "content": "什么时候发货？"},
        },
        "response": {
            "decision_id": "decision-001",
            "action": "handoff",
            "confidence": 0.11,
            "risk_level": "high",
            "trace": {"graph_version": "reply-decision-graph-v1", "steps": [{"name": "normalize", "status": "completed"}]},
        },
        "feedback": [],
    }
    connection = _FakeConnection(
        fetch_rows=[
            (
                "decision-001",
                "org-001",
                "store-001",
                "req-001",
                "msg-001",
                "pdd",
                "conv-001",
                "candidate",
                0.82,
                "low",
                state_payload,
                "2026-06-18T00:00:00Z",
            ),
            [
                (
                    "trace-step-001",
                    "normalize",
                    1,
                    "completed",
                    {"step_id": "trace-001", "inputs_ref": ["message:msg-001"], "outputs_ref": ["normalized"], "error": None},
                    "2026-06-18T00:00:00Z",
                )
            ],
            [
                (
                    "ctx-001",
                    "price",
                    "api",
                    {"context_request_id": "ctx-001", "price": "99.00"},
                    "2026-06-18T00:00:00Z",
                )
            ],
            [
                (
                    "action-001",
                    "refund_check",
                    "requested",
                    {"action_id": "action-001"},
                    "succeeded",
                    {"result": "ok"},
                    "2026-06-18T00:00:00Z",
                )
            ],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    detail = repository.get_message_trace(_system_session(role="technical_support"), "decision-001", {})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert detail is not None
    assert detail["trace"]["decision_id"] == "decision-001"
    assert detail["trace"]["external_message_id"] == "msg-001"
    assert detail["trace"]["store_id"] == "store-001"
    assert detail["trace"]["conversation_id"] == "conv-001"
    assert detail["trace"]["action"] == "candidate"
    assert detail["trace"]["confidence"] == 0.82
    assert detail["trace"]["risk_level"] == "low"
    assert detail["trace"]["trace"]["steps"][0]["step_id"] == "trace-001"
    assert detail["trace"]["sections"]["retrieval"]["context_snapshots"][0]["context_snapshot_id"] == "ctx-001"
    assert detail["trace"]["sections"]["persistence"]["action_requests"][0]["action_id"] == "action-001"
    assert "payload" not in detail["trace"]["sections"]["retrieval"]["context_snapshots"][0]
    assert "request_payload" not in detail["trace"]["sections"]["persistence"]["action_requests"][0]
    assert "result_payload" not in detail["trace"]["sections"]["persistence"]["action_requests"][0]
    assert detail["trace"]["trace"]["graph_version"] == "reply-decision-graph-v1"
    assert detail["audit_log_id"]
    assert "FROM decision_record decision" in executed_sql
    assert "decision_graph_checkpoint checkpoint" in executed_sql
    assert "FROM decision_trace_step step" in executed_sql
    assert "FROM context_snapshot snapshot" in executed_sql
    assert "FROM action_request action" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_postgres_system_admin_repository_includes_nested_payloads_only_with_raw_permission() -> None:
    state_payload = {
        "request": {
            "request_id": "req-raw",
            "platform": "pdd",
            "store_id": "store-001",
            "conversation": {"external_conversation_id": "conv-raw"},
            "message": {"external_message_id": "msg-raw"},
        },
        "response": {
            "decision_id": "decision-raw",
            "action": "action_request",
            "confidence": 0.7,
            "risk_level": "medium",
            "trace": {"graph_version": "reply-decision-graph-v1", "steps": []},
        },
        "feedback": [],
    }
    connection = _FakeConnection(
        fetch_rows=[
            (
                "decision-raw",
                "org-001",
                "store-001",
                "req-raw",
                "msg-raw",
                "pdd",
                "conv-raw",
                "action_request",
                0.7,
                "medium",
                state_payload,
                "2026-06-18T00:00:00Z",
            ),
            [],
            [("ctx-raw", "order", "api", {"buyer_phone": "redacted"}, "2026-06-18T00:00:00Z")],
            [("action-raw", "refund_check", "requested", {"buyer_phone": "redacted"}, "failed", {"error": "timeout"}, "2026-06-18T00:00:00Z")],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    detail = repository.get_message_trace(
        _system_session(role="super_admin"),
        "decision-raw",
        {"include_raw_payload": "true", "reason": "support debug"},
    )

    assert detail is not None
    context = detail["trace"]["sections"]["retrieval"]["context_snapshots"][0]
    action = detail["trace"]["sections"]["persistence"]["action_requests"][0]
    assert context["payload"] == {"buyer_phone": "redacted"}
    assert action["request_payload"] == {"buyer_phone": "redacted"}
    assert action["result_payload"] == {"error": "timeout"}
    assert detail["raw_payload"]["request_id"] == "req-raw"


def test_postgres_system_admin_repository_requires_raw_payload_capability() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")
    connection = _FakeConnection()
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        repository.get_message_trace(
            _system_session(role="technical_support"),
            "decision-001",
            {"include_raw_payload": "true", "reason": "support debug"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "raw_payload_access_denied"


def test_postgres_system_admin_repository_falls_back_to_legacy_app_decision_state_detail() -> None:
    state_payload = {
        "request": {
            "request_id": "req-legacy",
            "platform": "pdd",
            "organization_id": "org-001",
            "store_id": "store-001",
            "conversation": {"external_conversation_id": "conv-legacy"},
            "message": {"external_message_id": "msg-legacy"},
        },
        "response": {
            "decision_id": "decision-legacy",
            "action": "candidate",
            "confidence": 0.71,
            "risk_level": "low",
            "trace": {"graph_version": "reply-decision-graph-v1", "steps": []},
        },
        "feedback": [],
    }
    connection = _FakeConnection(
        fetch_rows=[
            None,
            (
                "decision-legacy",
                "org-001",
                "store-001",
                "req-legacy",
                "msg-legacy",
                "pdd",
                "conv-legacy",
                "candidate",
                0.71,
                "low",
                state_payload,
                "2026-06-18T00:00:00Z",
            ),
            [],
            [],
            [],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    detail = repository.get_message_trace(_system_session(role="technical_support"), "decision-legacy", {})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert detail is not None
    assert detail["trace"]["decision_id"] == "decision-legacy"
    assert detail["trace"]["external_message_id"] == "msg-legacy"
    assert "FROM app_decision_state legacy" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_postgres_system_admin_repository_requires_reason_for_raw_message_trace_payload() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")
    connection = _FakeConnection()
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        repository.get_message_trace(_system_session(role="technical_support"), "decision-001", {"include_raw_payload": "true"})

    assert exc.value.status_code == 422
    assert exc.value.detail["error"]["code"] == "audit_reason_required"
    assert "INSERT INTO system_admin_audit_log" in "\n".join(sql for sql, _params in connection.executed)


def test_postgres_system_admin_repository_denies_raw_message_trace_payload_by_role_with_audit() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")
    connection = _FakeConnection()
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        repository.get_message_trace(
            _system_session(role="platform_operator"),
            "decision-001",
            {"include_raw_payload": "true", "reason": "debug"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "raw_payload_access_denied"
    assert "INSERT INTO system_admin_audit_log" in "\n".join(sql for sql, _params in connection.executed)


def test_postgres_system_admin_repository_denies_raw_message_trace_list_by_role_with_audit() -> None:
    repository = PostgresSystemAdminRepository("postgresql://example")
    connection = _FakeConnection()
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        repository.list_message_traces(
            _system_session(role="platform_operator"),
            {"organization_id": "org-001", "include_raw_payload": "true", "reason": "debug"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "raw_payload_access_denied"
    audit_payload = connection.executed[0][1][8].obj
    assert audit_payload["sensitive_access"] is True
    assert audit_payload["reason"] == "debug"


def test_in_memory_system_admin_repository_denies_raw_message_trace_list_by_role_with_audit() -> None:
    repository = InMemorySystemAdminRepository()

    with pytest.raises(HTTPException) as exc:
        repository.list_message_traces(
            _system_session(role="technical_support"),
            {"organization_id": "org-001", "include_raw_payload": "true", "reason": "debug"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"]["code"] == "raw_payload_access_denied"
    assert repository.audit_logs[0]["action"] == "system_admin.message_trace.raw_payload_denied"
    assert repository.audit_logs[0]["sensitive_access"] is True


def test_postgres_system_admin_repository_system_health_reads_db_and_writes_audit() -> None:
    connection = _FakeConnection(fetch_rows=[(True, True, 1, 0)])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    health = repository.system_health(_system_session())

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert health["status"] == "degraded"
    assert all("checked_at" in dependency for dependency in health["dependencies"])
    assert all("message" in dependency for dependency in health["dependencies"])
    assert all("detail" not in dependency for dependency in health["dependencies"])
    assert {dependency["name"] for dependency in health["dependencies"]} >= {
        "api",
        "postgresql",
        "pgvector",
        "queue",
    }
    assert "FROM pg_extension" in executed_sql
    assert "FROM background_task" in executed_sql
    assert "INSERT INTO system_admin_audit_log" in executed_sql


def test_postgres_system_admin_repository_marks_raw_list_audit_sensitive() -> None:
    connection = _FakeConnection(fetch_rows=[(0,), []])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    repository.list_message_traces(
        _system_session(role="super_admin"),
        {"organization_id": "org-001", "include_raw_payload": "true", "reason": "raw list debug"},
    )

    audit_payload = connection.executed[0][1][8].obj
    assert audit_payload["sensitive_access"] is True
    assert audit_payload["reason"] == "raw list debug"


def test_postgres_system_admin_repository_filters_audit_logs_by_sensitive_access() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "audit-raw",
                    "sysadmin-uuid",
                    "org-001",
                    "store-001",
                    "system_admin.message_trace.get",
                    "decision_record",
                    "decision-001",
                    {"reason": "debug", "sensitive_access": True},
                    "2026-06-18T00:00:00Z",
                )
            ],
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    logs = repository.list_audit_logs(_system_session(), {"sensitive_access": "true"})

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert logs["items"][0]["sensitive_access"] is True
    assert "COALESCE((audit.diff_summary->>'sensitive_access')::boolean, false) = %s" in executed_sql


def test_system_admin_audit_sensitive_access_is_derived_from_diff_summary() -> None:
    log = _audit_from_row(
        (
            "audit-raw",
            "sysadmin-uuid",
            "org-001",
            "store-001",
            "system_admin.message_trace.raw_payload_denied",
            "decision_record",
            "decision-001",
            {"reason": "debug", "sensitive_access": True},
            "2026-06-18T00:00:00Z",
        )
    )

    assert log["sensitive_access"] is True


def test_postgres_system_admin_repository_rejects_non_failed_task_retry_with_409() -> None:
    connection = _FakeConnection(fetch_rows=[None, ("succeeded", True, "org-001", "store-001")])
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    with pytest.raises(HTTPException) as exc:
        repository.retry_task(
            _system_session(),
            "task-001",
            {"idempotency_key": "retry-001", "reason": "manual retry"},
        )

    assert exc.value.status_code == 409


def test_postgres_system_admin_repository_lists_system_audit_logs() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            (1,),
            [
                (
                    "audit-001",
                    "sysadmin-uuid",
                    "org-001",
                    "store-001",
                    "system_admin.task.retry",
                    "background_task",
                    "task-001",
                    {"reason": "manual retry"},
                    "2026-06-18T00:00:00Z",
                )
            ]
        ]
    )
    repository = PostgresSystemAdminRepository("postgresql://example")
    repository._connect = lambda _url: connection

    logs = repository.list_audit_logs(_system_session(), {"organization_id": "org-001"})

    assert logs["items"][0]["audit_log_id"] == "audit-001"
    assert logs["items"][0]["actor_system_user_id"] == "sysadmin-uuid"
    assert "FROM system_admin_audit_log audit" in connection.executed[1][0]


def _system_session(role: str = "super_admin") -> Any:
    return SystemAdminSession(
        token="session-token",
        user_id="sysadmin-uuid",
        email="system-admin@example.test",
        display_name="System Admin",
        role=role,
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


class _FakeConnection:
    def __init__(self, fetch_rows: list[Any] | None = None) -> None:
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
            item = self.connection.fetch_rows.pop(0)
            if isinstance(item, list):
                return item[0] if item else None
            return item
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        if self.connection.fetch_rows:
            item = self.connection.fetch_rows.pop(0)
            if isinstance(item, list):
                return item
            return [item]
        return []
