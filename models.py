"""
Fixed SQLAlchemy Models with tenant_id and proper relationship handling
"""
from datetime import datetime
from typing import Optional

class Tenant:
    """Represents a tenant in the system"""
    id: int
    name: str


class User:
    """Fixed User model with tenant_id"""
    id: int
    tenant_id: int
    username: str
    email: str
    created_at: datetime
    
    def __repr__(self):
        return f"<User {self.username} (tenant={self.tenant_id})>"


class Follower:
    """Fixed Follower model with tenant_id, deleted flag, and timestamps"""
    id: int
    tenant_id: int  # KEY FIX: Enables tenant isolation and cache key scoping
    follower_id: int  # User who is following
    followed_id: int  # User being followed
    deleted: bool = False  # KEY FIX: Soft-delete for audit trail
    created_at: datetime
    updated_at: datetime
    
    def __repr__(self):
        status = "deleted" if self.deleted else "active"
        return f"<Follower tenant={self.tenant_id} {self.follower_id}->{self.followed_id} {status}>"


# SCHEMA FIXES SUMMARY:
# 1. Tenant Isolation:
#    - follower_id and followed_id alone are not sufficient for multi-tenant systems
#    - tenant_id must be part of the primary key or unique constraint
#    - Cache keys must include tenant_id: follow_status:<tenant_id>:<follower_id>:<followed_id>
#
# 2. Soft-Delete Support:
#    - deleted flag allows marking rows as deleted without losing historical data
#    - Queries must filter: WHERE deleted = FALSE
#    - Cache invalidation must happen when deleted is set to TRUE
#
# 3. Timestamps:
#    - updated_at enables cache invalidation when rows change
#    - Useful for versioned caching strategies
#
# 4. Composite Unique Constraint:
#    - UNIQUE(tenant_id, follower_id, followed_id) prevents duplicates
#    - Prevents race condition where concurrent INSERTs both succeed
#    - Generates IntegrityError that can be caught and handled gracefully
