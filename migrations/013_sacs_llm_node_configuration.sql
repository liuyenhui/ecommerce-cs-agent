CREATE TABLE IF NOT EXISTS llm_model_config (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    provider TEXT NOT NULL CHECK (provider IN ('openai', 'deepseek', 'qwen', 'openai_compatible')),
    base_url TEXT NOT NULL CHECK (base_url ~ '^https://'),
    model_id TEXT NOT NULL CHECK (btrim(model_id) <> ''),
    api_key_ciphertext BYTEA NOT NULL,
    api_key_nonce BYTEA NOT NULL,
    encryption_version TEXT NOT NULL,
    api_key_last_four VARCHAR(4) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'untested' CHECK (status IN ('untested', 'active', 'unhealthy', 'disabled')),
    last_connection_test_status TEXT CHECK (last_connection_test_status IN ('passed', 'failed')),
    last_connection_test_latency_ms INTEGER CHECK (last_connection_test_latency_ms >= 0),
    last_connection_test_error_code TEXT,
    last_connection_tested_at TIMESTAMPTZ,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS llm_model_connection_test (
    id UUID PRIMARY KEY,
    llm_model_config_id UUID NOT NULL REFERENCES llm_model_config(id) ON DELETE RESTRICT,
    checked_by_system_admin_user_id UUID,
    model_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed')),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    error_code TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_model_connection_test_checked
    ON llm_model_connection_test (llm_model_config_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS langgraph_node_llm_binding (
    node_id TEXT PRIMARY KEY,
    llm_model_config_id UUID NOT NULL REFERENCES llm_model_config(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision > 0),
    updated_by_system_admin_user_id UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (node_id IN ('classify_service_stage', 'generate_candidate'))
);

CREATE TABLE IF NOT EXISTS llm_node_binding_revision (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_by_system_admin_user_id UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO llm_node_binding_revision (singleton, revision)
VALUES (TRUE, 0)
ON CONFLICT (singleton) DO NOTHING;
