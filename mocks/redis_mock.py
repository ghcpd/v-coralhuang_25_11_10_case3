import time
import threading


class SimpleLock:
    def __init__(self):
        self._lock = threading.Lock()

    def acquire(self, blocking=True):
        return self._lock.acquire(blocking)

    def release(self):
        self._lock.release()


class RedisMock:
    def __init__(self):
        # store actual values
        self._store = {}
        self._store_ts = {}  # when value becomes visible
        self._pubsub = []
        self._locks = {}

    def _ensure_lock(self, name):
        if name not in self._locks:
            self._locks[name] = SimpleLock()
        return self._locks[name]

    def set(self, key, value, ex=None, delay_ms=0):
        visible_at = time.time() + (delay_ms / 1000.0)
        self._store[key] = str(value)
        self._store_ts[key] = visible_at
        # Simulate TTL: store expiry
        if ex:
            # store expiry epoch
            self._store_ts[key + ':expiry'] = time.time() + ex

    def get(self, key):
        t = time.time()
        visible = self._store_ts.get(key, 0)
        expiry = self._store_ts.get(key + ':expiry')
        if expiry and expiry < t:
            # expired
            self._store.pop(key, None)
            self._store_ts.pop(key, None)
            self._store_ts.pop(key + ':expiry', None)
            return None
        if t < visible:
            # Not visible yet (replication delay)
            return None
        return self._store.get(key)

    def delete(self, key):
        self._store.pop(key, None)
        self._store_ts.pop(key, None)

    def publish(self, channel, message):
        self._pubsub.append((channel, message))

    def subscribe_messages(self):
        # Return and clear
        msgs = list(self._pubsub)
        self._pubsub.clear()
        return msgs

    def lock(self, name, timeout=None):
        # returns a lock-like object
        return self._ensure_lock(name)
