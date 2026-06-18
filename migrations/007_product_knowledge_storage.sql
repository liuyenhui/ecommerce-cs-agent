-- Stage 3 product knowledge loop storage alignment.
-- Keeps existing product data intact while adding explicit object metadata and lookup indexes.

ALTER TABLE product_asset ADD COLUMN IF NOT EXISTS object_hash text;
ALTER TABLE product_asset ADD COLUMN IF NOT EXISTS mime_type text NOT NULL DEFAULT 'application/octet-stream';
ALTER TABLE product_asset ADD COLUMN IF NOT EXISTS size_bytes bigint;
ALTER TABLE product_asset ADD COLUMN IF NOT EXISTS storage_status text NOT NULL DEFAULT 'referenced';

UPDATE product_asset
SET object_hash = COALESCE(object_hash, metadata->>'file_hash')
WHERE object_hash IS NULL;

CREATE INDEX IF NOT EXISTS idx_product_asset_storage_status_created
    ON product_asset (organization_id, store_id, storage_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_product_knowledge_candidate_review_status
    ON product_knowledge_candidate (organization_id, store_id, review_status, created_at DESC);
