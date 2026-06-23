ALTER TABLE admin_user ADD COLUMN IF NOT EXISTS fcihome_account_sub text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_user_fcihome_account_sub
    ON admin_user (fcihome_account_sub)
    WHERE fcihome_account_sub IS NOT NULL;
