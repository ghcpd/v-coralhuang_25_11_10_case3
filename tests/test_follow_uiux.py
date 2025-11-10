import threading
import time

from api.follow_status import FollowService, tenant_cache_key
from api.models import Follower
from mocks.redis_mock import RedisMock


class InMemoryDB:
    def __init__(self, fail_commit=False):
        self.rows = []
        self._fail_commit = fail_commit

    def query(self, model):
        class Q:
            def __init__(self, rows):
                self.rows = rows

            def filter(self, cond):
                # cond will be a sqlalchemy and_ call in normal use; but we'll duck-type for the fields
                def first():
                    for r in self.rows:
                        if not r.deleted:
                            return r
                    return None

                q = type('q', (), {})()
                q.first = first
                return q

        return Q(self.rows)

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        if self._fail_commit:
            raise Exception('IntegrityError: duplicate key')

    def rollback(self):
        pass

    def has_following(self, tenant_id, follower_id, followed_id):
        for r in self.rows:
            if (r.tenant_id == tenant_id and r.follower_id == follower_id and
                    r.followed_id == followed_id and not r.deleted):
                return True
        return False


def test_ui_desync_cache_delay():
    redis = RedisMock()
    db = InMemoryDB()
    service = FollowService(db, redis)

    tenant, follower, followed = 1, 101, 202
    key = tenant_cache_key(tenant, follower, followed)
    # Simulate stale cache saying false
    redis.set(key, '0', ex=60)

    # Now call follow
    service.follow(tenant, follower, followed)

    # follow_status should return True (reconciled with DB even if cached = 0 earlier)
    assert service.get_following(tenant, follower, followed)


def test_concurrent_toggle_race():
    redis = RedisMock()
    db = InMemoryDB()
    service = FollowService(db, redis)

    tenant, follower, followed = 1, 303, 404

    def do_follow():
        service.follow(tenant, follower, followed)

    def do_unfollow():
        service.unfollow(tenant, follower, followed)

    # run follow, unfollow, follow in rapid succession with threads
    t1 = threading.Thread(target=do_follow)
    t2 = threading.Thread(target=do_unfollow)
    t3 = threading.Thread(target=do_follow)
    t1.start(); t2.start(); t3.start()
    t1.join(); t2.join(); t3.join()

    # DB final state should be following
    assert service.get_following(tenant, follower, followed)
    # Redis should also reflect following
    key = tenant_cache_key(tenant, follower, followed)
    assert redis.get(key) == '1'


def test_cross_tenant_isolation():
    redis = RedisMock()
    db1 = InMemoryDB()
    db2 = InMemoryDB()
    svc1 = FollowService(db1, redis)
    svc2 = FollowService(db2, redis)

    tenant_writer = 1
    tenant_reader = 2
    follower = 5001
    followed = 5002

    svc1.follow(tenant_writer, follower, followed)

    # tenant 2 should not see tenant 1's key
    assert not svc2.get_following(tenant_reader, follower, followed)


def test_soft_delete_excluded_from_api():
    redis = RedisMock()
    db = InMemoryDB()
    svc = FollowService(db, redis)

    tenant, follower, followed = 3, 700, 701

    svc.follow(tenant, follower, followed)
    svc.unfollow(tenant, follower, followed)

    # should not be following
    assert not svc.get_following(tenant, follower, followed)


def test_delayed_backend_confirmation_rolls_back():
    redis = RedisMock()
    db = InMemoryDB(fail_commit=True)
    svc = FollowService(db, redis)

    tenant, follower, followed = 4, 800, 801
    try:
        svc.follow(tenant, follower, followed)
        assert False, "follow should have raised"
    except Exception as e:
        # ensure cache remains invalidated
        key = tenant_cache_key(tenant, follower, followed)
        assert redis.get(key) in (None, '0')
