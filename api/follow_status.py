# Simplified Flask + SQLAlchemy + Redis example for follow_status with tenant-aware keys
# This file is a self-contained module suitable for unit testing and demonstration.

from dataclasses import dataclass
import threading
import time
from typing import Optional

# We'll use the redis mock in tests; import at runtime to allow swapping
try:
    from mocks.redis_mock import RedisMock
except Exception:
    RedisMock = None

# Simulated DB (in-memory) to avoid external dependencies for tests
@dataclass
class FollowRow:
    tenant_id: int
    follower_id: int
    followed_id: int
    deleted: bool = False

class InMemoryDB:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = []  # list of FollowRow

    def insert_follow(self, tenant_id: int, follower_id: int, followed_id: int):
        with self.lock:
            # enforce composite unique constraint
            for r in self.rows:
                if r.tenant_id == tenant_id and r.follower_id == follower_id and r.followed_id == followed_id and not r.deleted:
                    raise ValueError('IntegrityError: duplicate follow')
            self.rows.append(FollowRow(tenant_id, follower_id, followed_id))

    def remove_follow(self, tenant_id: int, follower_id: int, followed_id: int):
        with self.lock:
            for r in self.rows:
                if r.tenant_id == tenant_id and r.follower_id == follower_id and r.followed_id == followed_id and not r.deleted:
                    r.deleted = True
                    return
            # idempotent

    def is_following(self, tenant_id: int, follower_id: int, followed_id: int) -> bool:
        with self.lock:
            for r in self.rows:
                if r.tenant_id == tenant_id and r.follower_id == follower_id and r.followed_id == followed_id and not r.deleted:
                    return True
            return False

# Simple Redlock-like lock using redis mock's setnx simulation or threading.Lock fallback
class DistributedLock:
    def __init__(self, redis, key):
        self.redis = redis
        self.key = key
        self.acquired = False

    def acquire(self, timeout_ms=1000):
        # best-effort: try setnx with expiry
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            ok = self.redis.setnx(self.key, '1', ex_ms=timeout_ms)
            if ok:
                self.acquired = True
                return True
            time.sleep(0.01)
        return False

    def release(self):
        if self.acquired:
            try:
                self.redis.delete(self.key)
            except Exception:
                pass
            self.acquired = False

# Main service
class FollowService:
    def __init__(self, db: InMemoryDB, redis_client=None):
        self.db = db
        self.redis = redis_client or (RedisMock() if RedisMock else None)

    def _make_key(self, tenant_id: int, follower_id: int, followed_id: int) -> str:
        # tenant-aware key
        return f"follow_status:{tenant_id}:{follower_id}:{followed_id}"

    def follow(self, tenant_id: int, follower_id: int, followed_id: int) -> bool:
        # use distributed lock per relationship to avoid race
        key_lock = f"lock:follow:{tenant_id}:{follower_id}:{followed_id}"
        lock = DistributedLock(self.redis, key_lock)
        if not lock.acquire(timeout_ms=2000):
            raise RuntimeError('Could not acquire lock')
        try:
            # transaction-safe DB write
            try:
                self.db.insert_follow(tenant_id, follower_id, followed_id)
            except ValueError as e:
                # duplicate - treat as success
                pass
            # write-through cache
            cache_key = self._make_key(tenant_id, follower_id, followed_id)
            # set with a reasonable TTL
            self.redis.set(cache_key, '1', ex=60)
            # publish invalidation so other subscribers update
            self.redis.publish('follow_invalidation', cache_key)
            return True
        finally:
            lock.release()

    def unfollow(self, tenant_id: int, follower_id: int, followed_id: int) -> bool:
        key_lock = f"lock:follow:{tenant_id}:{follower_id}:{followed_id}"
        lock = DistributedLock(self.redis, key_lock)
        if not lock.acquire(timeout_ms=2000):
            raise RuntimeError('Could not acquire lock')
        try:
            self.db.remove_follow(tenant_id, follower_id, followed_id)
            cache_key = self._make_key(tenant_id, follower_id, followed_id)
            self.redis.set(cache_key, '0', ex=60)
            self.redis.publish('follow_invalidation', cache_key)
            return True
        finally:
            lock.release()

    def follow_status(self, tenant_id: int, follower_id: int, followed_id: int) -> bool:
        cache_key = self._make_key(tenant_id, follower_id, followed_id)
        cached = self.redis.get(cache_key)
        if cached is not None:
            # cache hit: but verify type and handle drift
            try:
                val = int(cached)
                # If cache says not-following (0) we can trust it for performance.
                if val == 0:
                    return False
                # If cache says following (1), verify against DB to avoid soft-delete/drift issues
                is_following_db = self.db.is_following(tenant_id, follower_id, followed_id)
                if is_following_db:
                    return True
                # DB disagrees: reconcile cache and return correct value
                self.redis.set(cache_key, '0', ex=60)
                return False
            except Exception:
                # fallthrough to DB verification
                pass
        # Cache miss or invalid: check DB and reconcile cache synchronously (read-through)
        is_following = self.db.is_following(tenant_id, follower_id, followed_id)
        self.redis.set(cache_key, '1' if is_following else '0', ex=60)
        return is_following

# Helper runner for tests
def create_test_service(redis_client=None):
    db = InMemoryDB()
    svc = FollowService(db, redis_client=redis_client)
    return svc, db
