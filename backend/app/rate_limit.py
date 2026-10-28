import threading
import time
from collections import OrderedDict, deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int, max_keys: int = 10000):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            # Ordered by last accepted request, so expired senders can be
            # collected without scanning all active senders on every request.
            while self._events:
                oldest = next(iter(self._events))
                if self._events[oldest][-1] > cutoff:
                    break
                del self._events[oldest]
            if key not in self._events:
                if len(self._events) >= self.max_keys:
                    return False
                self._events[key] = deque()
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            self._events.move_to_end(key)
            return True
