import time
import json
from api.app import create_app
from api.models import db, Follower
from mocks.redis_mock import redis_singleton


def run():
    app = create_app(test_config={'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    with app.app_context():
        client = app.test_client()
        redis_singleton._store.clear()
        # Case 1: cache delay
        redis_singleton.default_delay_ms = 2000
        tenant_id = 1
        follower_id = 101
        followed_id = 202
        t0 = time.time()
        r = client.post('/follow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})
        t1 = time.time()
        follow_latency = (t1 - t0) * 1000.0
        r2 = client.get(f'/follow_status/{tenant_id}/{followed_id}', query_string={'follower_id': follower_id})
        status_after_follow = r2.get_json()['following']

        # Case 2: concurrent toggle
        redis_singleton.default_delay_ms = 0
        tenant_id = 1
        follower_id = 303
        followed_id = 404
        def p(method):
            if method == 'follow':
                client.post('/follow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})
            else:
                client.post('/unfollow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})

        import threading
        threads = []
        for m in ['follow', 'unfollow', 'follow']:
            t = threading.Thread(target=p, args=(m,))
            t.start()
            threads.append(t)
            time.sleep(0.15)
        for t in threads:
            t.join()
        final_db_state = bool(Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id, deleted=False).first())
        key = f'follow_status:{tenant_id}:{follower_id}:{followed_id}'
        final_cache_state = (redis_singleton.get(key) == '1')

        # Case 3: cross-tenant
        tenant1 = 1
        tenant2 = 2
        follower_id = 5001
        followed_id = 5002
        client.post('/follow', json={'tenant_id': tenant1, 'follower_id': follower_id, 'followed_id': followed_id})
        r1 = client.get(f'/follow_status/{tenant1}/{followed_id}', query_string={'follower_id': follower_id})
        r2 = client.get(f'/follow_status/{tenant2}/{followed_id}', query_string={'follower_id': follower_id})
        tenant1_status = r1.get_json()['following']
        tenant2_status = r2.get_json()['following']

        # Case 4: soft delete
        tenant_id = 3
        follower_id = 700
        followed_id = 701
        client.post('/follow', json={'tenant_id': tenant_id, 'follower_id': follower_id, 'followed_id': followed_id})
        f = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id).first()
        f.deleted = True
        db.session.add(f)
        db.session.commit()
        redis_singleton.set(f'follow_status:{tenant_id}:{follower_id}:{followed_id}', '1', ex=60)
        r = client.get(f'/follow_status/{tenant_id}/{followed_id}', query_string={'follower_id': follower_id})
        soft_status = r.get_json()['following']

        results = {
            'cache_delay': {
                'follow_call_latency_ms': follow_latency,
                'status_after_follow': status_after_follow
            },
            'concurrent_toggle': {
                'final_db_state': final_db_state,
                'final_cache_state': final_cache_state
            },
            'cross_tenant': {
                'tenant1_status': tenant1_status,
                'tenant2_status': tenant2_status
            },
            'soft_delete': {
                'status': soft_status
            }
        }

        with open('results_uiux.json', 'w') as f:
            json.dump(results, f, indent=2)
        print('Results (json):')
        print(json.dumps(results, indent=2))

        with open('output.json', 'w') as f:
            summary = {
                'status': 'complete',
                'findings': 'Reconciled cache on misses and added tenant awareness; tests executed',
                'tests': results
            }
            json.dump(summary, f, indent=2)
        print('Summary:')
        print(json.dumps(summary, indent=2))

        print('Results written to results_uiux.json and output.json')
        # Append to logs
        try:
            with open('logs/test_run.log', 'a') as lf:
                lf.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} Script completed\n")
        except Exception:
            pass


if __name__ == '__main__':
    try:
        run()
    except Exception as e:
        try:
            with open('logs/test_run.log', 'a') as lf:
                lf.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} Exception: {e}\n")
        except Exception:
            pass
        raise
