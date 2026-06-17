ALTER TABLE organization ADD COLUMN IF NOT EXISTS external_organization_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_organization_external_organization_id
    ON organization (external_organization_id)
    WHERE external_organization_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_store_external_lookup
    ON store (organization_id, platform, external_store_id);

ALTER TABLE conversation ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE conversation ADD COLUMN IF NOT EXISTS buyer_ref text;
ALTER TABLE conversation ADD COLUMN IF NOT EXISTS summary jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_tenant_external
    ON conversation (organization_id, store_id, platform, external_conversation_id);

ALTER TABLE message ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE message ADD COLUMN IF NOT EXISTS store_id uuid;
ALTER TABLE message ADD COLUMN IF NOT EXISTS platform text;
ALTER TABLE message ADD COLUMN IF NOT EXISTS sender_type text NOT NULL DEFAULT 'buyer';
ALTER TABLE message ADD COLUMN IF NOT EXISTS content text NOT NULL DEFAULT '';
ALTER TABLE message ADD COLUMN IF NOT EXISTS raw jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE message ADD COLUMN IF NOT EXISTS direction text;
ALTER TABLE message ADD COLUMN IF NOT EXISTS message_type text NOT NULL DEFAULT 'text';
ALTER TABLE message ADD COLUMN IF NOT EXISTS content_redacted text;
ALTER TABLE message ADD COLUMN IF NOT EXISTS raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE message ADD COLUMN IF NOT EXISTS received_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE message ALTER COLUMN sender_type SET DEFAULT 'buyer';
ALTER TABLE message ALTER COLUMN content SET DEFAULT '';
ALTER TABLE message ALTER COLUMN raw SET DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS idx_message_tenant_external
    ON message (organization_id, store_id, platform, external_message_id);

ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS action text NOT NULL DEFAULT 'unknown';
ALTER TABLE decision_record ALTER COLUMN action SET DEFAULT 'unknown';
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS status text;
UPDATE decision_record
SET status = COALESCE(
    status,
    to_jsonb(decision_record)->>'decision_status',
    to_jsonb(decision_record)->>'action',
    'completed'
)
WHERE status IS NULL;
ALTER TABLE decision_record ALTER COLUMN status SET DEFAULT 'completed';

ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS decision_type text;
UPDATE decision_record
SET decision_type = COALESCE(
    decision_type,
    to_jsonb(decision_record)->>'action',
    'unknown'
)
WHERE decision_type IS NULL;
ALTER TABLE decision_record ALTER COLUMN decision_type SET DEFAULT 'unknown';

ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS reasons jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS message_id uuid;

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_record_organization_request_id
    ON decision_record (organization_id, request_id);

CREATE INDEX IF NOT EXISTS idx_decision_record_tenant_status_created
    ON decision_record (organization_id, store_id, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_trace_step_decision_step_order
    ON decision_trace_step (decision_id, step_order);

CREATE INDEX IF NOT EXISTS idx_decision_trace_step_decision_created
    ON decision_trace_step (decision_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_context_snapshot_decision_context_request
    ON context_snapshot (decision_id, context_request_id);

CREATE INDEX IF NOT EXISTS idx_context_snapshot_decision_type
    ON context_snapshot (decision_id, context_type);

ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS store_id uuid;
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS thread_id text NOT NULL DEFAULT '';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS graph_version text NOT NULL DEFAULT 'reply-decision-graph-v1';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS node_name text NOT NULL DEFAULT 'latest';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS decision_status text NOT NULL DEFAULT 'completed';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS state_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS checkpoint_key text;
UPDATE decision_graph_checkpoint
SET checkpoint_key = COALESCE(
    checkpoint_key,
    to_jsonb(decision_graph_checkpoint)->>'node_name',
    'latest-' || id::text
)
WHERE checkpoint_key IS NULL;
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS state jsonb;
UPDATE decision_graph_checkpoint
SET state = COALESCE(
    state,
    to_jsonb(decision_graph_checkpoint)->'state_json',
    '{}'::jsonb
)
WHERE state IS NULL;
ALTER TABLE decision_graph_checkpoint ALTER COLUMN thread_id SET DEFAULT '';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN graph_version SET DEFAULT 'reply-decision-graph-v1';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN node_name SET DEFAULT 'latest';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN decision_status SET DEFAULT 'completed';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN state_json SET DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_graph_checkpoint_decision_key
    ON decision_graph_checkpoint (decision_id, checkpoint_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_action_request_decision_action
    ON action_request (decision_id, action_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_action_result_decision_action_idempotency
    ON action_result (decision_id, action_id, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_action_result_decision_action
    ON action_result (decision_id, action_id);

ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS store_id uuid;
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS decision_id text;
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS human_reply text NOT NULL DEFAULT '';
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS replied_by_ref text;
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS final_reply_redacted text;
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS adopted_suggestion boolean;
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS outcome text NOT NULL DEFAULT 'submitted';
ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS feedback_payload jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE human_reply ALTER COLUMN human_reply SET DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_human_reply_decision_id
    ON human_reply (decision_id);

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

ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS product_id uuid;
ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS source_product_candidate_id uuid;
ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'product';
ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS content text NOT NULL DEFAULT '';
UPDATE knowledge_entry
SET content = COALESCE(NULLIF(content, ''), to_jsonb(knowledge_entry)->>'body', '')
WHERE content = '';
ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS source_type text NOT NULL DEFAULT 'manual';
UPDATE knowledge_entry
SET source_type = COALESCE(source_type, to_jsonb(knowledge_entry)->>'source', 'manual')
WHERE source_type = 'manual';
ALTER TABLE knowledge_entry ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'approved';
UPDATE knowledge_entry
SET status = CASE
    WHEN COALESCE((to_jsonb(knowledge_entry)->>'enabled')::boolean, true) THEN status
    ELSE 'disabled'
END
WHERE to_jsonb(knowledge_entry) ? 'enabled';

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
