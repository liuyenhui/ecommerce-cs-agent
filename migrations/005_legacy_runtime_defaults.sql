ALTER TABLE message ADD COLUMN IF NOT EXISTS sender_type text NOT NULL DEFAULT 'buyer';
ALTER TABLE message ADD COLUMN IF NOT EXISTS content text NOT NULL DEFAULT '';
ALTER TABLE message ADD COLUMN IF NOT EXISTS raw jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE message ALTER COLUMN sender_type SET DEFAULT 'buyer';
ALTER TABLE message ALTER COLUMN content SET DEFAULT '';
ALTER TABLE message ALTER COLUMN raw SET DEFAULT '{}'::jsonb;

ALTER TABLE decision_record ADD COLUMN IF NOT EXISTS action text NOT NULL DEFAULT 'unknown';
ALTER TABLE decision_record ALTER COLUMN action SET DEFAULT 'unknown';

ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS thread_id text NOT NULL DEFAULT '';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS graph_version text NOT NULL DEFAULT 'reply-decision-graph-v1';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS node_name text NOT NULL DEFAULT 'latest';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS decision_status text NOT NULL DEFAULT 'completed';
ALTER TABLE decision_graph_checkpoint ADD COLUMN IF NOT EXISTS state_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE decision_graph_checkpoint ALTER COLUMN thread_id SET DEFAULT '';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN graph_version SET DEFAULT 'reply-decision-graph-v1';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN node_name SET DEFAULT 'latest';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN decision_status SET DEFAULT 'completed';
ALTER TABLE decision_graph_checkpoint ALTER COLUMN state_json SET DEFAULT '{}'::jsonb;

ALTER TABLE human_reply ADD COLUMN IF NOT EXISTS human_reply text NOT NULL DEFAULT '';
ALTER TABLE human_reply ALTER COLUMN human_reply SET DEFAULT '';
