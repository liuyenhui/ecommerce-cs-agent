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


def load_settings() -> Settings:
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development"))
    production = environment.lower() in {"production", "prod"}
    required = [
        "AGENT_API_TOKEN",
        "ADMIN_SESSION_SECRET",
        "SYSTEM_ADMIN_SESSION_SECRET",
        "ADMIN_INITIAL_EMAIL",
        "ADMIN_INITIAL_PASSWORD_HASH",
        "SYSTEM_ADMIN_INITIAL_EMAIL",
        "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH",
        "DATABASE_URL",
    ]
    if production:
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise RuntimeError(f"Missing required production settings: {', '.join(missing)}")

    return Settings(
        service_name=os.environ.get("SERVICE_NAME", "ecommerce-cs-agent-api"),
        environment=environment,
        graph_version=os.environ.get("GRAPH_VERSION", "reply-decision-graph-v1"),
        model_version=os.environ.get("MODEL_VERSION", "reply-generator-v1"),
        agent_api_token=os.environ.get("AGENT_API_TOKEN", "test-agent-token"),
        admin_session=os.environ.get("ADMIN_SESSION_SECRET", "test-admin-session"),
        system_admin_session=os.environ.get("SYSTEM_ADMIN_SESSION_SECRET", "test-system-session"),
        admin_initial_email=os.environ.get("ADMIN_INITIAL_EMAIL", "admin@example.test"),
        admin_initial_password_hash=os.environ.get("ADMIN_INITIAL_PASSWORD_HASH", "plain:admin-password"),
        system_admin_initial_email=os.environ.get("SYSTEM_ADMIN_INITIAL_EMAIL", "system-admin@example.test"),
        system_admin_initial_password_hash=os.environ.get(
            "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH",
            "plain:system-admin-password",
        ),
        database_url=os.environ.get("DATABASE_URL"),
    )
