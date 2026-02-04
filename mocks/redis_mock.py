"""
Mock Redis implementation with simulation of delays, failures, and TTL drift
Useful for testing cache consistency under adverse conditions
"""

import time
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class MockRedisWithDelaySimulation:
    """
    Enhanced mock Redis that simulates:
    - Artificial delays (network latency)
    - TTL expiration (cache staleness)
    - Replica lag (master-slave consistency)
    - Random failures (connection errors)
    """
    
    def __init__(self, default_delay_ms: int = 0, replica_lag_ms: int = 0):
        """
        Initialize mock Redis
        
        Args:
            default_delay_ms: simulated network delay for all operations
            replica_lag_ms: simulated master-slave replication lag
        """
        self.data = {}  # key -> {'value': str, 'expires_at': datetime}
        self.default_delay_ms = default_delay_ms
        self.replica_lag_ms = replica_lag_ms
        self.lock = threading.Lock()
        self.operation_count = 0
        self.failure_rate = 0.0  # Fraction of operations that fail (0.0 to 1.0)
        self.failed_operations = []
        self.success_operations = []
    
    def _apply_delay(self, delay_ms: int):
        """Simulate network latency"""
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
    
    def _check_ttl(self, key: str) -> bool:
        """Check if key has expired"""
        if key not in self.data:
            return False
        
        expires_at = self.data[key].get('expires_at')
        if expires_at and datetime.utcnow() >= expires_at:
            del self.data[key]
            return False
        return True
    
    def set(self, key: str, value: str, ex: Optional[int] = None, delay_ms: Optional[int] = None) -> bool:
        """
        Set a key with optional TTL
        
        Args:
            key: cache key
            value: string value
            ex: expiration time in seconds
            delay_ms: optional override of default delay
        
        Returns: True if successful, False on failure
        """
        delay = delay_ms if delay_ms is not None else self.default_delay_ms
        
        with self.lock:
            self.operation_count += 1
            
            # Simulate random failures
            if self._should_fail():
                self.failed_operations.append(('SET', key, value))
                return False
            
            self._apply_delay(delay)
            
            expires_at = None
            if ex is not None:
                expires_at = datetime.utcnow() + timedelta(seconds=ex)
            
            self.data[key] = {
                'value': value,
                'expires_at': expires_at,
                'set_at': datetime.utcnow()
            }
            
            self.success_operations.append(('SET', key, value))
            return True
    
    def get(self, key: str, delay_ms: Optional[int] = None) -> Optional[str]:
        """
        Get a key value
        
        Args:
            key: cache key
            delay_ms: optional override of default delay
        
        Returns: value if found and not expired, None otherwise
        """
        delay = delay_ms if delay_ms is not None else self.default_delay_ms
        
        with self.lock:
            self.operation_count += 1
            
            # Simulate random failures
            if self._should_fail():
                self.failed_operations.append(('GET', key, None))
                return None
            
            # Simulate replica lag: return stale data if replica_lag_ms > 0
            if self.replica_lag_ms > 0:
                time.sleep(self.replica_lag_ms / 1000.0)
            
            self._apply_delay(delay)
            
            # Check TTL
            if not self._check_ttl(key):
                self.failed_operations.append(('GET', key, 'EXPIRED'))
                return None
            
            if key not in self.data:
                self.failed_operations.append(('GET', key, 'MISS'))
                return None
            
            value = self.data[key]['value']
            self.success_operations.append(('GET', key, value))
            return value
    
    def delete(self, key: str, delay_ms: Optional[int] = None) -> bool:
        """
        Delete a key
        
        Args:
            key: cache key
            delay_ms: optional override of default delay
        
        Returns: True if key existed, False otherwise
        """
        delay = delay_ms if delay_ms is not None else self.default_delay_ms
        
        with self.lock:
            self.operation_count += 1
            
            # Simulate random failures
            if self._should_fail():
                self.failed_operations.append(('DELETE', key, None))
                return False
            
            self._apply_delay(delay)
            
            if key in self.data:
                del self.data[key]
                self.success_operations.append(('DELETE', key, None))
                return True
            
            self.failed_operations.append(('DELETE', key, 'NOT_FOUND'))
            return False
    
    def _should_fail(self) -> bool:
        """Decide if operation should fail based on failure_rate"""
        if self.failure_rate <= 0:
            return False
        import random
        return random.random() < self.failure_rate
    
    def flush(self):
        """Clear all data"""
        with self.lock:
            self.data.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get operation statistics"""
        return {
            'total_operations': self.operation_count,
            'success_count': len(self.success_operations),
            'failed_count': len(self.failed_operations),
            'current_keys': len(self.data),
            'success_rate': len(self.success_operations) / max(1, self.operation_count),
            'failed_operations': self.failed_operations[-10:],  # Last 10 failures
            'data_snapshot': {k: v['value'] for k, v in list(self.data.items())[:5]}
        }


class DistributedLockSimulator:
    """
    Simulates Redis SETEX-based distributed lock for preventing race conditions
    In production, use redlock-py or similar
    """
    
    def __init__(self, redis_client: MockRedisWithDelaySimulation):
        self.redis = redis_client
        self.locks = {}
    
    def acquire_lock(self, lock_key: str, owner_id: str, ttl_seconds: int = 5) -> bool:
        """
        Attempt to acquire a lock
        
        Args:
            lock_key: key to lock
            owner_id: unique owner identifier
            ttl_seconds: lock time-to-live
        
        Returns: True if lock acquired, False if already locked
        """
        # In real Redis: SET key owner_id NX EX ttl_seconds
        lock_value = f"{owner_id}:{time.time()}"
        
        # Simplified simulation: check if locked
        if lock_key in self.locks:
            lock_data = self.locks[lock_key]
            if datetime.utcnow() < lock_data['expires_at']:
                return False  # Still locked
        
        # Acquire lock
        self.locks[lock_key] = {
            'owner': owner_id,
            'expires_at': datetime.utcnow() + timedelta(seconds=ttl_seconds)
        }
        return True
    
    def release_lock(self, lock_key: str, owner_id: str) -> bool:
        """
        Release a lock (only if owned by owner_id)
        
        Args:
            lock_key: key to unlock
            owner_id: owner identifier that acquired the lock
        
        Returns: True if released, False if not owned by owner_id
        """
        if lock_key in self.locks:
            if self.locks[lock_key]['owner'] == owner_id:
                del self.locks[lock_key]
                return True
        return False
    
    def is_locked(self, lock_key: str) -> bool:
        """Check if key is locked"""
        if lock_key not in self.locks:
            return False
        
        if datetime.utcnow() >= self.locks[lock_key]['expires_at']:
            del self.locks[lock_key]
            return False
        
        return True


class CacheTestHelper:
    """Utility class for cache testing scenarios"""
    
    @staticmethod
    def simulate_cache_delay_scenario(redis: MockRedisWithDelaySimulation, delay_ms: int = 2000):
        """Simulate cache write delay (test case: ui_desync_cache_delay)"""
        redis.default_delay_ms = delay_ms
        return redis
    
    @staticmethod
    def simulate_replica_lag_scenario(redis: MockRedisWithDelaySimulation, lag_ms: int = 500):
        """Simulate master-slave replica lag (test case: concurrent_toggle_race)"""
        redis.replica_lag_ms = lag_ms
        return redis
    
    @staticmethod
    def simulate_failure_scenario(redis: MockRedisWithDelaySimulation, failure_rate: float = 0.3):
        """Simulate random Redis failures (fallback to DB)"""
        redis.failure_rate = failure_rate
        return redis
    
    @staticmethod
    def create_scenario_redis(scenario: str) -> MockRedisWithDelaySimulation:
        """Create Redis instance pre-configured for a test scenario"""
        if scenario == "ui_desync_cache_delay":
            return MockRedisWithDelaySimulation(default_delay_ms=2000)
        elif scenario == "concurrent_toggle_race":
            return MockRedisWithDelaySimulation(replica_lag_ms=500)
        elif scenario == "cross_tenant_visibility":
            return MockRedisWithDelaySimulation()  # Regular Redis, but we'll check keys
        elif scenario == "api_returns_stale_after_soft_delete":
            return MockRedisWithDelaySimulation()
        elif scenario == "delayed_backend_confirmation":
            return MockRedisWithDelaySimulation()
        else:
            return MockRedisWithDelaySimulation()


# MOCK SYSTEMS SUMMARY:
# 1. MockRedisWithDelaySimulation: Simulates network delays, replica lag, TTL expiration, random failures
# 2. DistributedLockSimulator: Simple distributed lock for atomic operations
# 3. CacheTestHelper: Utility to set up various test scenarios
#
# These enable comprehensive testing of:
# - Cache delay scenarios (redis write lag)
# - Replica lag (master-slave consistency)
# - Failure fallback (API gracefully uses DB when Redis unavailable)
# - Race conditions (rapid concurrent operations)
# - TTL expiration (cache staleness)
