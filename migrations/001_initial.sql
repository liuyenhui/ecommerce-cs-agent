CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migration (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS organization (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS store (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    name text NOT NULL,
    platform text NOT NULL,
    external_store_id text,
    status text NOT NULL DEFAULT 'active',
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, platform, external_store_id)
);

CREATE TABLE IF NOT EXISTS platform_account (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    platform text NOT NULL,
    external_account_id text NOT NULL,
    display_name text,
    status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, platform, external_account_id)
);

CREATE TABLE IF NOT EXISTS external_api_token (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid REFERENCES store(id),
    token_hash text NOT NULL,
    name text NOT NULL,
    scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
    status text NOT NULL DEFAULT 'active',
    last_used_at timestamptz,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, token_hash)
);

CREATE TABLE IF NOT EXISTS admin_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    email text NOT NULL,
    password_hash text NOT NULL,
    display_name text NOT NULL,
    role text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, email)
);

CREATE TABLE IF NOT EXISTS admin_session (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    admin_user_id uuid NOT NULL REFERENCES admin_user(id),
    session_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_hash)
);

CREATE TABLE IF NOT EXISTS system_admin_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    display_name text NOT NULL,
    role text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system_admin_session (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    system_admin_user_id uuid NOT NULL REFERENCES system_admin_user(id),
    session_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    platform text NOT NULL,
    external_conversation_id text NOT NULL,
    buyer_ref text,
    status text NOT NULL DEFAULT 'open',
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, platform, external_conversation_id)
);

CREATE TABLE IF NOT EXISTS message (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    conversation_id uuid NOT NULL REFERENCES conversation(id),
    platform text NOT NULL,
    external_message_id text NOT NULL,
    direction text NOT NULL,
    message_type text NOT NULL DEFAULT 'text',
    content_redacted text,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    received_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, platform, external_message_id)
);

CREATE TABLE IF NOT EXISTS decision_record (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id text NOT NULL UNIQUE,
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    conversation_id uuid REFERENCES conversation(id),
    message_id uuid REFERENCES message(id),
    request_id text NOT NULL,
    status text NOT NULL,
    decision_type text NOT NULL,
    risk_level text NOT NULL,
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, request_id)
);

CREATE TABLE IF NOT EXISTS decision_trace_step (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    decision_id text NOT NULL REFERENCES decision_record(decision_id),
    step_name text NOT NULL,
    step_order integer NOT NULL,
    status text NOT NULL,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (decision_id, step_order)
);

CREATE TABLE IF NOT EXISTS context_snapshot (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    decision_id text NOT NULL REFERENCES decision_record(decision_id),
    context_request_id text NOT NULL,
    context_type text NOT NULL,
    source text NOT NULL,
    business_updated_at timestamptz,
    captured_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (decision_id, context_request_id)
);

CREATE TABLE IF NOT EXISTS decision_graph_checkpoint (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    decision_id text NOT NULL REFERENCES decision_record(decision_id),
    checkpoint_key text NOT NULL,
    state jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (decision_id, checkpoint_key)
);

CREATE TABLE IF NOT EXISTS action_request (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    decision_id text NOT NULL REFERENCES decision_record(decision_id),
    action_id text NOT NULL,
    action_type text NOT NULL,
    status text NOT NULL,
    idempotency_key text NOT NULL,
    request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (decision_id, action_id),
    UNIQUE (organization_id, store_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS action_result (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    action_request_id uuid NOT NULL REFERENCES action_request(id),
    decision_id text NOT NULL REFERENCES decision_record(decision_id),
    action_id text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL,
    result_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    received_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (action_request_id, idempotency_key),
    UNIQUE (decision_id, action_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS human_reply (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    decision_id text NOT NULL REFERENCES decision_record(decision_id),
    replied_by_ref text,
    final_reply_redacted text,
    adopted_suggestion boolean,
    outcome text NOT NULL,
    feedback_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (decision_id)
);

CREATE TABLE IF NOT EXISTS product (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    external_product_id text NOT NULL,
    title text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, external_product_id)
);

CREATE TABLE IF NOT EXISTS product_asset (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    product_id uuid NOT NULL REFERENCES product(id),
    asset_type text NOT NULL,
    object_key text NOT NULL,
    source_url text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, object_key)
);

CREATE TABLE IF NOT EXISTS product_asset_markdown (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    product_asset_id uuid NOT NULL REFERENCES product_asset(id),
    markdown text NOT NULL,
    review_status text NOT NULL DEFAULT 'pending',
    generated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (product_asset_id)
);

CREATE TABLE IF NOT EXISTS product_knowledge_candidate (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    product_id uuid REFERENCES product(id),
    source_type text NOT NULL,
    source_ref text,
    candidate_text text NOT NULL,
    review_status text NOT NULL DEFAULT 'pending',
    embedding vector(1536),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS product_price_snapshot (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    product_id uuid NOT NULL REFERENCES product(id),
    currency text NOT NULL,
    price_amount numeric(12, 2) NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL,
    UNIQUE (product_id, captured_at)
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid REFERENCES store(id),
    admin_user_id uuid REFERENCES admin_user(id),
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text,
    diff_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system_admin_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    system_admin_user_id uuid REFERENCES system_admin_user(id),
    organization_id uuid REFERENCES organization(id),
    store_id uuid REFERENCES store(id),
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text,
    diff_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
