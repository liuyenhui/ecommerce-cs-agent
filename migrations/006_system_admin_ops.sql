ALTER TABLE system_admin_user ADD COLUMN IF NOT EXISTS roles text[] NOT NULL DEFAULT ARRAY[]::text[];

UPDATE system_admin_user
SET roles = ARRAY[role]
WHERE cardinality(roles) = 0
  AND role IS NOT NULL;

ALTER TABLE system_admin_audit_log ADD COLUMN IF NOT EXISTS idempotency_key text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_admin_audit_action_idempotency
    ON system_admin_audit_log (action, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_store_id_organization_id
    ON store (id, organization_id);

CREATE TABLE IF NOT EXISTS background_task (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id text NOT NULL UNIQUE,
    task_type text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    organization_id uuid NOT NULL REFERENCES organization(id),
    store_id uuid REFERENCES store(id),
    input_ref text,
    output_ref text,
    error_summary text,
    retry_count integer NOT NULL DEFAULT 0,
    retryable boolean NOT NULL DEFAULT true,
    idempotency_key text,
    next_retry_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_background_task_tenant_status_created
    ON background_task (organization_id, store_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_background_task_type_status_created
    ON background_task (task_type, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_background_task_idempotency_key
    ON background_task (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_background_task_store_tenant'
    ) THEN
        ALTER TABLE background_task
            ADD CONSTRAINT fk_background_task_store_tenant
            FOREIGN KEY (store_id, organization_id)
            REFERENCES store (id, organization_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_system_admin_audit_tenant_created
    ON system_admin_audit_log (organization_id, store_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_system_admin_audit_actor_created
    ON system_admin_audit_log (system_admin_user_id, created_at DESC);
