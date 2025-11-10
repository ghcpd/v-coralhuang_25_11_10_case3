import time
import threading
from typing import Optional, Dict, Any


class RedisMock:
    """
    A simplified Redis mock that supports delays, TTL, and a basic lock and pub/sub.
    It can simulate replica lag by not making writes visible until a delay elapses.
    """

    def __init__(self, default_delay_ms: int = 0):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._pubsub_channels = {}
        self.default_delay_ms = default_delay_ms

    def set(self, key: str, value: str, ex: Optional[int] = None, delay_ms: Optional[int] = None):
        # Schedule write after delay_ms, default to default_delay_ms. If delay is 0, write synchronously.
        if delay_ms is None:
            delay_ms = self.default_delay_ms

        if delay_ms <= 0:
            with self._lock:
                self._store[key] = {'value': value, 'expires_at': (time.time() + ex if ex else None)}
            self._append_log(f"SET {key} {value} EX {ex}")
            self._append_log(f"SET {key} {value} EX {ex}")
        else:
            def write_later():
                time.sleep(delay_ms / 1000.0)
                with self._lock:
                    self._store[key] = {'value': value, 'expires_at': (time.time() + ex if ex else None)}
                self._append_log(f"SET_DELAYED {key} {value} EX {ex} DELAY_MS {delay_ms}")
            t = threading.Thread(target=write_later)
            t.daemon = True
            t.start()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry['expires_at'] and entry['expires_at'] < time.time():
                # expired
                del self._store[key]
                return None
            val = entry['value']
            self._append_log(f"GET {key} -> {val}")
            return val

    def get_versioned(self, key: str):
        """Return (value, ts) if value stored in format "<val>|<ts>" else (value, None)"""
        v = self.get(key)
        if v is None:
            return None, None
        if '|' in v:
            val, ts = v.split('|', 1)
            try:
                ts = float(ts)
            except Exception:
                ts = None
            return val, ts
        return v, None

    def set_versioned(self, key: str, value: str, ts: float, ex: Optional[int] = None, delay_ms: Optional[int] = None):
        existing, existing_ts = self.get_versioned(key)
        if existing_ts is not None and existing_ts > ts:
            # Don't overwrite newer value
            self._append_log(f"SET_SKIPPED_OLDER {key} {value} EX {ex} TS {ts} EXISTING_TS {existing_ts}")
            return
        self.set(key, f"{value}|{ts}", ex=ex, delay_ms=delay_ms)


    def delete(self, key: str):
        with self._lock:
            if key in self._store:
                del self._store[key]
                self._append_log(f"DELETE {key}")

    def ttl(self, key: str) -> Optional[int]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry['expires_at']:
                return int(entry['expires_at'] - time.time())
            return None

    def lock(self, key: str, timeout: int = 5):
        # Simple context manager that acquires the global lock; not a real distributed lock.
        return self._lock_context(self._lock)

    class _lock_context:
        def __init__(self, lock):
            self.lock = lock

        def __enter__(self):
            self.lock.acquire()

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.lock.release()

    def publish(self, channel: str, message: str):
        # call all subscribers
        subs = self._pubsub_channels.get(channel, [])
        for cb in subs:
            try:
                cb(message)
            except Exception:
                pass
        self._append_log(f"PUBLISH {channel} -> {message}")

    def subscribe(self, channel: str, callback):
        self._pubsub_channels.setdefault(channel, []).append(callback)


redis_singleton = RedisMock()

def _ensure_logfile():
    import os
    os.makedirs('logs', exist_ok=True)
    open('logs/test_run.log', 'a').close()

# add helper method dynamically for logging
def _append_log(self, msg: str):
    _ensure_logfile()
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open('logs/test_run.log', 'a') as f:
        f.write(f"{ts} {msg}\n")

RedisMock._append_log = _append_log

