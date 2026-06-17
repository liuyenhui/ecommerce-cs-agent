CREATE TABLE IF NOT EXISTS admin_membership (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    admin_user_id uuid NOT NULL REFERENCES admin_user(id),
    roles text[] NOT NULL DEFAULT ARRAY[]::text[],
    store_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, admin_user_id)
);

CREATE TABLE IF NOT EXISTS admin_invitation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organization(id),
    email text NOT NULL,
    display_name text,
    roles text[] NOT NULL DEFAULT ARRAY[]::text[],
    store_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    status text NOT NULL DEFAULT 'pending',
    token_hash text,
    idempotency_key text,
    invited_by_admin_user_id uuid REFERENCES admin_user(id),
    accepted_at timestamptz,
    revoked_at timestamptz,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, email, status),
    UNIQUE (organization_id, idempotency_key)
);

ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS active_store_id uuid REFERENCES store(id);
ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;
ALTER TABLE admin_session ADD COLUMN IF NOT EXISTS request_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_admin_session_hash_active
    ON admin_session (session_hash, expires_at)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_admin_membership_user_org
    ON admin_membership (admin_user_id, organization_id, status);

CREATE INDEX IF NOT EXISTS idx_admin_invitation_org_status_created
    ON admin_invitation (organization_id, status, created_at DESC);
