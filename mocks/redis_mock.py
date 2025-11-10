import threading
import time
from collections import defaultdict
from typing import Optional

class RedisMock:
    """A simple Redis mock supporting delayed writes, TTL and pub/sub simulation.

    Behavior:
    - Shared keyspace by default (simulate non-tenant-aware Redis in original system)
    - set/get with optional ex (seconds) or ex_ms (milliseconds)
    - setnx used by DistributedLock
    - publish records messages in a list for tests to inspect
    """
    def __init__(self, write_delay_ms=0):
        self.store = {}  # key -> (value, expire_at)
        self.lock = threading.Lock()
        self.write_delay_ms = write_delay_ms
        self.pubsub = defaultdict(list)  # channel -> list of messages

    def _now_ms(self):
        return int(time.time() * 1000)

    def _expire_cleanup(self):
        now = self._now_ms()
        to_delete = []
        for k, (v, exp) in list(self.store.items()):
            if exp is not None and exp < now:
                to_delete.append(k)
        for k in to_delete:
            del self.store[k]

    def set(self, key, value, ex: Optional[int]=None, ex_ms: Optional[int]=None):
        # simulate eventual consistency by delaying writes
        if self.write_delay_ms > 0:
            def delayed():
                time.sleep(self.write_delay_ms / 1000.0)
                with self.lock:
                    exp = None
                    if ex_ms is not None:
                        exp = self._now_ms() + ex_ms
                    elif ex is not None:
                        exp = self._now_ms() + ex * 1000
                    self.store[key] = (value, exp)
            t = threading.Thread(target=delayed)
            t.daemon = True
            t.start()
        else:
            with self.lock:
                exp = None
                if ex_ms is not None:
                    exp = self._now_ms() + ex_ms
                elif ex is not None:
                    exp = self._now_ms() + ex * 1000
                self.store[key] = (value, exp)

    def get(self, key):
        with self.lock:
            self._expire_cleanup()
            v = self.store.get(key)
            if v is None:
                return None
            return v[0]

    def setnx(self, key, value, ex_ms=None):
        with self.lock:
            self._expire_cleanup()
            if key in self.store:
                return False
            exp = None
            if ex_ms is not None:
                exp = self._now_ms() + ex_ms
            self.store[key] = (value, exp)
            return True

    def delete(self, key):
        with self.lock:
            if key in self.store:
                del self.store[key]

    def publish(self, channel, message):
        # append message for tests to inspect
        with self.lock:
            self.pubsub[channel].append((self._now_ms(), message))

    def get_pubsub_messages(self, channel):
        with self.lock:
            return list(self.pubsub.get(channel, []))

    # helper for tests
    def clear(self):
        with self.lock:
            self.store.clear()
            self.pubsub.clear()

# Typing helpers
from typing import Optional
