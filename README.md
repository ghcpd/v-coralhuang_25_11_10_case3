This small project demonstrates a corrected follow/unfollow flow addressing UI/cache/DB desync.

Key points:
- Backend `FollowService` ensures tenant-scoped Redis keys and reconciles cache with DB on cache miss or when cache indicates no-following.
- `FollowService` performs lock-based write operations and uses Redis pub/sub to broadcast changes.
- Frontend `FollowButton.jsx` waits for API confirmation and rolls back UI on errors.
- `mocks/redis_mock.py` simulates Redis behavior with TTL and pub/sub for tests.

How to run tests:

1. Install pytest: pip install pytest
2. Run pytest from repo root: pytest -q

Files of interest:
- `api/follow_status.py`: business logic, caching and reconciliation
- `frontend/FollowButton.jsx`: revised component (no unconditional optimistic update)
- `mocks/redis_mock.py`: simulation of Redis and replication delay
- `tests/test_follow_uiux.py`: e2e-like tests for cache-delay, concurrency, tenant isolation, soft delete, backend failure

Notes:
- DB scaffolding and schema changes need to be migrated in an existing production DB.
- Add `tenant_id` to `followers` table and enforce composite unique constraint. We provide a SQLAlchemy model with such constraint in `api/models.py`.
