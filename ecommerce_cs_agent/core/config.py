from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    service_name: str = "ecommerce-cs-agent-api"
    environment: str = "development"
    graph_version: str = "reply-decision-graph-v1"
    model_version: str = "reply-generator-v1"
    agent_api_token: str = "test-agent-token"
    admin_session: str = "test-admin-session"
    system_admin_session: str = "test-system-session"
    admin_initial_email: str = "admin@example.test"
    admin_initial_password_hash: str = "plain:admin-password"
    system_admin_initial_email: str = "system-admin@example.test"
    system_admin_initial_password_hash: str = "plain:system-admin-password"
    database_url: str | None = None
    object_storage_backend: str = "reference"
    object_storage_root: str = ".object-storage"


def load_settings() -> Settings:
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development"))
    production = environment.lower() in {"production", "prod"}
    required_groups = [
        ("AGENT_API_TOKEN",),
        ("ADMIN_SESSION_SECRET", "SESSION_SECRET"),
        ("SYSTEM_ADMIN_SESSION_SECRET", "JWT_SECRET"),
        ("ADMIN_INITIAL_EMAIL",),
        ("ADMIN_INITIAL_PASSWORD_HASH",),
        ("SYSTEM_ADMIN_INITIAL_EMAIL", "ADMIN_INITIAL_EMAIL"),
        ("SYSTEM_ADMIN_INITIAL_PASSWORD_HASH", "ADMIN_INITIAL_PASSWORD_HASH"),
        ("DATABASE_URL",),
    ]
    if production:
        missing = _missing_required_groups(required_groups)
        if missing:
            raise RuntimeError(f"Missing required production settings: {', '.join(missing)}")

    return Settings(
        service_name=os.environ.get("SERVICE_NAME", "ecommerce-cs-agent-api"),
        environment=environment,
        graph_version=os.environ.get("GRAPH_VERSION", "reply-decision-graph-v1"),
        model_version=os.environ.get("MODEL_VERSION", "reply-generator-v1"),
        agent_api_token=os.environ.get("AGENT_API_TOKEN", "test-agent-token"),
        admin_session=_env_first("ADMIN_SESSION_SECRET", "SESSION_SECRET", default="test-admin-session"),
        system_admin_session=_env_first("SYSTEM_ADMIN_SESSION_SECRET", "JWT_SECRET", default="test-system-session"),
        admin_initial_email=os.environ.get("ADMIN_INITIAL_EMAIL", "admin@example.test"),
        admin_initial_password_hash=os.environ.get("ADMIN_INITIAL_PASSWORD_HASH", "plain:admin-password"),
        system_admin_initial_email=_env_first(
            "SYSTEM_ADMIN_INITIAL_EMAIL",
            "ADMIN_INITIAL_EMAIL",
            default="system-admin@example.test",
        ),
        system_admin_initial_password_hash=_env_first(
            "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH",
            "ADMIN_INITIAL_PASSWORD_HASH",
            default="plain:system-admin-password",
        ),
        database_url=os.environ.get("DATABASE_URL"),
        object_storage_backend=os.environ.get("OBJECT_STORAGE_BACKEND", "reference"),
        object_storage_root=os.environ.get("OBJECT_STORAGE_ROOT", ".object-storage"),
    )


def _env_first(*keys: str, default: str) -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def _missing_required_groups(groups: list[tuple[str, ...]]) -> list[str]:
    missing: list[str] = []
    for group in groups:
        if not any(os.environ.get(key) for key in group):
            missing.append("|".join(group))
    return missing
