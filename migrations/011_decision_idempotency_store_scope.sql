-- request_id idempotency belongs to one tenant store, matching the service key
-- (organization_id, store_id, request_id). The former organization-only
-- constraint is stricter, so existing rows cannot conflict under the new key.
ALTER TABLE decision_record
    DROP CONSTRAINT IF EXISTS decision_record_organization_id_request_id_key;

DROP INDEX IF EXISTS idx_decision_record_organization_request_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_record_organization_store_request_id
    ON decision_record (organization_id, store_id, request_id);
