"""
Fixed Flask API for follow operations with cache reconciliation
KEY IMPROVEMENTS:
1. Cache keys include tenant_id for multi-tenant isolation
2. follow_status() reconciles Redis with DB on mismatch
3. Atomic follow/unfollow with proper error handling
4. Cache invalidation on state changes
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import time

# Mock implementations for demonstration (in real system: redis, sqlalchemy, etc)
class MockRedis:
    """Mock Redis with simulated delays for testing"""
    def __init__(self, delay_ms: int = 0):
        self.data = {}
        self.delay_ms = delay_ms
    
    def get(self, key: str) -> Optional[str]:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        return self.data.get(key)
    
    def set(self, key: str, value: str, ex: int = None) -> bool:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        self.data[key] = value
        return True
    
    def delete(self, key: str) -> bool:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        self.data.pop(key, None)
        return True


class MockDB:
    """Mock database for testing"""
    def __init__(self):
        self.followers = {}  # (tenant_id, follower_id, followed_id) -> {record}
        self.next_id = 1
    
    def insert_follower(self, tenant_id: int, follower_id: int, followed_id: int) -> Dict:
        """Insert a follower relationship"""
        key = (tenant_id, follower_id, followed_id)
        if key in self.followers and not self.followers[key].get('deleted'):
            raise Exception("IntegrityError: Duplicate key")
        
        record = {
            'id': self.next_id,
            'tenant_id': tenant_id,
            'follower_id': follower_id,
            'followed_id': followed_id,
            'deleted': False,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        self.next_id += 1
        self.followers[key] = record
        return record
    
    def delete_follower(self, tenant_id: int, follower_id: int, followed_id: int) -> bool:
        """Soft-delete a follower relationship"""
        key = (tenant_id, follower_id, followed_id)
        if key not in self.followers:
            return False
        self.followers[key]['deleted'] = True
        self.followers[key]['updated_at'] = datetime.utcnow().isoformat()
        return True
    
    def get_follower(self, tenant_id: int, follower_id: int, followed_id: int) -> Optional[Dict]:
        """Get a follower relationship (active only)"""
        key = (tenant_id, follower_id, followed_id)
        record = self.followers.get(key)
        if record and not record.get('deleted', False):
            return record
        return None
    
    def query_active_followers(self, tenant_id: int, followed_id: int) -> list:
        """Get all active followers of a user"""
        result = []
        for (t_id, f_id, fd_id), record in self.followers.items():
            if t_id == tenant_id and fd_id == followed_id and not record.get('deleted', False):
                result.append(record)
        return result


# Global mock instances
redis_client = MockRedis()
db_client = MockDB()
logger = logging.getLogger(__name__)


def _cache_key(tenant_id: int, follower_id: int, followed_id: int) -> str:
    """Generate cache key with tenant isolation"""
    # KEY FIX: Include tenant_id in Redis key to prevent cross-tenant leakage
    return f"follow_status:{tenant_id}:{follower_id}:{followed_id}"


def _invalidate_cache(tenant_id: int, follower_id: int, followed_id: int) -> None:
    """Invalidate cache entry when relationship changes"""
    key = _cache_key(tenant_id, follower_id, followed_id)
    redis_client.delete(key)
    logger.info(f"Invalidated cache key: {key}")


def follow_status(tenant_id: int, follower_id: int, followed_id: int) -> Dict[str, bool]:
    """
    Get follow status with cache reconciliation
    
    KEY IMPROVEMENTS:
    1. Cache keys include tenant_id
    2. On cache miss: queries DB and populates cache
    3. On cache hit but age mismatch: reconciles with DB
    4. Handles soft-deleted rows
    5. Returns authoritative state from DB
    
    Test Cases Addressed:
    - ui_desync_cache_delay: DB is source of truth, cache is re-checked
    - concurrent_toggle_race: Returns DB state, not stale cache
    - cross_tenant_visibility: tenant_id in key prevents leakage
    - api_returns_stale_after_soft_delete: Checks deleted flag
    - delayed_backend_confirmation: Returns current DB state on retry
    """
    cache_key = _cache_key(tenant_id, follower_id, followed_id)
    
    try:
        # STEP 1: Try cache first
        cached_value = redis_client.get(cache_key)
        
        if cached_value is not None:
            # Cache hit - but verify with DB to detect drift
            cached_following = bool(int(cached_value))
            db_record = db_client.get_follower(tenant_id, follower_id, followed_id)
            db_following = db_record is not None
            
            # KEY FIX: Reconcile if mismatch detected
            if cached_following != db_following:
                logger.warning(
                    f"Cache drift detected for {cache_key}: "
                    f"cache={cached_following} db={db_following}. Fixing cache."
                )
                # Update cache to match DB
                redis_client.set(cache_key, "1" if db_following else "0", ex=300)
                return {"following": db_following}
            
            logger.info(f"Cache hit: {cache_key} = {cached_following}")
            return {"following": cached_following}
        
        # STEP 2: Cache miss - query DB
        logger.info(f"Cache miss: {cache_key}, querying DB")
        db_record = db_client.get_follower(tenant_id, follower_id, followed_id)
        following = db_record is not None
        
        # Populate cache with DB state
        redis_client.set(cache_key, "1" if following else "0", ex=300)
        logger.info(f"Populated cache: {cache_key} = {following}")
        
        return {"following": following}
    
    except Exception as e:
        # Graceful fallback: on Redis error, query DB directly
        logger.error(f"Redis error in follow_status: {e}. Falling back to DB.")
        db_record = db_client.get_follower(tenant_id, follower_id, followed_id)
        return {"following": db_record is not None}


def create_follow(tenant_id: int, follower_id: int, followed_id: int) -> Tuple[Dict, int]:
    """
    Create a follow relationship with atomic transaction
    
    KEY IMPROVEMENTS:
    1. Attempts DB insert first
    2. On success, updates cache
    3. On IntegrityError, checks current state
    4. Proper error codes for client handling
    
    Returns: (response_dict, http_status_code)
    """
    try:
        logger.info(f"Creating follow: tenant={tenant_id}, follower={follower_id}, followed={followed_id}")
        
        # STEP 1: Insert into DB (atomic)
        # This will raise IntegrityError if duplicate exists
        record = db_client.insert_follower(tenant_id, follower_id, followed_id)
        logger.info(f"DB insert successful: {record}")
        
        # STEP 2: Update cache on success
        cache_key = _cache_key(tenant_id, follower_id, followed_id)
        redis_client.set(cache_key, "1", ex=300)
        logger.info(f"Cache updated: {cache_key} = 1")
        
        return {
            "status": "success",
            "following": True,
            "message": "Now following",
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating follow: {error_msg}")
        
        # Check if it's a duplicate entry
        if "IntegrityError" in error_msg or "Duplicate" in error_msg:
            # Already following - verify cache state and return 200
            logger.info("Duplicate entry detected, verifying cache")
            following = follow_status(tenant_id, follower_id, followed_id)
            return {
                "status": "already_following",
                "following": True,
                "message": "Already following",
                "timestamp": datetime.utcnow().isoformat()
            }, 200
        
        # Generic server error
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }, 500


def delete_follow(tenant_id: int, follower_id: int, followed_id: int) -> Tuple[Dict, int]:
    """
    Delete a follow relationship (soft-delete)
    
    KEY IMPROVEMENTS:
    1. Uses soft-delete (sets deleted=True)
    2. Invalidates cache on delete
    3. Preserves audit trail
    4. Idempotent: calling twice returns 200 both times
    
    Returns: (response_dict, http_status_code)
    """
    try:
        logger.info(f"Deleting follow: tenant={tenant_id}, follower={follower_id}, followed={followed_id}")
        
        # STEP 1: Soft-delete in DB
        success = db_client.delete_follower(tenant_id, follower_id, followed_id)
        
        if not success:
            logger.warning(f"Follower relationship not found for deletion")
            return {
                "status": "not_found",
                "following": False,
                "message": "Not following",
                "timestamp": datetime.utcnow().isoformat()
            }, 200
        
        # STEP 2: Invalidate cache
        _invalidate_cache(tenant_id, follower_id, followed_id)
        logger.info("Cache invalidated")
        
        return {
            "status": "success",
            "following": False,
            "message": "Unfollowed",
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    
    except Exception as e:
        logger.error(f"Error deleting follow: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }, 500


def get_follower_count(tenant_id: int, followed_id: int) -> Dict:
    """Get follower count for a user (uses DB, not cache, for accuracy)"""
    try:
        followers = db_client.query_active_followers(tenant_id, followed_id)
        count = len(followers)
        logger.info(f"Follower count for user {followed_id} in tenant {tenant_id}: {count}")
        return {"follower_count": count, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Error getting follower count: {e}")
        return {"error": str(e)}, 500


# API IMPROVEMENTS SUMMARY:
# 1. Cache key includes tenant_id: prevents cross-tenant data leakage
# 2. follow_status() reconciles on mismatch: fixes ui_desync_cache_delay
# 3. Soft-delete with deleted flag: fixes api_returns_stale_after_soft_delete
# 4. DB insert with IntegrityError: fixes delayed_backend_confirmation via idempotency
# 5. Cache invalidation on delete: ensures consistency
# 6. Graceful Redis fallback: system works even if Redis fails
# 7. Logging at every step: enables debugging
