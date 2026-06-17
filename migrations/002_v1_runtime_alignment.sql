CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE schema_migration ADD COLUMN IF NOT EXISTS checksum text;

CREATE TABLE IF NOT EXISTS app_decision_state (
    decision_id text PRIMARY KEY,
    organization_id text NOT NULL,
    store_id text NOT NULL,
    request_id text NOT NULL,
    request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    state_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_app_decision_state_tenant_store_created
    ON app_decision_state (organization_id, store_id, created_at DESC);

CREATE TABLE IF NOT EXISTS app_product (
    product_id text PRIMARY KEY,
    organization_id text NOT NULL,
    store_id text NOT NULL,
    external_product_id text NOT NULL,
    title text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active',
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, external_product_id)
);

CREATE TABLE IF NOT EXISTS app_knowledge_candidate (
    candidate_id text PRIMARY KEY,
    organization_id text NOT NULL,
    store_id text NOT NULL,
    product_id text REFERENCES app_product(product_id) ON DELETE SET NULL,
    candidate_text text NOT NULL,
    review_status text NOT NULL DEFAULT 'pending',
    source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz
);

CREATE TABLE IF NOT EXISTS app_audit_log (
    audit_log_id text PRIMARY KEY,
    scope text NOT NULL,
    organization_id text,
    store_id text,
    actor_id text,
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text,
    diff_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_audit_log_scope_created
    ON app_audit_log (scope, created_at DESC);
