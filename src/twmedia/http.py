"""Polite HTTP client shared by all collectors.

Rules enforced here (see PLAN.md §4.5):
- honest User-Agent, no login, no challenge bypass
- robots.txt is checked before every request
- a minimum interval between requests to the same host
- a 403/429 or a bot-challenge page stops that source for the rest of the run
"""

from __future__ import annotations

import threading
import time
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

USER_AGENT = "twmedia-research/0.1 (+https://github.com/f0909172434)"
ROBOTS_AGENT = "twmedia-research"

_CHALLENGE_MARKERS = (
    "Just a moment...",
    "challenges.cloudflare.com",
    "需要確認您的連線是安全的",
)


class Blocked(Exception):
    """The site refused us (status code or bot challenge). Stop this source."""


class Disallowed(Exception):
    """robots.txt does not allow this URL."""


class PoliteClient:
    def __init__(self, min_interval: float = 2.0, timeout: float = 20.0, host_intervals: dict[str, float] | None = None):
        self.min_interval = min_interval
        self.host_intervals = host_intervals or {}  # per-host overrides, e.g. a slower pace for web.archive.org
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _wait_turn(self, host: str) -> None:
        interval = self.host_intervals.get(host, self.min_interval)
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last[host] = time.monotonic()

    def _robots_for(self, scheme: str, host: str) -> urllib.robotparser.RobotFileParser | None:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._client.get(f"{scheme}://{host}/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[host] = rp
            except httpx.HTTPError:
                self._robots[host] = None  # unreachable robots.txt: treat as no rules
        return self._robots[host]

    def get(
        self, url: str, *, cookies: dict | None = None, retries: int = 2, official_api: bool = False,
        follow_redirects: bool = True,
    ) -> httpx.Response:
        """official_api=True skips robots.txt: it governs crawlers, not authenticated API calls."""
        parts = urlsplit(url)
        host = parts.netloc
        safe_url = parts._replace(query="").geturl()  # never put query strings (API keys, tokens) in errors
        if not official_api:
            rp = self._robots_for(parts.scheme, host)
            if rp is not None and not rp.can_fetch(ROBOTS_AGENT, url):
                raise Disallowed(safe_url)

        with self._host_lock(host):
            for attempt in range(retries + 1):
                self._wait_turn(host)
                try:
                    r = self._client.get(url, cookies=cookies, follow_redirects=follow_redirects)
                except httpx.TransportError as e:
                    if attempt == retries:
                        raise httpx.TransportError(f"{type(e).__name__} {safe_url}") from None
                    time.sleep(5 * (attempt + 1))
                    continue
                # an official API's 403 is a permission error with a JSON body; let the caller report it
                if (r.status_code == 429 or (r.status_code == 403 and not official_api)) or _is_challenge(r):
                    raise Blocked(f"{r.status_code} {safe_url}")
                if r.status_code >= 500 and attempt < retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                return r
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._client.close()


def _is_challenge(r: httpx.Response) -> bool:
    if r.headers.get("cf-mitigated") == "challenge":
        return True
    if "text/html" not in r.headers.get("content-type", ""):
        return False
    head = r.text[:4000]
    return any(m in head for m in _CHALLENGE_MARKERS)
