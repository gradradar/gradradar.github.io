"""Small, polite HTTP helper. Stdlib only so the action needs no extra wheels."""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "grad-job-finder/1.0 (open-source graduate job aggregator)"
_lock = threading.Lock()
_last_call: dict[str, float] = {}
MIN_GAP = 0.34  # seconds between calls to the same host


class FetchError(RuntimeError):
    pass


def _throttle(url: str) -> None:
    host = urllib.parse.urlparse(url).netloc
    with _lock:
        gap = time.monotonic() - _last_call.get(host, 0.0)
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last_call[host] = time.monotonic()


def request_json(url: str, *, method: str = "GET", body: dict | None = None,
                 headers: dict[str, str] | None = None, timeout: int = 25,
                 retries: int = 3):
    """JSON request with throttling and backoff. Raises FetchError on failure."""
    payload = json.dumps(body).encode() if body is not None else None
    last: Exception | None = None

    for attempt in range(retries):
        _throttle(url)
        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/json")
        if payload:
            req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 401, 403, 404, 422):
                raise FetchError(f"HTTP {exc.code} for {url}") from exc
            # 429 / 5xx are worth another go
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError, OSError) as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (2 ** attempt) + random.random())
    raise FetchError(f"giving up on {url}: {last}")


def qs(base: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{base}?{urllib.parse.urlencode(clean)}"
