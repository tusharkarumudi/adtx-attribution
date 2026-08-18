"""Async HTTP layer: per-host token buckets, on-disk cache, request budget.

Caching is not a performance nicety here. Re-fetching a source changes what the
evidence record says was retrieved and when; for anything that may end up
supporting litigation, the cached body is the artifact.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

#: Requests per second, per host. Defaults are deliberately conservative.
RATE_LIMITS: dict[str, float] = {
    "efts.sec.gov": 8.0,
    "data.sec.gov": 8.0,
    "www.sec.gov": 8.0,
    "crt.sh": 1.0,
    "api.gleif.org": 4.0,
    "api.github.com": 8.0,
    "rdap.org": 5.0,
    "internetdb.shodan.io": 2.0,
    "api.mnemonic.no": 1.0,
    "keys.openpgp.org": 2.0,
    "_default": 2.0,
}


class BudgetExceeded(RuntimeError):
    pass


class _Bucket:
    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            now = time.monotonic()
            wait = max(0.0, self.next_at - now)
            self.next_at = max(now, self.next_at) + 1.0 / self.rate
        if wait:
            await asyncio.sleep(wait)


@dataclass
class Response:
    url: str
    status: int
    text: str
    from_cache: bool = False

    def json(self) -> Any:
        return json.loads(self.text)


class Fetcher:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path = Path(".eae-cache"),
        max_requests: int = 5000,
        timeout: float = 20.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_requests = max_requests
        self.count = 0
        self._buckets: dict[str, _Bucket] = {}
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json, text/html;q=0.9"},
        )

    def _bucket(self, host: str) -> _Bucket:
        if host not in self._buckets:
            self._buckets[host] = _Bucket(RATE_LIMITS.get(host, RATE_LIMITS["_default"]))
        return self._buckets[host]

    def _cache_path(self, url: str, headers: dict | None) -> Path:
        key = hashlib.sha256((url + json.dumps(headers or {}, sort_keys=True)).encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    async def get(
        self,
        url: str,
        headers: dict | None = None,
        allow_html: bool = False,
    ) -> Response | None:
        cp = self._cache_path(url, headers)
        if cp.exists():
            d = json.loads(cp.read_text())
            return Response(url, d["status"], d["text"], from_cache=True)

        if self.count >= self.max_requests:
            raise BudgetExceeded(f"request budget of {self.max_requests} exhausted")

        host = urlparse(url).netloc
        await self._bucket(host).acquire()
        self.count += 1

        try:
            r = await self._client.get(url, headers=headers)
        except httpx.HTTPError:
            return None

        if r.status_code >= 400:
            return Response(url, r.status_code, "")

        text = r.text
        cp.write_text(json.dumps({"status": r.status_code, "text": text}))
        return Response(url, r.status_code, text)

    async def get_json(self, url: str, headers: dict | None = None) -> Any | None:
        r = await self.get(url, headers)
        if not r or r.status != 200 or not r.text:
            return None
        try:
            return r.json()
        except json.JSONDecodeError:
            return None

    async def aclose(self) -> None:
        await self._client.aclose()
