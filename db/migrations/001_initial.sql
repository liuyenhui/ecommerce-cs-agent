CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS decision_record (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id text NOT NULL UNIQUE,
  request_id text NOT NULL UNIQUE,
  organization_id text,
  store_id text,
  platform text,
  decision_status text NOT NULL,
  action text NOT NULL,
  request_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  response_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  trace_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS organization_id text;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS store_id text;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS platform text;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS decision_status text NOT NULL DEFAULT 'pending';
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS request_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS response_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS trace_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS decision_record_org_store_created_idx
  ON decision_record (organization_id, store_id, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_graph_checkpoint (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id text NOT NULL REFERENCES decision_record(decision_id) ON DELETE CASCADE,
  thread_id text NOT NULL,
  graph_version text NOT NULL,
  node_name text NOT NULL,
  decision_status text NOT NULL,
  state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  resume_token text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS decision_graph_checkpoint_decision_idx
  ON decision_graph_checkpoint (decision_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_type text NOT NULL,
  actor_id text,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  summary text NOT NULL,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_log_resource_idx
  ON audit_log (resource_type, resource_id, created_at DESC);

CREATE TABLE IF NOT EXISTS admin_user (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  role text NOT NULL DEFAULT 'owner',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
