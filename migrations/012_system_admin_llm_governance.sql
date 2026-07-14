-- LLM governance stores Kubernetes Secret references and redacted operational
-- metadata only. Secret payloads, prompts, customer messages, model outputs,
-- and HTTP bodies are forbidden from these tables.

CREATE TABLE IF NOT EXISTS llm_provider_config (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 128),
    provider_type text NOT NULL CHECK (length(provider_type) BETWEEN 1 AND 64),
    base_url text NOT NULL CHECK (length(base_url) BETWEEN 1 AND 2048),
    secret_namespace text NOT NULL CHECK (length(secret_namespace) BETWEEN 1 AND 253),
    secret_name text NOT NULL CHECK (length(secret_name) BETWEEN 1 AND 253),
    secret_key text NOT NULL CHECK (length(secret_key) BETWEEN 1 AND 253),
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
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE RESTRICT,
    version_number bigint NOT NULL CHECK (version_number > 0),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'validated', 'pending_publish', 'running', 'superseded', 'rolled_back')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    description text CHECK (description IS NULL OR length(description) <= 512),
    configuration_hash char(64) NOT NULL
        CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
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
    CHECK (rollback_of_version_id IS NULL OR rollback_of_version_id <> id),
    UNIQUE (organization_id, version_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_config_version_id_organization
    ON llm_config_version (id, organization_id);

CREATE TABLE IF NOT EXISTS llm_eval_run (
    id varchar(128) PRIMARY KEY
        CHECK (length(id) BETWEEN 1 AND 128 AND id ~ '^[A-Za-z0-9][A-Za-z0-9_:-]*$'),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE RESTRICT,
    config_version_id uuid NOT NULL,
    config_revision integer NOT NULL CHECK (config_revision > 0),
    configuration_hash char(64) NOT NULL
        CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'canceled')),
    gate_status text NOT NULL DEFAULT 'pending'
        CHECK (gate_status IN ('pending', 'passed', 'failed')),
    red_line_failures integer NOT NULL DEFAULT 0 CHECK (red_line_failures >= 0),
    report_ref text CHECK (
        report_ref IS NULL OR (
            length(report_ref) BETWEEN 1 AND 512
            AND report_ref !~ '[[:cntrl:]]'
        )
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    UNIQUE (id, organization_id, config_version_id),
    FOREIGN KEY (config_version_id, organization_id)
        REFERENCES llm_config_version(id, organization_id) ON DELETE RESTRICT,
    CHECK (
        (status = 'running' AND gate_status = 'pending' AND completed_at IS NULL)
        OR (status = 'completed' AND gate_status IN ('passed', 'failed') AND completed_at IS NOT NULL)
        OR (status IN ('failed', 'canceled') AND gate_status = 'failed' AND completed_at IS NOT NULL)
    ),
    CHECK (completed_at IS NULL OR completed_at >= created_at),
    CHECK (gate_status <> 'passed' OR (status = 'completed' AND red_line_failures = 0))
);

CREATE INDEX IF NOT EXISTS idx_llm_eval_run_version_created
    ON llm_eval_run (organization_id, config_version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_release_record (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE RESTRICT,
    config_version_id uuid NOT NULL,
    evaluation_run_id varchar(128) NOT NULL
        CHECK (
            length(evaluation_run_id) <= 128
            AND evaluation_run_id ~ '[^[:space:]]'
        ),
    evaluation_config_version_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'superseded', 'rolled_back')),
    submitted_by_system_admin_user_id uuid NOT NULL
        REFERENCES system_admin_user(id) ON DELETE RESTRICT,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    published_by_system_admin_user_id uuid
        REFERENCES system_admin_user(id) ON DELETE RESTRICT,
    published_at timestamptz,
    rollback_of_release_id uuid REFERENCES llm_release_record(id) ON DELETE RESTRICT,
    rollback_of_version_id uuid REFERENCES llm_config_version(id) ON DELETE RESTRICT,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    UNIQUE (config_version_id),
    FOREIGN KEY (config_version_id, organization_id)
        REFERENCES llm_config_version(id, organization_id) ON DELETE RESTRICT,
    FOREIGN KEY (evaluation_run_id, organization_id, evaluation_config_version_id)
        REFERENCES llm_eval_run(id, organization_id, config_version_id) ON DELETE RESTRICT,
    CHECK (
        (status = 'pending' AND published_by_system_admin_user_id IS NULL AND published_at IS NULL)
        OR (status IN ('running', 'superseded', 'rolled_back')
            AND published_by_system_admin_user_id IS NOT NULL AND published_at IS NOT NULL)
    ),
    CHECK (
        (rollback_of_release_id IS NULL
            AND rollback_of_version_id IS NULL
            AND evaluation_config_version_id = config_version_id)
        OR (rollback_of_release_id IS NOT NULL
            AND rollback_of_version_id IS NOT NULL
            AND evaluation_config_version_id = rollback_of_version_id)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_release_record_one_running
    ON llm_release_record (organization_id) WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_llm_release_record_org_status_submitted
    ON llm_release_record (organization_id, status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_release_record_evaluation_reference
    ON llm_release_record (evaluation_run_id, organization_id, evaluation_config_version_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_config_version_one_running
    ON llm_config_version (organization_id)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_llm_config_version_status_created
    ON llm_config_version (organization_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS llm_scenario_route (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_version_id uuid NOT NULL
        REFERENCES llm_config_version(id) ON DELETE RESTRICT,
    scenario text NOT NULL CHECK (length(scenario) BETWEEN 1 AND 64),
    primary_provider_config_id uuid NOT NULL
        REFERENCES llm_provider_config(id) ON DELETE RESTRICT,
    primary_model text NOT NULL CHECK (length(primary_model) BETWEEN 1 AND 128),
    fallback_provider_config_id uuid
        REFERENCES llm_provider_config(id) ON DELETE RESTRICT,
    fallback_model text CHECK (fallback_model IS NULL OR length(fallback_model) BETWEEN 1 AND 128),
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
    provider_revision integer NOT NULL DEFAULT 1 CHECK (provider_revision > 0),
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
    organization_id uuid NOT NULL REFERENCES organization(id) ON DELETE RESTRICT,
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

-- Lock order: route row when present, version rows in UUID order, then version advisory locks.
CREATE OR REPLACE FUNCTION lock_llm_config_versions(
    first_version_id uuid,
    second_version_id uuid DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    lower_version_id uuid;
    higher_version_id uuid;
BEGIN
    IF first_version_id IS NULL THEN
        RETURN;
    END IF;

    IF second_version_id IS NULL OR first_version_id = second_version_id THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended('llm_config_version:' || first_version_id::text, 0)
        );
        RETURN;
    END IF;

    IF first_version_id::text < second_version_id::text THEN
        lower_version_id := first_version_id;
        higher_version_id := second_version_id;
    ELSE
        lower_version_id := second_version_id;
        higher_version_id := first_version_id;
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('llm_config_version:' || lower_version_id::text, 0)
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended('llm_config_version:' || higher_version_id::text, 0)
    );
END;
$$;

CREATE OR REPLACE FUNCTION validate_llm_invocation_metric_route_role()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    metric_version_id uuid;
BEGIN
    SELECT route.config_version_id
    INTO metric_version_id
    FROM llm_scenario_route AS route
    WHERE route.id = NEW.scenario_route_id
    FOR KEY SHARE;

    IF metric_version_id IS NULL THEN
        RAISE EXCEPTION 'invocation metric route does not exist'
            USING ERRCODE = '23503';
    END IF;

    PERFORM 1
    FROM llm_config_version AS route_version
    WHERE route_version.id = metric_version_id
    ORDER BY route_version.id::text
    FOR KEY SHARE;
    PERFORM lock_llm_config_versions(metric_version_id);

    IF NOT EXISTS (
        SELECT 1
        FROM llm_config_version AS route_version
        WHERE route_version.id = metric_version_id
          AND route_version.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'invocation metric organization must match its route config version'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM llm_scenario_route AS route
    JOIN llm_config_version AS route_version
      ON route_version.id = route.config_version_id
    WHERE route.id = NEW.scenario_route_id
      AND route.config_version_id = metric_version_id
      AND route_version.status = 'running'
    FOR KEY SHARE OF route, route_version;

    IF NOT FOUND THEN
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
    BEFORE INSERT
    ON llm_invocation_metric
    FOR EACH ROW
    EXECUTE FUNCTION validate_llm_invocation_metric_route_role();

CREATE OR REPLACE FUNCTION protect_llm_invocation_metric_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'invocation metrics are append-only'
        USING ERRCODE = '23514';
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_llm_invocation_metric_history
    ON llm_invocation_metric;

CREATE TRIGGER trg_protect_llm_invocation_metric_history
    BEFORE UPDATE OR DELETE ON llm_invocation_metric
    FOR EACH ROW
    EXECUTE FUNCTION protect_llm_invocation_metric_history();

CREATE OR REPLACE FUNCTION protect_llm_scenario_route_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM 1
        FROM llm_config_version AS route_version
        WHERE route_version.id = NEW.config_version_id
        ORDER BY route_version.id::text
        FOR KEY SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'scenario route config version does not exist'
                USING ERRCODE = '23503';
        END IF;
        PERFORM lock_llm_config_versions(NEW.config_version_id);
        PERFORM 1
        FROM llm_config_version AS route_version
        WHERE route_version.id = NEW.config_version_id
          AND route_version.status = 'draft';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'scenario routes can only be added to draft config versions'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        PERFORM 1
        FROM llm_config_version AS route_version
        WHERE route_version.id IN (OLD.config_version_id, NEW.config_version_id)
        ORDER BY route_version.id::text
        FOR KEY SHARE;
        PERFORM lock_llm_config_versions(OLD.config_version_id, NEW.config_version_id);
    ELSE
        PERFORM 1
        FROM llm_config_version AS route_version
        WHERE route_version.id = OLD.config_version_id
        ORDER BY route_version.id::text
        FOR KEY SHARE;
        PERFORM lock_llm_config_versions(OLD.config_version_id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM llm_invocation_metric AS metric
        WHERE metric.scenario_route_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'scenario routes referenced by invocation metrics are immutable'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM llm_config_version AS route_version
    WHERE route_version.id = OLD.config_version_id
      AND route_version.status <> 'draft'
    FOR KEY SHARE;
    IF FOUND THEN
        RAISE EXCEPTION 'scenario routes are immutable after their config version leaves draft'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        PERFORM 1
        FROM llm_config_version AS route_version
        WHERE route_version.id = NEW.config_version_id
          AND route_version.status <> 'draft'
        FOR KEY SHARE;
        IF FOUND THEN
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
    BEFORE INSERT OR UPDATE OR DELETE ON llm_scenario_route
    FOR EACH ROW
    EXECUTE FUNCTION protect_llm_scenario_route_history();

CREATE OR REPLACE FUNCTION validate_llm_config_version_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM lock_llm_config_versions(OLD.id);
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'only draft config versions may be deleted'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' OR NEW.revision <> 1
            OR NEW.published_by_system_admin_user_id IS NOT NULL
            OR NEW.published_at IS NOT NULL
        THEN
            RAISE EXCEPTION 'config versions must start as unpublished revision-one drafts'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.rollback_of_version_id IS NOT NULL THEN
            PERFORM 1
            FROM llm_config_version AS rollback_target
            WHERE rollback_target.id = NEW.rollback_of_version_id
              AND rollback_target.organization_id = NEW.organization_id
              AND rollback_target.status IN ('superseded', 'rolled_back')
            ORDER BY rollback_target.id::text
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'rollback source must be a terminal version from the same organization'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM lock_llm_config_versions(NEW.id, NEW.rollback_of_version_id);
        ELSE
            PERFORM lock_llm_config_versions(NEW.id);
        END IF;
        RETURN NEW;
    END IF;

    PERFORM lock_llm_config_versions(OLD.id, NEW.id);

    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'config version id is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'config version updates must increment revision by exactly one'
            USING ERRCODE = '23514';
    END IF;

    IF NOT (
        (NEW.status = OLD.status
            AND OLD.status IN ('draft', 'validated', 'pending_publish'))
        OR (OLD.status = 'draft' AND NEW.status = 'validated')
        OR (OLD.status = 'validated' AND NEW.status = 'pending_publish')
        OR (OLD.status = 'pending_publish' AND NEW.status = 'running')
        OR (OLD.status = 'running' AND NEW.status IN ('superseded', 'rolled_back'))
    ) THEN
        RAISE EXCEPTION 'invalid config version lifecycle transition: % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.version_number IS DISTINCT FROM OLD.version_number
    THEN
        RAISE EXCEPTION 'config version organization and number are immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.rollback_of_version_id IS DISTINCT FROM OLD.rollback_of_version_id THEN
        RAISE EXCEPTION 'rollback source must be supplied during draft creation and is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.created_by_system_admin_user_id IS DISTINCT FROM OLD.created_by_system_admin_user_id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'config version creation metadata is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NOT (OLD.status = 'draft' AND NEW.status = 'draft')
        AND (
            NEW.configuration_hash IS DISTINCT FROM OLD.configuration_hash
            OR NEW.description IS DISTINCT FROM OLD.description
        )
    THEN
        RAISE EXCEPTION 'config version content is frozen after draft'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'pending_publish' AND NEW.status = 'running' THEN
        IF OLD.published_by_system_admin_user_id IS NOT NULL
            OR OLD.published_at IS NOT NULL
            OR NEW.published_by_system_admin_user_id IS NULL
            OR NEW.published_at IS NULL
        THEN
            RAISE EXCEPTION 'publishing must set actor and timestamp exactly once'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.published_by_system_admin_user_id IS DISTINCT FROM OLD.published_by_system_admin_user_id
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
    THEN
        RAISE EXCEPTION 'publication metadata is immutable outside pending-to-running publish'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_llm_config_version_transition
    ON llm_config_version;

CREATE TRIGGER trg_validate_llm_config_version_transition
    BEFORE INSERT OR UPDATE OR DELETE ON llm_config_version
    FOR EACH ROW
    EXECUTE FUNCTION validate_llm_config_version_transition();

CREATE OR REPLACE FUNCTION protect_llm_eval_run_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    version_organization_id uuid;
    version_status text;
    version_revision integer;
    version_configuration_hash text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'evaluation run history is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT organization_id, status, revision, configuration_hash
        INTO version_organization_id, version_status, version_revision, version_configuration_hash
        FROM llm_config_version
        WHERE id = NEW.config_version_id
        FOR UPDATE;
        IF NOT FOUND
            OR version_organization_id IS DISTINCT FROM NEW.organization_id
            OR version_status <> 'validated'
        THEN
            RAISE EXCEPTION 'evaluation runs require a validated config version snapshot'
                USING ERRCODE = '23514';
        END IF;
        PERFORM lock_llm_config_versions(NEW.config_version_id);
        IF NEW.config_revision <> version_revision
            OR NEW.configuration_hash IS DISTINCT FROM version_configuration_hash
        THEN
            RAISE EXCEPTION 'evaluation snapshot must match config version revision and hash'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status <> 'running' OR NEW.gate_status <> 'pending'
            OR NEW.completed_at IS NOT NULL OR NEW.revision <> 1
        THEN
            RAISE EXCEPTION 'evaluation run must start in running state' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status <> 'running' OR NEW.status NOT IN ('completed', 'failed', 'canceled')
        OR NEW.revision <> OLD.revision + 1
        OR NEW.id IS DISTINCT FROM OLD.id
        OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.config_version_id IS DISTINCT FROM OLD.config_version_id
        OR NEW.config_revision IS DISTINCT FROM OLD.config_revision
        OR NEW.configuration_hash IS DISTINCT FROM OLD.configuration_hash
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR NEW.completed_at IS NULL
    THEN
        RAISE EXCEPTION 'invalid evaluation run lifecycle transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_llm_eval_run_history ON llm_eval_run;
CREATE TRIGGER trg_protect_llm_eval_run_history
    BEFORE INSERT OR UPDATE OR DELETE ON llm_eval_run
    FOR EACH ROW EXECUTE FUNCTION protect_llm_eval_run_history();

CREATE OR REPLACE FUNCTION protect_llm_release_record_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM 1
        FROM llm_config_version AS release_version
        WHERE release_version.id IN (NEW.config_version_id, NEW.rollback_of_version_id)
        ORDER BY release_version.id::text
        FOR KEY SHARE;
        IF NOT EXISTS (
            SELECT 1 FROM llm_config_version WHERE id = NEW.config_version_id
        ) THEN
            RAISE EXCEPTION 'release config version does not exist'
                USING ERRCODE = '23503';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM llm_config_version AS target_version
            WHERE target_version.id = NEW.config_version_id
              AND target_version.rollback_of_version_id
                  IS NOT DISTINCT FROM NEW.rollback_of_version_id
        ) THEN
            RAISE EXCEPTION 'release rollback source must match its config version rollback source'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.rollback_of_version_id IS NULL THEN
            PERFORM lock_llm_config_versions(NEW.config_version_id);
            IF NEW.evaluation_config_version_id <> NEW.config_version_id THEN
                RAISE EXCEPTION 'normal release evaluation must target its config version'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            PERFORM lock_llm_config_versions(
                NEW.config_version_id,
                NEW.rollback_of_version_id
            );
            IF NEW.evaluation_config_version_id <> NEW.rollback_of_version_id THEN
                RAISE EXCEPTION 'rollback release evaluation must target its source version'
                    USING ERRCODE = '23514';
            END IF;
        END IF;

        IF NEW.status <> 'pending' OR NEW.revision <> 1
            OR NEW.published_by_system_admin_user_id IS NOT NULL OR NEW.published_at IS NOT NULL
        THEN
            RAISE EXCEPTION 'release records must start as pending revision one'
                USING ERRCODE = '23514';
        END IF;
        PERFORM 1
        FROM llm_eval_run AS release_evaluation
        WHERE release_evaluation.id = NEW.evaluation_run_id
          AND release_evaluation.organization_id = NEW.organization_id
          AND release_evaluation.config_version_id = NEW.evaluation_config_version_id
          AND release_evaluation.status = 'completed'
          AND release_evaluation.gate_status = 'passed'
          AND release_evaluation.red_line_failures = 0
          AND release_evaluation.completed_at >= release_evaluation.created_at
        FOR KEY SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'release records require a completed passing evaluation snapshot'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.rollback_of_release_id IS NOT NULL THEN
            PERFORM 1
            FROM llm_release_record AS source
            JOIN llm_config_version AS source_version
              ON source_version.id = source.config_version_id
            WHERE source.id = NEW.rollback_of_release_id
              AND source.config_version_id = NEW.rollback_of_version_id
              AND source.organization_id = NEW.organization_id
              AND source_version.organization_id = NEW.organization_id
              AND source.status IN ('superseded', 'rolled_back')
              AND source_version.status = source.status;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'rollback release and version must identify matching terminal history'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        -- Terminal rows can never be deleted. Reject before taking a version
        -- advisory lock so the rollback-source FK cannot form a release-row /
        -- version-lock cycle with a concurrent rollback insert.
        IF OLD.status IN ('superseded', 'rolled_back') THEN
            RAISE EXCEPTION 'terminal release records are immutable'
                USING ERRCODE = '23514';
        END IF;
        PERFORM 1
        FROM llm_config_version AS release_version
        WHERE release_version.id = OLD.config_version_id
        ORDER BY release_version.id::text
        FOR KEY SHARE;
        PERFORM lock_llm_config_versions(OLD.config_version_id);
        RAISE EXCEPTION 'release records are immutable history'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM llm_config_version AS release_version
    WHERE release_version.id IN (OLD.config_version_id, NEW.config_version_id)
    ORDER BY release_version.id::text
    FOR KEY SHARE;
    PERFORM lock_llm_config_versions(OLD.config_version_id, NEW.config_version_id);

    IF OLD.status IN ('superseded', 'rolled_back') THEN
        RAISE EXCEPTION 'terminal release records are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.config_version_id IS DISTINCT FROM OLD.config_version_id
        OR NEW.evaluation_run_id IS DISTINCT FROM OLD.evaluation_run_id
        OR NEW.evaluation_config_version_id IS DISTINCT FROM OLD.evaluation_config_version_id
        OR NEW.submitted_by_system_admin_user_id IS DISTINCT FROM OLD.submitted_by_system_admin_user_id
        OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
        OR NEW.rollback_of_release_id IS DISTINCT FROM OLD.rollback_of_release_id
        OR NEW.rollback_of_version_id IS DISTINCT FROM OLD.rollback_of_version_id
    THEN
        RAISE EXCEPTION 'release record linkage and evaluation are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.revision <> OLD.revision + 1
        OR NOT (
            (OLD.status = 'pending' AND NEW.status = 'running')
            OR (OLD.status = 'running' AND NEW.status IN ('superseded', 'rolled_back'))
        )
    THEN
        RAISE EXCEPTION 'invalid release record lifecycle transition'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'pending' AND NEW.status = 'running' THEN
        IF NEW.published_by_system_admin_user_id IS NULL OR NEW.published_at IS NULL THEN
            RAISE EXCEPTION 'running release requires publication metadata'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.published_by_system_admin_user_id IS DISTINCT FROM OLD.published_by_system_admin_user_id
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
    THEN
        RAISE EXCEPTION 'release publication metadata is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_llm_release_record_history ON llm_release_record;
CREATE TRIGGER trg_protect_llm_release_record_history
    BEFORE INSERT OR UPDATE OR DELETE ON llm_release_record
    FOR EACH ROW EXECUTE FUNCTION protect_llm_release_record_history();

CREATE OR REPLACE FUNCTION validate_llm_release_version_consistency()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    affected_version_id uuid;
    version_status text;
    release_count integer;
    matching_release_count integer;
BEGIN
    IF TG_TABLE_NAME = 'llm_config_version' THEN
        IF TG_OP = 'DELETE' THEN
            affected_version_id := OLD.id;
        ELSE
            affected_version_id := NEW.id;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN
            affected_version_id := OLD.config_version_id;
        ELSE
            affected_version_id := NEW.config_version_id;
        END IF;
    END IF;

    PERFORM 1
    FROM llm_config_version AS release_version
    WHERE release_version.id = affected_version_id
    ORDER BY release_version.id::text
    FOR KEY SHARE;
    PERFORM lock_llm_config_versions(affected_version_id);

    SELECT status
    INTO version_status
    FROM llm_config_version
    WHERE id = affected_version_id;

    SELECT count(*)
    INTO release_count
    FROM llm_release_record
    WHERE config_version_id = affected_version_id;

    IF version_status IS NULL THEN
        IF release_count <> 0 THEN
            RAISE EXCEPTION 'release records require an existing config version'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    IF version_status IN ('draft', 'validated') THEN
        IF release_count <> 0 THEN
            RAISE EXCEPTION 'draft and validated config versions must not have release records'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    SELECT count(*)
    INTO matching_release_count
    FROM llm_release_record
    WHERE config_version_id = affected_version_id
      AND status = CASE
          WHEN version_status = 'pending_publish' THEN 'pending'
          ELSE version_status
      END;

    IF version_status = 'pending_publish' THEN
        IF release_count <> 1 OR matching_release_count <> 1 THEN
            RAISE EXCEPTION 'pending_publish config versions require exactly one pending release record'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    IF release_count <> 1 OR matching_release_count <> 1 THEN
        RAISE EXCEPTION 'terminal config version and release record statuses must match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_llm_release_version_consistency ON llm_config_version;
CREATE CONSTRAINT TRIGGER trg_llm_release_version_consistency
    AFTER INSERT OR UPDATE OR DELETE ON llm_config_version
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_llm_release_version_consistency();

DROP TRIGGER IF EXISTS trg_llm_release_version_consistency ON llm_release_record;
CREATE CONSTRAINT TRIGGER trg_llm_release_version_consistency
    AFTER INSERT OR UPDATE OR DELETE ON llm_release_record
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_llm_release_version_consistency();

CREATE OR REPLACE FUNCTION protect_llm_connection_test_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    provider_revision_snapshot integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'connection test history is immutable'
            USING ERRCODE = '23514';
    END IF;

    SELECT revision
    INTO provider_revision_snapshot
    FROM llm_provider_config
    WHERE id = NEW.provider_config_id
    FOR KEY SHARE;

    IF provider_revision_snapshot IS NULL THEN
        RAISE EXCEPTION 'connection test provider does not exist'
            USING ERRCODE = '23503';
    END IF;
    IF NEW.provider_revision <> provider_revision_snapshot THEN
        RAISE EXCEPTION 'connection test provider revision must match the locked provider revision'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_llm_connection_test_history ON llm_connection_test;
CREATE TRIGGER trg_protect_llm_connection_test_history
    BEFORE INSERT OR UPDATE OR DELETE ON llm_connection_test
    FOR EACH ROW EXECUTE FUNCTION protect_llm_connection_test_history();

CREATE OR REPLACE FUNCTION protect_llm_provider_endpoint()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'provider identity and creation metadata are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.provider_type IS DISTINCT FROM OLD.provider_type
        OR NEW.base_url IS DISTINCT FROM OLD.base_url
        OR NEW.secret_namespace IS DISTINCT FROM OLD.secret_namespace
        OR NEW.secret_name IS DISTINCT FROM OLD.secret_name
        OR NEW.secret_key IS DISTINCT FROM OLD.secret_key
    THEN
        RAISE EXCEPTION 'provider endpoint and Secret reference are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'provider updates must increment revision exactly once'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_llm_provider_endpoint ON llm_provider_config;
CREATE TRIGGER trg_protect_llm_provider_endpoint
    BEFORE UPDATE ON llm_provider_config
    FOR EACH ROW EXECUTE FUNCTION protect_llm_provider_endpoint();
