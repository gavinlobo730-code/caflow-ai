"""
Simple in-process rate limiter for AI endpoints.
Limits per (firm_id, endpoint_prefix) using a sliding window counter.
For production with multiple workers, use Redis-backed limiting.
"""
import time
import threading
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import Request, HTTPException

_lock = threading.Lock()
# { (firm_id, prefix): [(timestamp, count), ...] }
_windows: Dict[Tuple[str, str], list] = defaultdict(list)

# Limits: (max_requests, window_seconds)
_LIMITS = {
    "/api/ai-copilot": (20, 60),       # 20 req/min per firm
    "/api/intelligence": (30, 60),      # 30 req/min per firm
    "/api/assistant": (20, 60),
}


def check_rate_limit(request: Request, firm_id: str) -> None:
    """Raise 429 if firm exceeds the rate limit for this endpoint prefix."""
    path = request.url.path
    matched_prefix = next((p for p in _LIMITS if path.startswith(p)), None)
    if not matched_prefix:
        return

    max_req, window = _LIMITS[matched_prefix]
    key = (firm_id, matched_prefix)
    now = time.monotonic()
    cutoff = now - window

    with _lock:
        bucket = _windows[key]
        # Prune old entries
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= max_req:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {max_req} requests per {window}s for this endpoint.",
            )
        bucket.append(now)
