-- FIXED SCHEMA: Followers table with tenant_id, deleted column, and composite unique constraint
-- This addresses issues: cross-tenant leakage, soft-delete cache staleness, and race conditions

CREATE TABLE followers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    follower_id INTEGER NOT NULL,
    followed_id INTEGER NOT NULL,
    deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Composite unique constraint: prevents duplicate follows within same tenant
    CONSTRAINT uq_followers_tenant_user UNIQUE(tenant_id, follower_id, followed_id),
    
    -- Composite index for efficient queries by tenant
    CONSTRAINT fk_followers_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- Index for efficient queries by follower and tenant
CREATE INDEX idx_followers_tenant_follower ON followers(tenant_id, follower_id) WHERE deleted = FALSE;

-- Index for efficient queries by followed and tenant (for follower count)
CREATE INDEX idx_followers_tenant_followed ON followers(tenant_id, followed_id) WHERE deleted = FALSE;

-- ROOT CAUSES FIXED:
-- 1. Added tenant_id column: Prevents cross-tenant data leakage
-- 2. Added deleted column: Enables soft-delete tracking without losing historical data
-- 3. Added UNIQUE(tenant_id, follower_id, followed_id): Prevents duplicate entries and enables DB-level constraint
-- 4. Added composite indexes: Optimizes both follower list and follower count queries
-- 5. Timestamp tracking: Enables cache invalidation based on update time
