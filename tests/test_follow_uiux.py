import time
import threading
import json
from api.follow_status import create_test_service
from mocks.redis_mock import RedisMock


def write_log(path, text):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text + '\n')


def test_normal_flow(tmp_path):
    redis = RedisMock(write_delay_ms=0)
    svc, db = create_test_service(redis_client=redis)

    # normal follow
    ok = svc.follow(1, 101, 202)
    assert ok
    assert db.is_following(1, 101, 202)
    # cache should be set
    assert redis.get('follow_status:1:101:202') == '1'


def test_cache_delay(tmp_path):
    redis = RedisMock(write_delay_ms=2000)
    svc, db = create_test_service(redis_client=redis)

    # perform follow; DB is immediate, cache delayed
    t0 = time.time()
    svc.follow(1, 101, 202)
    # immediately read status - cache may not have been written yet
    cached = redis.get('follow_status:1:101:202')
    # cached likely None due to delay, but the service's follow_status should reconcile
    status = svc.follow_status(1, 101, 202)
    assert status is True
    # wait for eventual consistency
    time.sleep(2.2)
    assert redis.get('follow_status:1:101:202') == '1'


def test_concurrent_toggle(tmp_path):
    redis = RedisMock(write_delay_ms=0)
    svc, db = create_test_service(redis_client=redis)

    follower = 303
    followed = 404

    def do_actions():
        svc.follow(1, follower, followed)
        time.sleep(0.05)
        svc.unfollow(1, follower, followed)
        time.sleep(0.05)
        svc.follow(1, follower, followed)

    threads = [threading.Thread(target=do_actions) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # final DB state should be following
    assert db.is_following(1, follower, followed)
    # final cache should reflect following
    assert redis.get(f'follow_status:1:{follower}:{followed}') == '1'


def test_cross_tenant_isolation(tmp_path):
    # Redis is shared; keys include tenant now so isolation should hold
    redis = RedisMock(write_delay_ms=0)
    svc, db = create_test_service(redis_client=redis)

    # tenant 1 follows
    svc.follow(1, 5001, 5002)
    # tenant 2 should not see that key
    val1 = redis.get('follow_status:1:5001:5002')
    val2 = redis.get('follow_status:2:5001:5002')
    assert val1 == '1'
    assert val2 is None or val2 == '0'


def test_soft_delete_behavior(tmp_path):
    redis = RedisMock(write_delay_ms=0)
    svc, db = create_test_service(redis_client=redis)

    svc.follow(3, 700, 701)
    # soft-delete
    db.remove_follow(3, 700, 701)
    # cache still says 1
    redis.set('follow_status:3:700:701', '1', ex=60)
    # follow_status should check DB and overwrite cache
    status = svc.follow_status(3, 700, 701)
    assert status is False
    assert redis.get('follow_status:3:700:701') == '0'


def test_backend_failure_rollback(tmp_path):
    # simulate db integrity error by invoking follow twice and expecting no UI permanent change
    redis = RedisMock(write_delay_ms=0)
    svc, db = create_test_service(redis_client=redis)

    # first follow
    svc.follow(4, 800, 801)
    # second follow should be idempotent (treated as success)
    svc.follow(4, 800, 801)
    # simulate a failure: direct DB error in insert - we can't easily simulate exception from service
    # Instead, verify follow_status returns DB truth
    assert db.is_following(4, 800, 801)
    # now manually clear cache to simulate failure in cache write
    redis.delete('follow_status:4:800:801')
    # follow_status should read DB and restore cache
    assert svc.follow_status(4, 800, 801) is True


if __name__ == '__main__':
    # simple runner to execute tests and capture outputs
    out = {}
    results = []
    tests = [
        test_normal_flow,
        test_cache_delay,
        test_concurrent_toggle,
        test_cross_tenant_isolation,
        test_soft_delete_behavior,
        test_backend_failure_rollback,
    ]
    logpath = 'logs/test_run.log'
    # clear log
    open(logpath, 'w').close()
    for t in tests:
        name = t.__name__
        try:
            t(tmp_path='.')
            results.append({'test': name, 'status': 'PASS'})
            write_log(logpath, f"{name}: PASS")
        except AssertionError as e:
            results.append({'test': name, 'status': 'FAIL', 'error': str(e)})
            write_log(logpath, f"{name}: FAIL - {e}")
        except Exception as e:
            results.append({'test': name, 'status': 'ERROR', 'error': str(e)})
            write_log(logpath, f"{name}: ERROR - {e}")

    out['results'] = results
    with open('results_uiux.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
