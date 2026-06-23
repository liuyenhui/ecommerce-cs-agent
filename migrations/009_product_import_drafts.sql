CREATE TABLE IF NOT EXISTS product_import_draft (
    draft_id text PRIMARY KEY,
    organization_id text NOT NULL,
    store_id text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    idempotency_key text NOT NULL,
    file_name text NOT NULL,
    mime_type text NOT NULL DEFAULT 'application/octet-stream',
    object_key text NOT NULL,
    object_hash text NOT NULL,
    size_bytes bigint,
    storage_status text NOT NULL DEFAULT 'referenced',
    analysis_status text NOT NULL DEFAULT 'fallback',
    analysis_model text,
    analysis_error text,
    draft_product jsonb NOT NULL DEFAULT '{}'::jsonb,
    markdown_text text NOT NULL DEFAULT '',
    source_map jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz,
    confirm_idempotency_key text,
    confirm_response jsonb,
    UNIQUE (organization_id, store_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_product_import_draft_store_updated
    ON product_import_draft (organization_id, store_id, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_import_draft_confirm_idempotency
    ON product_import_draft (organization_id, store_id, confirm_idempotency_key)
    WHERE confirm_idempotency_key IS NOT NULL;
