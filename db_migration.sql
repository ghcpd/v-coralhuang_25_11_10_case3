-- Add tenant_id to followers
ALTER TABLE followers ADD COLUMN tenant_id INTEGER;

-- If you have a default tenant mapping, set it here. Example: set tenant_id=1 for existing rows.
-- UPDATE followers SET tenant_id = 1 WHERE tenant_id IS NULL;

-- Make non-nullable if all rows have tenant_id filled.
-- ALTER TABLE followers ALTER COLUMN tenant_id SET NOT NULL;

-- Add composite uniqueness constraint
ALTER TABLE followers ADD CONSTRAINT uix_tenant_follower_followed UNIQUE (tenant_id, follower_id, followed_id);

-- To exclude soft-deleted rows, ensure your queries check deleted boolean, e.g.: WHERE deleted = false
