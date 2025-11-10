import time
import json
from contextlib import contextmanager

from flask import Blueprint, request, jsonify
from sqlalchemy import and_

from .models import Follower

bp = Blueprint('follow', __name__)


def tenant_cache_key(tenant_id, follower_id, followed_id):
    return f"follow_status:{tenant_id}:{follower_id}:{followed_id}"


class FollowService:
    def __init__(self, db_session, redis_client, lock_timeout=5, ttl=60):
        self.db = db_session
        self.redis = redis_client
        self.lock_timeout = lock_timeout
        self.ttl = ttl

    def _read_db(self, tenant_id, follower_id, followed_id):
        # Support simplified in-memory DB for tests
        if hasattr(self.db, 'has_following'):
            return self.db.has_following(tenant_id, follower_id, followed_id)
        q = self.db.query(Follower).filter(and_(
            Follower.tenant_id == tenant_id,
            Follower.follower_id == follower_id,
            Follower.followed_id == followed_id,
            Follower.deleted == False,
        ))
        return q.first() is not None

    def get_following(self, tenant_id, follower_id, followed_id):
        key = tenant_cache_key(tenant_id, follower_id, followed_id)
        cached = self.redis.get(key)
        if cached is not None:
            val = bool(int(cached))
            # If cache claims not following, double-check DB to avoid drift
            if not val:
                db_val = self._read_db(tenant_id, follower_id, followed_id)
                if db_val:
                    # reconcile: update cache to truth
                    self.redis.set(key, '1', ex=self.ttl)
                    return True
            return val

        # cache miss: check DB and fill cache
        db_val = self._read_db(tenant_id, follower_id, followed_id)
        self.redis.set(key, '1' if db_val else '0', ex=self.ttl)
        return db_val

    @contextmanager
    def _acquire_lock(self, key):
        # simple lock for tests / single-process semantics
        lock = self.redis.lock(key + ':lock', timeout=self.lock_timeout)
        acquired = lock.acquire(blocking=True)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

    def follow(self, tenant_id, follower_id, followed_id):
        key = tenant_cache_key(tenant_id, follower_id, followed_id)
        with self._acquire_lock(key) as _acq:
            # Check DB first
            if self._read_db(tenant_id, follower_id, followed_id):
                # Already exists
                self.redis.set(key, '1', ex=self.ttl)
                return True
            # Insert DB row
            row = Follower(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id, deleted=False)
            self.db.add(row)
            try:
                self.db.commit()
            except Exception:
                # rollback and re-raise so front-end can rollback optimistic update
                self.db.rollback()
                raise
            # set redis and publish
            self.redis.set(key, '1', ex=self.ttl)
            self.redis.publish('follow_changes', json.dumps({
                'tenant': tenant_id, 'follower': follower_id, 'followed': followed_id, 'following': 1
            }))
            return True

    def unfollow(self, tenant_id, follower_id, followed_id):
        key = tenant_cache_key(tenant_id, follower_id, followed_id)
        with self._acquire_lock(key) as _acq:
            q = self.db.query(Follower).filter(and_(
                Follower.tenant_id == tenant_id,
                Follower.follower_id == follower_id,
                Follower.followed_id == followed_id,
                Follower.deleted == False,
            ))
            row = q.first()
            if not row:
                # Already not following
                self.redis.set(key, '0', ex=self.ttl)
                return True
            # soft delete
            row.deleted = True
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.redis.set(key, '0', ex=self.ttl)
            self.redis.publish('follow_changes', json.dumps({
                'tenant': tenant_id, 'follower': follower_id, 'followed': followed_id, 'following': 0
            }))
            return True


@bp.route('/follow_status/<int:tenant_id>/<int:followed_id>', methods=['GET'])
def follow_status(tenant_id, followed_id):
    follower_id = request.args.get('follower_id', type=int)
    if follower_id is None:
        return jsonify({'error': 'follower_id required'}), 400
    svc: FollowService = request.environ.get('follow_service')
    res = svc.get_following(tenant_id, follower_id, followed_id)
    return jsonify({'following': res})


@bp.route('/follow', methods=['POST'])
def follow_endpoint():
    body = request.get_json() or {}
    tenant_id = body.get('tenant_id')
    follower_id = body.get('follower_id')
    followed_id = body.get('followed_id')
    action = body.get('action', 'follow')
    svc: FollowService = request.environ.get('follow_service')
    try:
        if action == 'follow':
            svc.follow(tenant_id, follower_id, followed_id)
            return jsonify({'following': True}), 200
        else:
            svc.unfollow(tenant_id, follower_id, followed_id)
            return jsonify({'following': False}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
