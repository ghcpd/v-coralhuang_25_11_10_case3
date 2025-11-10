# Follow/Unfollow UI Consistency Fixes

This repository contains a simplified Flask + SQLAlchemy + Redis mock implementation to demonstrate fixes for UI/UX desynchronization between optimistic front-end updates, backend truth in PostgreSQL, and a shared Redis cache.

What this repo includes:
- `api/` - Flask app with follow/unfollow API and follow_status endpoint. Reconciles cache and DB on cache misses and uses tenant-aware cache keys.
- `mocks/redis_mock.py` - A Redis mock with delay simulation, TTL, locks, and pub/sub to model cache races and delays.
- `frontend/FollowButton.jsx` - React component that no longer performs unconditional optimistic updates; it shows a spinner and rolls back on failure.
- `tests/test_follow_uiux.py` - Pytest tests that validate cache delay reconciliation, concurrency, cross-tenant isolation, and soft-delete behavior.

How to run tests (Windows PowerShell):

```powershell
# set up local virtualenv
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

Notes:
- This is a simplified testbench intended to exercise the logic; production systems should use a managed Redis, a real distributed lock, and proper error handling.
