from flask import Blueprint, request, jsonify
from .models import db, Follower
from mocks.redis_mock import redis_singleton
import time

bp = Blueprint('follow', __name__)

CACHE_TTL = 60  # seconds


def make_cache_key(tenant_id: int, follower_id: int, followed_id: int) -> str:
    return f"follow_status:{tenant_id}:{follower_id}:{followed_id}"


@bp.route('/follow', methods=['POST'])
def follow():
    data = request.get_json() or {}
    tenant_id = int(data['tenant_id'])
    follower_id = int(data['follower_id'])
    followed_id = int(data['followed_id'])

    # acquire a lock to prevent races
    lock_key = f"lock:follow:{tenant_id}:{follower_id}:{followed_id}"
    with redis_singleton.lock(lock_key):
        # Check if entry already exists (undeleted)
        existing = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id).first()
        if existing and not existing.deleted:
            # idempotent
            pass
        elif existing and existing.deleted:
            existing.deleted = False
            db.session.add(existing)
        else:
            newf = Follower(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id)
            db.session.add(newf)
        db.session.commit()
        # write-through cache (versioned by commit ts) to avoid late writes overwriting newer state
        key = make_cache_key(tenant_id, follower_id, followed_id)
        ts = time.time()
        redis_singleton.set_versioned(key, '1', ts, ex=CACHE_TTL)
        # publish invalidation for other nodes/sessions
        redis_singleton.publish(f"invalidate:{tenant_id}:{follower_id}:{followed_id}", '1')
        # publish invalidation for other nodes/sessions
        redis_singleton.publish(f"invalidate:{tenant_id}:{follower_id}:{followed_id}", '1')

    return jsonify({'ok': True, 'following': True}), 200


@bp.route('/unfollow', methods=['POST', 'DELETE'])
def unfollow():
    data = request.get_json() or {}
    tenant_id = int(data['tenant_id'])
    follower_id = int(data['follower_id'])
    followed_id = int(data['followed_id'])

    lock_key = f"lock:follow:{tenant_id}:{follower_id}:{followed_id}"
    with redis_singleton.lock(lock_key):
        existing = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id).first()
        if existing and not existing.deleted:
            existing.deleted = True
            db.session.add(existing)
            db.session.commit()
        else:
            # idempotent
            pass

    key = make_cache_key(tenant_id, follower_id, followed_id)
    ts = time.time()
    redis_singleton.set_versioned(key, '0', ts, ex=CACHE_TTL)
    redis_singleton.publish(f"invalidate:{tenant_id}:{follower_id}:{followed_id}", '0')

    return jsonify({'ok': True, 'following': False}), 200


@bp.route('/follow_status/<int:tenant_id>/<int:followed_id>', methods=['GET'])
def follow_status(tenant_id, followed_id):
    follower_id = request.args.get('follower_id')
    if not follower_id:
        return jsonify({'error': 'missing follower_id'}), 400
    follower_id = int(follower_id)

    key = make_cache_key(tenant_id, follower_id, followed_id)
    cached = redis_singleton.get(key)
    if cached is not None:
        # cached string '1' or '0' or versioned like '1|TS'
        if '|' in cached:
            val, _ = cached.split('|', 1)
        else:
            val = cached
        if val == '1':
            return jsonify({'following': True}), 200
        # cached says not following (0). Reconcile with DB to detect stale cache.
        rel = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id, deleted=False).first()
        if rel:
            # DB indicates following; update cache and return true
            ts = time.time()
            redis_singleton.set_versioned(key, '1', ts, ex=CACHE_TTL)
            return jsonify({'following': True}), 200
        else:
            return jsonify({'following': False}), 200

    # Cache miss or drift: reconcile with DB
    # This ensures stale caches don't return false while DB shows a relationship
    rel = Follower.query.filter_by(tenant_id=tenant_id, follower_id=follower_id, followed_id=followed_id, deleted=False).first()
    following = bool(rel)
    # Update cache (versioned) so subsequent requests are fast
    ts = time.time()
    redis_singleton.set_versioned(key, '1' if following else '0', ts, ex=CACHE_TTL)
    return jsonify({'following': following}), 200
