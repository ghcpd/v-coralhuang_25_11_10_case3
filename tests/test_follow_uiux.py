import time
import threading
import json
import pytest
from api.app import create_app
from api.models import db, Follower
from mocks.redis_mock import redis_singleton


@pytest.fixture(autouse=True)
def app():
    app = create_app(test_config={'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    app.testing = True
    with app.app_context():
        yield app


@pytest.fixture(autouse=True)
def client(app):
    client = app.test_client()
    # reset redis state
    redis_singleton._store.clear()
    redis_singleton.default_delay_ms = 0
    yield client


def test_cache_delay(client):
    # simulate a redis write delay
    redis_singleton.default_delay_ms = 2000
    tenant_id = 1
    follower_id = 101
    followed_id = 202
    # Call follow
    r = client.post('/follow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})
    assert r.status_code == 200
    # Immediately call status; with cache miss we should reconcile with DB and return True
    start = time.time()
    r2 = client.get(f'/follow_status/{tenant_id}/{followed_id}', query_string={'follower_id': follower_id})
    elapsed = (time.time() - start) * 1000.0
    assert r2.status_code == 200
    body = r2.get_json()
    assert body['following'] is True
    # check redis receives a value after delay
    time.sleep(2.2)
    key = f'follow_status:{tenant_id}:{follower_id}:{followed_id}'
    assert redis_singleton.get(key) == '1'


def test_concurrent_toggle(client):
    tenant_id = 1
    follower_id = 303
    followed_id = 404
    # Ensure no entry
    assert Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id).first() is None

    def p(method):
        if method == 'follow':
            client.post('/follow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})
        else:
            client.post('/unfollow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})

    # Rapid actions: follow, unfollow, follow
    threads = []
    for m in ['follow', 'unfollow', 'follow']:
        t = threading.Thread(target=p, args=(m,))
        t.start()
        threads.append(t)
        time.sleep(0.15)  # 150ms between actions
    for t in threads:
        t.join()

    # Final DB state should be following
    final = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id, deleted=False).first()
    assert final is not None
    # Cache should be consistent
    key = f'follow_status:{tenant_id}:{follower_id}:{followed_id}'
    # cache may take a moment to update; poll
    for _ in range(10):
        v = redis_singleton.get(key)
        if v == '1':
            break
        time.sleep(0.1)
    assert redis_singleton.get(key) == '1'


def test_cross_tenant_isolation(client):
    # Tenant 1 follows
    tenant1 = 1
    tenant2 = 2
    follower_id = 5001
    followed_id = 5002
    client.post('/follow', json={'tenant_id': tenant1, 'follower_id': follower_id, 'followed_id': followed_id})
    # Check tenant 1 status
    r1 = client.get(f'/follow_status/{tenant1}/{followed_id}', query_string={'follower_id': follower_id})
    assert r1.get_json()['following'] is True
    # Tenant 2 should not see it
    r2 = client.get(f'/follow_status/{tenant2}/{followed_id}', query_string={'follower_id': follower_id})
    assert r2.get_json()['following'] is False


def test_soft_delete_and_reconciliation(client):
    tenant_id = 3
    follower_id = 700
    followed_id = 701
    # Create a follow
    client.post('/follow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})
    # Soft delete in DB directly
    f = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id).first()
    assert f is not None
    f.deleted = True
    db.session.add(f)
    db.session.commit()
    # Manually set stale cache to 1 (simulate not invalidated)
    redis_singleton.set(f'follow_status:{tenant_id}:{follower_id}:{followed_id}', '1', ex=60)
    # Now request; follow_status must reconcile with DB and return following=false
    r = client.get(f'/follow_status/{tenant_id}/{followed_id}', query_string={'follower_id': follower_id})
    assert r.status_code == 200
    assert r.get_json()['following'] is False
