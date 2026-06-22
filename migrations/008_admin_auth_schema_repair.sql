-- Repair legacy Admin auth schema drift from pre-membership dev deployments.

ALTER TABLE admin_user ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE admin_user ADD COLUMN IF NOT EXISTS display_name text;
ALTER TABLE admin_user ADD COLUMN IF NOT EXISTS status text;
ALTER TABLE admin_user ADD COLUMN IF NOT EXISTS updated_at timestamptz;

UPDATE admin_user
SET organization_id = (
    SELECT id
    FROM organization
    ORDER BY created_at ASC
    LIMIT 1
)
WHERE organization_id IS NULL
  AND EXISTS (SELECT 1 FROM organization);

UPDATE admin_user
SET display_name = COALESCE(display_name, 'Customer Admin')
WHERE display_name IS NULL;

UPDATE admin_user
SET status = COALESCE(status, 'active')
WHERE status IS NULL;

UPDATE admin_user
SET updated_at = COALESCE(updated_at, now())
WHERE updated_at IS NULL;

ALTER TABLE admin_user ALTER COLUMN display_name SET DEFAULT 'Customer Admin';
ALTER TABLE admin_user ALTER COLUMN status SET DEFAULT 'active';
ALTER TABLE admin_user ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE admin_user ALTER COLUMN display_name SET NOT NULL;
ALTER TABLE admin_user ALTER COLUMN status SET NOT NULL;
ALTER TABLE admin_user ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM admin_user WHERE organization_id IS NULL
    ) THEN
        ALTER TABLE admin_user ALTER COLUMN organization_id SET NOT NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'admin_user_organization_id_fkey'
    ) THEN
        ALTER TABLE admin_user
            ADD CONSTRAINT admin_user_organization_id_fkey
            FOREIGN KEY (organization_id)
            REFERENCES organization(id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_user_organization_email
    ON admin_user (organization_id, email);

ALTER TABLE admin_user DROP CONSTRAINT IF EXISTS admin_user_email_key;

ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS admin_user_id uuid;
ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS active_store_id uuid;
ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;
ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS request_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE system_admin_user ADD COLUMN IF NOT EXISTS roles text[] NOT NULL DEFAULT ARRAY[]::text[];

UPDATE system_admin_user
SET roles = ARRAY[role]
WHERE cardinality(roles) = 0
  AND role IS NOT NULL;
