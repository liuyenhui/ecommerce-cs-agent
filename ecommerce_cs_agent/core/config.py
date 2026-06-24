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
    object_storage_endpoint: str | None = None
    object_storage_bucket: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_path_style: bool = True
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    admin_oidc_enabled: bool = False
    admin_oidc_issuer: str | None = None
    admin_oidc_client_id: str | None = None
    admin_oidc_client_secret: str | None = None
    admin_oidc_redirect_uri: str | None = None
    open_erp_integration_token: str = "test-open-erp-integration-token"
    open_erp_billing_lease_secret: str = "test-open-erp-billing-secret"


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
        object_storage_endpoint=os.environ.get("OBJECT_STORAGE_ENDPOINT"),
        object_storage_bucket=os.environ.get("OBJECT_STORAGE_BUCKET"),
        object_storage_region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        object_storage_path_style=os.environ.get("OBJECT_STORAGE_PATH_STYLE", "true").lower() not in {"0", "false", "no"},
        object_storage_access_key_id=os.environ.get("OBJECT_STORAGE_ACCESS_KEY_ID"),
        object_storage_secret_access_key=os.environ.get("OBJECT_STORAGE_SECRET_ACCESS_KEY"),
        llm_api_key=os.environ.get("LLM_API_KEY"),
        llm_base_url=os.environ.get("LLM_BASE_URL"),
        llm_model=os.environ.get("LLM_MODEL"),
        admin_oidc_enabled=_env_bool("ADMIN_OIDC_ENABLED", "OIDC_ENABLED"),
        admin_oidc_issuer=_env_first_optional("ADMIN_OIDC_ISSUER", "OIDC_ISSUER"),
        admin_oidc_client_id=_env_first_optional("ADMIN_OIDC_CLIENT_ID", "OIDC_CLIENT_ID"),
        admin_oidc_client_secret=_env_first_optional("ADMIN_OIDC_CLIENT_SECRET", "OIDC_CLIENT_SECRET"),
        admin_oidc_redirect_uri=_env_first_optional("ADMIN_OIDC_REDIRECT_URI", "OIDC_REDIRECT_URI"),
        open_erp_integration_token=os.environ.get("OPEN_ERP_INTEGRATION_TOKEN", "test-open-erp-integration-token"),
        open_erp_billing_lease_secret=os.environ.get("OPEN_ERP_BILLING_LEASE_SECRET", "test-open-erp-billing-secret"),
    )


def _env_first(*keys: str, default: str) -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def _env_first_optional(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def _env_bool(*keys: str) -> bool:
    value = _env_first_optional(*keys)
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def _missing_required_groups(groups: list[tuple[str, ...]]) -> list[str]:
    missing: list[str] = []
    for group in groups:
        if not any(os.environ.get(key) for key in group):
            missing.append("|".join(group))
    return missing
