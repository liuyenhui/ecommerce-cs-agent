ALTER TABLE organization ADD COLUMN IF NOT EXISTS external_organization_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_external_organization_id
    ON organization (external_organization_id)
    WHERE external_organization_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_store_external_lookup
    ON store (organization_id, platform, external_store_id);

CREATE INDEX IF NOT EXISTS idx_decision_record_tenant_status_created
    ON decision_record (organization_id, store_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_decision_trace_step_decision_created
    ON decision_trace_step (decision_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_context_snapshot_decision_type
    ON context_snapshot (decision_id, context_type);

CREATE INDEX IF NOT EXISTS idx_action_result_decision_action
    ON action_result (decision_id, action_id);

ALTER TABLE product ADD COLUMN IF NOT EXISTS public_product_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_public_product_id
    ON product (public_product_id)
    WHERE public_product_id IS NOT NULL;

ALTER TABLE product_knowledge_candidate ADD COLUMN IF NOT EXISTS public_candidate_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_knowledge_candidate_public_id
    ON product_knowledge_candidate (public_candidate_id)
    WHERE public_candidate_id IS NOT NULL;

ALTER TABLE product_asset ADD COLUMN IF NOT EXISTS public_asset_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_asset_public_asset_id
    ON product_asset (public_asset_id)
    WHERE public_asset_id IS NOT NULL;

ALTER TABLE product_price_snapshot ADD COLUMN IF NOT EXISTS public_price_snapshot_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_price_snapshot_public_id
    ON product_price_snapshot (public_price_snapshot_id)
    WHERE public_price_snapshot_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS knowledge_entry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    product_id uuid REFERENCES product(id),
    source_product_candidate_id uuid REFERENCES product_knowledge_candidate(id),
    scope text NOT NULL DEFAULT 'product',
    title text NOT NULL DEFAULT '',
    content text NOT NULL,
    source_type text NOT NULL,
    tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'approved',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, store_id, source_product_candidate_id)
);

CREATE TABLE IF NOT EXISTS knowledge_embedding (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid NOT NULL REFERENCES store(id),
    knowledge_entry_id uuid NOT NULL REFERENCES knowledge_entry(id),
    embedding vector(1536),
    embedding_model text NOT NULL,
    chunk_text text NOT NULL,
    chunk_index integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (knowledge_entry_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_entry_store_status_created
    ON knowledge_entry (organization_id, store_id, status, created_at DESC);
