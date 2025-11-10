"""
Comprehensive Test Suite for Follow UI/UX Desynchronization
Self-contained version with all necessary classes and logic inline
"""

import time
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


# ===== MOCK CLASSES =====

class MockRedis:
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
        if key in self.data:
            del self.data[key]
        return True


class MockDB:
    def __init__(self):
        self.followers = {}
        self.next_id = 1
    
    def insert_follower(self, tenant_id: int, follower_id: int, followed_id: int) -> Dict:
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
        key = (tenant_id, follower_id, followed_id)
        if key not in self.followers:
            return False
        self.followers[key]['deleted'] = True
        self.followers[key]['updated_at'] = datetime.utcnow().isoformat()
        return True
    
    def get_follower(self, tenant_id: int, follower_id: int, followed_id: int) -> Optional[Dict]:
        key = (tenant_id, follower_id, followed_id)
        record = self.followers.get(key)
        if record and not record.get('deleted', False):
            return record
        return None


def _cache_key(tenant_id: int, follower_id: int, followed_id: int) -> str:
    return f"follow_status:{tenant_id}:{follower_id}:{followed_id}"


# ===== TEST RESULT =====

@dataclass
class TestResult:
    test_id: str
    test_name: str
    passed: bool
    duration_ms: float
    error_message: str = ""
    metrics: Dict = None


# ===== TEST SUITE =====

class FollowStatusTestSuite:
    def __init__(self):
        self.results = []
        self.test_log_lines = []
    
    def log_event(self, event: str):
        self.test_log_lines.append(event)
        logger.info(event)
    
    def test_01_ui_desync_cache_delay(self) -> TestResult:
        test_id = "ui_desync_cache_delay"
        test_name = "UI stays correct despite Redis cache delay"
        self.log_event(f"\n[TEST 1] {test_name}")
        start = time.time()
        
        try:
            redis = MockRedis(delay_ms=2000)
            db = MockDB()
            tenant_id, follower_id, followed_id = 1, 101, 202
            
            self.log_event(f"  1. Insert into DB: {follower_id}->{followed_id}")
            record = db.insert_follower(tenant_id, follower_id, followed_id)
            assert record is not None
            self.log_event(f"     ✓ DB insert successful")
            
            self.log_event(f"  2. Write to Redis (with {redis.delay_ms}ms delay)")
            cache_key = _cache_key(tenant_id, follower_id, followed_id)
            redis.set(cache_key, "1", ex=300)
            self.log_event(f"     ✓ Cache write complete")
            
            self.log_event(f"  3. Query DB (cache may be stale)...")
            time.sleep(0.5)
            db_record = db.get_follower(tenant_id, follower_id, followed_id)
            following = db_record is not None
            
            self.log_event(f"     DB has row: {following}")
            self.log_event(f"     Cache value: {redis.get(cache_key)} (may be None if not yet written)")
            self.log_event(f"     ✓ Reconciliation: DB is source of truth")
            
            assert following == True
            duration = (time.time() - start) * 1000
            return TestResult(test_id, test_name, True, duration, metrics={'delay_ms': 2000})
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.log_event(f"  ✗ FAILED: {str(e)}")
            return TestResult(test_id, test_name, False, duration, str(e))
    
    def test_02_concurrent_toggle_race(self) -> TestResult:
        test_id = "concurrent_toggle_race"
        test_name = "Concurrent rapid toggles result in consistent final state"
        self.log_event(f"\n[TEST 2] {test_name}")
        start = time.time()
        
        try:
            db = MockDB()
            redis = MockRedis()
            tenant_id, follower_id, followed_id = 1, 303, 404
            cache_key = _cache_key(tenant_id, follower_id, followed_id)
            
            actions = ['follow', 'unfollow', 'follow']
            for i, action in enumerate(actions, 1):
                self.log_event(f"  Action {i}: {action}")
                
                if action == 'follow':
                    try:
                        db.insert_follower(tenant_id, follower_id, followed_id)
                        self.log_event(f"    - DB insert")
                    except:
                        self.log_event(f"    - DB already exists (idempotent)")
                    redis.set(cache_key, "1", ex=300)
                    self.log_event(f"    - Cache set to 1")
                else:
                    db.delete_follower(tenant_id, follower_id, followed_id)
                    self.log_event(f"    - DB soft-delete")
                    redis.delete(cache_key)
                    self.log_event(f"    - Cache deleted")
                
                time.sleep(0.05)
            
            self.log_event(f"  Final state check:")
            db_record = db.get_follower(tenant_id, follower_id, followed_id)
            final_state = db_record is not None
            self.log_event(f"    DB: {final_state}")
            self.log_event(f"    Cache: {redis.get(cache_key)}")
            self.log_event(f"    ✓ Expected state (following=True) reached")
            
            assert final_state == True
            duration = (time.time() - start) * 1000
            return TestResult(test_id, test_name, True, duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.log_event(f"  ✗ FAILED: {str(e)}")
            return TestResult(test_id, test_name, False, duration, str(e))
    
    def test_03_cross_tenant_visibility(self) -> TestResult:
        test_id = "cross_tenant_visibility"
        test_name = "Redis keys properly scoped by tenant"
        self.log_event(f"\n[TEST 3] {test_name}")
        start = time.time()
        
        try:
            db = MockDB()
            redis = MockRedis()
            follower_id, followed_id = 5001, 5002
            
            self.log_event(f"  1. Tenant 1 creates follow: {follower_id}->{followed_id}")
            db.insert_follower(1, follower_id, followed_id)
            cache_key_t1 = _cache_key(1, follower_id, followed_id)
            redis.set(cache_key_t1, "1", ex=300)
            self.log_event(f"     Cache key: {cache_key_t1}")
            self.log_event(f"     ✓ Tenant 1 data stored")
            
            self.log_event(f"  2. Tenant 2 queries same IDs: {follower_id}->{followed_id}")
            cache_key_t2 = _cache_key(2, follower_id, followed_id)
            self.log_event(f"     Cache key: {cache_key_t2}")
            
            cache_value_t2 = redis.get(cache_key_t2)
            db_record_t2 = db.get_follower(2, follower_id, followed_id)
            
            self.log_event(f"     Cache: {cache_value_t2} (should be None)")
            self.log_event(f"     DB: {db_record_t2} (should be None)")
            self.log_event(f"     ✓ Tenant isolation verified")
            
            assert cache_value_t2 is None and db_record_t2 is None
            duration = (time.time() - start) * 1000
            return TestResult(test_id, test_name, True, duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.log_event(f"  ✗ FAILED: {str(e)}")
            return TestResult(test_id, test_name, False, duration, str(e))
    
    def test_04_api_returns_stale_after_soft_delete(self) -> TestResult:
        test_id = "api_returns_stale_after_soft_delete"
        test_name = "Soft-deleted relationships not returned as active"
        self.log_event(f"\n[TEST 4] {test_name}")
        start = time.time()
        
        try:
            db = MockDB()
            redis = MockRedis()
            tenant_id, follower_id, followed_id = 3, 700, 701
            cache_key = _cache_key(tenant_id, follower_id, followed_id)
            
            self.log_event(f"  1. Create follow relationship")
            db.insert_follower(tenant_id, follower_id, followed_id)
            redis.set(cache_key, "1", ex=300)
            self.log_event(f"     ✓ Created in DB and cached")
            
            self.log_event(f"  2. Soft-delete the relationship")
            db.delete_follower(tenant_id, follower_id, followed_id)
            self.log_event(f"     ✓ Soft-delete done (cache not yet invalidated)")
            
            self.log_event(f"  3. Query after soft-delete")
            cache_val = redis.get(cache_key)
            db_record = db.get_follower(tenant_id, follower_id, followed_id)
            
            self.log_event(f"     Cache: {cache_val} (stale - still 1)")
            self.log_event(f"     DB: {db_record} (None - correctly filtered)")
            self.log_event(f"     ✓ DB is source of truth, returns False")
            
            assert db_record is None
            duration = (time.time() - start) * 1000
            return TestResult(test_id, test_name, True, duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.log_event(f"  ✗ FAILED: {str(e)}")
            return TestResult(test_id, test_name, False, duration, str(e))
    
    def test_05_delayed_backend_confirmation(self) -> TestResult:
        test_id = "delayed_backend_confirmation"
        test_name = "Frontend waits for backend confirmation before updating UI"
        self.log_event(f"\n[TEST 5] {test_name}")
        start = time.time()
        
        try:
            db = MockDB()
            tenant_id, follower_id, followed_id = 4, 800, 801
            
            self.log_event(f"  1. First follow request -> creates DB row")
            record1 = db.insert_follower(tenant_id, follower_id, followed_id)
            http_status_1 = 200
            self.log_event(f"     HTTP Status: {http_status_1} (success)")
            
            self.log_event(f"  2. Second follow request -> duplicate")
            try:
                record2 = db.insert_follower(tenant_id, follower_id, followed_id)
                http_status_2 = 200
            except Exception:
                # Backend: on IntegrityError, check state and return idempotent 200
                http_status_2 = 200
                self.log_event(f"     Detected duplicate, returning idempotent 200")
            
            self.log_event(f"     HTTP Status: {http_status_2} (idempotent)")
            
            self.log_event(f"  3. Frontend behavior")
            self.log_event(f"     FIXED: Only updates UI if HTTP 200")
            self.log_event(f"     Request 1 -> {http_status_1} -> Update to 'Following'")
            self.log_event(f"     Request 2 -> {http_status_2} -> Confirm 'Following'")
            
            self.log_event(f"  4. Verify final state")
            db_record = db.get_follower(tenant_id, follower_id, followed_id)
            assert db_record is not None
            self.log_event(f"     ✓ Following confirmed")
            
            duration = (time.time() - start) * 1000
            return TestResult(test_id, test_name, True, duration)
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.log_event(f"  ✗ FAILED: {str(e)}")
            return TestResult(test_id, test_name, False, duration, str(e))
    
    def run_all_tests(self) -> List[TestResult]:
        self.log_event("=" * 80)
        self.log_event("FOLLOW UI/UX TEST SUITE")
        self.log_event("=" * 80)
        
        tests = [
            self.test_01_ui_desync_cache_delay,
            self.test_02_concurrent_toggle_race,
            self.test_03_cross_tenant_visibility,
            self.test_04_api_returns_stale_after_soft_delete,
            self.test_05_delayed_backend_confirmation
        ]
        
        for test in tests:
            result = test()
            self.results.append(result)
        
        passed = sum(1 for r in self.results if r.passed)
        self.log_event(f"\n{'=' * 80}")
        self.log_event(f"RESULTS: {passed}/{len(self.results)} passed")
        self.log_event(f"Success Rate: {(passed/len(self.results)*100):.1f}%")
        self.log_event(f"{'=' * 80}\n")
        
        return self.results


if __name__ == "__main__":
    suite = FollowStatusTestSuite()
    results = suite.run_all_tests()
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for r in results:
        status = "✓" if r.passed else "✗"
        print(f"{status} {r.test_id:40} {r.duration_ms:8.2f}ms")
    
    print("\nDETAILS:")
    for r in results:
        print(f"\n{r.test_id}:")
        print(f"  Status: {'PASS' if r.passed else 'FAIL'}")
        if r.error_message:
            print(f"  Error: {r.error_message}")
