"""Polite, disk-cached, read-only HTTP GET for public JSON/CSV endpoints.

Design rules (this project hits free public APIs that rate-limit shared IPs):
  * Every successful response is cached on disk, so each URL is fetched once.
  * Each host has a minimum gap between requests.
  * HTTP 429 with a *daily* limit message raises RateLimited immediately and
    is remembered for the rest of the process: we never hammer a limit.
  * Only GET is implemented. There is no code path that can place an order,
    sign anything, or send credentials.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests

DATA_DIR = Path(os.environ.get("WEATHERBOT_DATA", Path(__file__).resolve().parent.parent / "data"))
CACHE_DIR = DATA_DIR / "cache"
USER_AGENT = "weatherbot-paper-research/0.1 (read-only research; contact: github chrisjeansonne1232-jpg/weatherbot)"

# seconds between two requests to the same host
MIN_GAP = {
    "gamma-api.polymarket.com": 0.25,
    "clob.polymarket.com": 0.12,
    "data-api.polymarket.com": 0.35,
    "previous-runs-api.open-meteo.com": 4.0,
    "historical-forecast-api.open-meteo.com": 4.0,
    "api.open-meteo.com": 2.0,
    "ensemble-api.open-meteo.com": 4.0,
    "archive-api.open-meteo.com": 4.0,
    "mesonet.agron.iastate.edu": 1.0,
    "aviationweather.gov": 1.0,
    "api.weather.gov": 1.0,
}
DEFAULT_GAP = 1.0


class RateLimited(RuntimeError):
    """A host told us its daily/hourly limit is used up. Stop calling it."""


class FetchError(RuntimeError):
    pass


_next_slot: dict[str, float] = {}
_lock = threading.Lock()
_blocked_hosts: dict[str, str] = {}
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _key(url: str, params) -> str:
    """Cache key from the URL and params (a dict, or a list of pairs for repeated keys)."""
    if params and not isinstance(params, dict):
        items = sorted((str(k), str(v)) for k, v in params)
    else:
        items = sorted((str(k), str(v)) for k, v in (params or {}).items())
    full = url + ("?" + urlencode(items) if items else "")
    return hashlib.sha256(full.encode()).hexdigest()


def _path(host: str, key: str) -> Path:
    return CACHE_DIR / host / key[:2] / f"{key}.gz"


def cached_only(url: str, params: dict | None = None) -> bool:
    host = urlparse(url).netloc
    return _path(host, _key(url, params)).exists()


def get(url: str, params: dict | None = None, *, as_text: bool = False, retries: int = 4, timeout: float = 60.0):
    """GET `url` (cached). Returns parsed JSON, or text if as_text=True."""
    host = urlparse(url).netloc
    key = _key(url, params)
    p = _path(host, key)
    if p.exists():
        raw = gzip.decompress(p.read_bytes()).decode("utf-8")
        return raw if as_text else json.loads(raw)
    if host in _blocked_hosts:
        raise RateLimited(f"{host} blocked this run: {_blocked_hosts[host]}")

    gap = MIN_GAP.get(host, DEFAULT_GAP)
    delay = 2.0
    last_err = ""
    for attempt in range(retries + 1):
        with _lock:  # one shared request budget per host, even with several worker threads
            now = time.monotonic()
            slot = max(now, _next_slot.get(host, 0.0))
            _next_slot[host] = slot + gap
        if slot > now:
            time.sleep(slot - now)
        try:
            r = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:  # network hiccup: back off and retry
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            text = r.text
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(text.encode("utf-8"), 6))
            tmp.replace(p)
            return text if as_text else json.loads(text)
        if r.status_code == 429:
            body = r.text[:200]
            if "limit" in body.lower() and ("daily" in body.lower() or "hourly" in body.lower() or "minutely" in body.lower() or "tomorrow" in body.lower()):
                _blocked_hosts[host] = body
                raise RateLimited(f"{host}: {body}")
            last_err = f"429 {body}"
            time.sleep(max(delay, float(r.headers.get("Retry-After", 0) or 0)))
            delay *= 2
            continue
        if 500 <= r.status_code < 600:
            last_err = f"{r.status_code}"
            time.sleep(delay)
            delay *= 2
            continue
        # 4xx other than 429: not retryable. Cache known-empty answers only for 404? No: raise.
        raise FetchError(f"{r.status_code} for {r.url}: {r.text[:200]}")
    raise FetchError(f"gave up on {url} {params}: {last_err}")
