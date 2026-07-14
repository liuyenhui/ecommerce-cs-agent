-- LLM governance stores Kubernetes Secret references and redacted operational
-- metadata only. Secret payloads, prompts, customer messages, model outputs,
-- and HTTP bodies are forbidden from these tables.

CREATE TABLE IF NOT EXISTS llm_provider_config (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    provider_type text NOT NULL,
    base_url text NOT NULL,
    secret_namespace text NOT NULL,
    secret_name text NOT NULL,
    secret_key text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled', 'unhealthy')),
    last_connection_test_status text
        CHECK (last_connection_test_status IN ('passed', 'failed')),
    last_connection_test_latency_ms integer
        CHECK (last_connection_test_latency_ms IS NULL OR last_connection_test_latency_ms >= 0),
    last_connection_test_error_code text,
    last_connection_tested_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    CHECK ((enabled AND status <> 'disabled') OR (NOT enabled AND status = 'disabled'))
);

CREATE INDEX IF NOT EXISTS idx_llm_provider_config_type_status
    ON llm_provider_config (provider_type, status, enabled);

CREATE TABLE IF NOT EXISTS llm_config_version (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_number bigint NOT NULL UNIQUE CHECK (version_number > 0),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'validated', 'pending_publish', 'running', 'superseded', 'rolled_back')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    description text,
    configuration_hash text NOT NULL,
    created_by_system_admin_user_id uuid NOT NULL
        REFERENCES system_admin_user(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_by_system_admin_user_id uuid
        REFERENCES system_admin_user(id) ON DELETE RESTRICT,
    published_at timestamptz,
    rollback_of_version_id uuid
        REFERENCES llm_config_version(id) ON DELETE RESTRICT,
    CHECK (
        (status IN ('draft', 'validated', 'pending_publish')
            AND published_at IS NULL
            AND published_by_system_admin_user_id IS NULL)
        OR (status IN ('running', 'superseded', 'rolled_back')
            AND published_at IS NOT NULL
            AND published_by_system_admin_user_id IS NOT NULL)
    ),
    -- Rollback creates a new running version from a historical source. Once
    -- superseded, that derived version retains the source link for history.
    CHECK (rollback_of_version_id IS NULL OR status IN ('running', 'superseded')),
    CHECK (rollback_of_version_id IS NULL OR rollback_of_version_id <> id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_config_version_one_running
    ON llm_config_version (status)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_llm_config_version_status_created
    ON llm_config_version (status, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_scenario_route (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_version_id uuid NOT NULL
        REFERENCES llm_config_version(id) ON DELETE RESTRICT,
    scenario text NOT NULL,
    primary_provider_config_id uuid NOT NULL
        REFERENCES llm_provider_config(id) ON DELETE RESTRICT,
    primary_model text NOT NULL,
    fallback_provider_config_id uuid
        REFERENCES llm_provider_config(id) ON DELETE RESTRICT,
    fallback_model text,
    enabled boolean NOT NULL DEFAULT true,
    temperature numeric(4, 3) NOT NULL DEFAULT 0.200
        CHECK (temperature >= 0 AND temperature <= 2),
    max_output_tokens integer NOT NULL DEFAULT 1024
        CHECK (max_output_tokens > 0),
    timeout_seconds integer NOT NULL DEFAULT 30 CHECK (timeout_seconds > 0),
    max_retries integer NOT NULL DEFAULT 1 CHECK (max_retries >= 0),
    circuit_breaker_threshold integer NOT NULL DEFAULT 5
        CHECK (circuit_breaker_threshold > 0),
    recovery_probe_seconds integer NOT NULL DEFAULT 60
        CHECK (recovery_probe_seconds > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    UNIQUE (config_version_id, scenario),
    CHECK (
        (fallback_provider_config_id IS NULL AND fallback_model IS NULL)
        OR (fallback_provider_config_id IS NOT NULL AND fallback_model IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_llm_scenario_route_primary_provider_model
    ON llm_scenario_route (primary_provider_config_id, primary_model);

CREATE INDEX IF NOT EXISTS idx_llm_scenario_route_fallback_provider_model
    ON llm_scenario_route (fallback_provider_config_id, fallback_model)
    WHERE fallback_provider_config_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_llm_scenario_route_scenario
    ON llm_scenario_route (scenario, config_version_id);

CREATE TABLE IF NOT EXISTS llm_connection_test (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_config_id uuid NOT NULL
        REFERENCES llm_provider_config(id) ON DELETE RESTRICT,
    config_version_id uuid
        REFERENCES llm_config_version(id) ON DELETE RESTRICT,
    checked_by_system_admin_user_id uuid NOT NULL
        REFERENCES system_admin_user(id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (status IN ('passed', 'failed')),
    latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    checked_at timestamptz NOT NULL DEFAULT now(),
    error_code text,
    redacted_error_message text,
    CHECK (
        (status = 'passed' AND error_code IS NULL AND redacted_error_message IS NULL)
        OR status = 'failed'
    )
);

CREATE INDEX IF NOT EXISTS idx_llm_connection_test_provider_checked
    ON llm_connection_test (provider_config_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_connection_test_version_checked
    ON llm_connection_test (config_version_id, checked_at DESC)
    WHERE config_version_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS llm_invocation_metric (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    scenario_route_id uuid NOT NULL
        REFERENCES llm_scenario_route(id) ON DELETE RESTRICT,
    route_role text NOT NULL CHECK (route_role IN ('primary', 'fallback')),
    organization_id uuid REFERENCES organization(id) ON DELETE RESTRICT,
    store_id uuid REFERENCES store(id) ON DELETE RESTRICT,
    input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    latency_ms integer NOT NULL CHECK (latency_ms >= 0),
    status text NOT NULL CHECK (status IN ('succeeded', 'failed', 'timed_out', 'rejected')),
    error_code text,
    estimated_cost_micros bigint NOT NULL DEFAULT 0 CHECK (estimated_cost_micros >= 0),
    currency char(3) NOT NULL DEFAULT 'USD'
        CHECK (currency IN ('CNY', 'USD')),
    CHECK (store_id IS NULL OR organization_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_llm_invocation_metric_route_occurred
    ON llm_invocation_metric (scenario_route_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_invocation_metric_organization_store_occurred
    ON llm_invocation_metric (organization_id, store_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_invocation_metric_store_occurred
    ON llm_invocation_metric (store_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_invocation_metric_status_occurred
    ON llm_invocation_metric (status, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_invocation_metric_occurred
    ON llm_invocation_metric (occurred_at DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_llm_invocation_metric_store_organization'
          AND conrelid = 'llm_invocation_metric'::regclass
    ) THEN
        ALTER TABLE llm_invocation_metric
            ADD CONSTRAINT fk_llm_invocation_metric_store_organization
            FOREIGN KEY (store_id, organization_id)
            REFERENCES store (id, organization_id)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION validate_llm_invocation_metric_route_role()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.scenario_route_id::text, 0));

    IF NOT EXISTS (
        SELECT 1
        FROM llm_scenario_route AS route
        JOIN llm_config_version AS route_version
          ON route_version.id = route.config_version_id
        WHERE route.id = NEW.scenario_route_id
          AND route_version.status = 'running'
    ) THEN
        RAISE EXCEPTION 'invocation metrics require a route from the running config version'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.route_role = 'fallback' AND NOT EXISTS (
        SELECT 1
        FROM llm_scenario_route AS route
        WHERE route.id = NEW.scenario_route_id
          AND route.fallback_provider_config_id IS NOT NULL
          AND route.fallback_model IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'fallback route role requires a configured fallback model'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_llm_invocation_metric_route_role
    ON llm_invocation_metric;

CREATE TRIGGER trg_validate_llm_invocation_metric_route_role
    BEFORE INSERT OR UPDATE OF scenario_route_id, route_role
    ON llm_invocation_metric
    FOR EACH ROW
    EXECUTE FUNCTION validate_llm_invocation_metric_route_role();

CREATE OR REPLACE FUNCTION protect_llm_scenario_route_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(OLD.id::text, 0));

    IF EXISTS (
        SELECT 1
        FROM llm_invocation_metric AS metric
        WHERE metric.scenario_route_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'scenario routes referenced by invocation metrics are immutable'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM llm_config_version AS route_version
        WHERE route_version.id = OLD.config_version_id
          AND route_version.status <> 'draft'
    ) THEN
        RAISE EXCEPTION 'scenario routes are immutable after their config version leaves draft'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF EXISTS (
            SELECT 1
            FROM llm_config_version AS route_version
            WHERE route_version.id = NEW.config_version_id
              AND route_version.status <> 'draft'
        ) THEN
            RAISE EXCEPTION 'scenario routes cannot be moved into a non-draft config version'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_llm_scenario_route_history
    ON llm_scenario_route;

CREATE TRIGGER trg_protect_llm_scenario_route_history
    BEFORE UPDATE OR DELETE ON llm_scenario_route
    FOR EACH ROW
    EXECUTE FUNCTION protect_llm_scenario_route_history();
