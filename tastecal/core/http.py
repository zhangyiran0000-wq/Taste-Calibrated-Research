"""Tiny stdlib HTTP layer: JSON GET/POST with retries, backoff and a disk cache.

Cache entries carry the time they were fetched. Lists that change as the field moves on (search results,
"who cites this") expire after `fresh_days`; paper records after `meta_days`; page text never. An expired
entry is fetched again, and kept as a fallback if the new request fails. A resume (replay) ignores expiry,
so it takes the same path as the run it continues.

Requests that fail for a passing reason (HTTP 429, 5xx, network) are written to a gaps file. A resume replays
from the cache until it reaches a request the cache does not hold (where the earlier attempt stopped, or one of
its gaps); from there it continues live, so it neither stops at the cached papers nor leaves the gaps empty.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Set

log = logging.getLogger("tastecal.http")

USER_AGENT = "tastecal/0.1 (+taste-calibrated research)"


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status
        self.url = url
        self.body = body


DAY = 86400.0
ENVELOPE = "__tastecal_cache__"
# Requests whose answer changes as new papers appear: search results and citing-paper lists.
FRESH_MARKERS = ("/search", "/citations", "search=", "cites:", "cites%3A", "cited_by", "query=")
PASSING = (0, 429, 500, 502, 503, 504, 529)   # failures worth trying again later (a gap), not "not found"


def kind_of(key: str) -> str:
    """'fresh' (lists that grow), 'meta' (a paper record) or 'text' (a page or full text)."""
    if key.startswith(("TEXT ", "PDFTEXT ")):
        return "text"
    return "fresh" if any(m in key for m in FRESH_MARKERS) else "meta"


def retry_after_seconds(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """Seconds to wait from a Retry-After header: a number of seconds or an HTTP date. None when absent or bad."""
    if not value:
        return None
    value = value.strip()
    if value.replace(".", "", 1).isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, IndexError):
        return None
    return max(0.0, when - (now if now is not None else time.time()))


class Http:
    def __init__(self, cache_dir: Optional[str] = None, min_interval: float = 0.0,
                 fresh_days: float = 14.0, meta_days: float = 60.0, refresh: bool = False):
        self.cache_dir = os.path.join(cache_dir, "http") if cache_dir else None
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
        self.min_interval = min_interval  # polite spacing between live requests
        self.base_interval = min_interval # what the spacing relaxes back to after a burst of HTTP 429
        self._last = 0.0
        self.fresh_days = fresh_days      # search results and citer lists older than this are fetched again
        self.meta_days = meta_days        # paper records older than this are fetched again
        self.refresh = refresh            # True: every search and citer list is fetched again (--refresh)
        self.clock = time.time
        self.sleeper = time.sleep
        # Replay (used when resuming a run): cached downloads are used whatever their age, so the run retraces the
        # earlier attempt. The first request that is not in the cache (where the earlier attempt stopped, or one it
        # failed to get) ends the replay, and the run continues live from there.
        self.replay = False
        self.retry: Set[str] = set()
        self.gaps_path: Optional[str] = None   # where failed requests are written (runs/<run>/gaps.json)
        self.gaps: Dict[str, dict] = {}
        self.filled = 0                        # gaps fetched successfully in this run
        self.stale_used = 0                    # expired entries used because a new fetch failed
        self.rate_limited = 0                  # 429 answers seen
        # sources whose 429 means a daily allowance is spent (daily_limited): host -> retries, host -> why it is not
        # asked again in this run, host -> params sent with each request (an API key) but kept out of the cache key,
        # the gaps file, the log and every error
        self.fail_fast: Dict[str, int] = {}
        self.off: Dict[str, str] = {}
        self.secrets: Dict[str, Dict[str, str]] = {}

    def daily_limited(self, host: str, retries: int = 2, secret: Optional[Dict[str, str]] = None) -> None:
        """A source whose 429 means its daily allowance is used up: a 429 is final (no waiting, no retry), and once it
        refuses it is not asked again in this run (answers already cached are still used); other failures get few
        retries. `secret`: request parameters such as an API
        key, added to every request to it and never written anywhere."""
        self.fail_fast[host] = retries
        sec = {k: v for k, v in (secret or {}).items() if v}
        if sec:
            self.secrets[host] = sec
        else:
            self.secrets.pop(host, None)

    def _scrub(self, text: str) -> str:
        for sec in self.secrets.values():
            for v in sec.values():
                text = text.replace(v, "***").replace(urllib.parse.quote(v, safe=""), "***")
        return text

    # -- gaps ----------------------------------------------------------------
    def load_gaps(self, path: str) -> int:
        """Read an earlier run's gaps file; its requests may go live during a replay. Returns how many."""
        self.gaps_path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            rows = []
        self.gaps = {r["key"]: r for r in rows if isinstance(r, dict) and r.get("key")}
        self.retry = set(self.gaps)
        return len(self.retry)

    def gaps_from_log(self, log_path: str) -> int:
        """For runs made before gaps files existed: take the failed requests from run.log
        ("HTTP 429 for <url>"). Returns how many were found."""
        import re
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return 0
        for m in re.finditer(r"HTTP (429|5\d\d|0) for (https?://\S+?):? ", text):
            key = "GET " + m.group(2)
            if key not in self.gaps and self._cache_get(key) is None:
                self.gaps[key] = {"key": key, "status": int(m.group(1)), "tries": 1, "last": "", "from": "run.log"}
        self.retry = set(self.gaps)
        self._save_gaps()
        return len(self.gaps)

    def _save_gaps(self) -> None:
        if not self.gaps_path:
            return
        try:
            tmp = self.gaps_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self.gaps.values()), f, indent=1)
            os.replace(tmp, self.gaps_path)
        except OSError as e:
            log.info("could not write the gaps file: %s", e)

    def _gap(self, key: str, err: "HttpError") -> None:
        if err.status not in PASSING:
            return
        row = self.gaps.get(key) or {"key": key, "tries": 0}
        row.update(status=err.status, tries=row["tries"] + 1, last=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.gaps[key] = row
        self._save_gaps()

    def _filled(self, key: str) -> None:
        if key in self.gaps:
            del self.gaps[key]
            self.filled += 1
            self._save_gaps()
        self.retry.discard(key)

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, key: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
        return os.path.join(self.cache_dir, h + ".json")

    def _cache_entry(self, key: str):
        """(value, fetched_at) or (None, None). Older entries without a time use the file's time."""
        p = self._cache_path(key)
        if not (p and os.path.exists(p)):
            return None, None
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return None, None
        if isinstance(raw, dict) and raw.get(ENVELOPE) == 1:
            return raw.get("v"), float(raw.get("t") or 0)
        return raw, os.path.getmtime(p)

    def _cache_get(self, key: str) -> Any:
        return self._cache_entry(key)[0]

    def _cache_put(self, key: str, value: Any) -> None:
        p = self._cache_path(key)
        if p:
            from tastecal.core.files import atomic_write
            atomic_write(p, json.dumps({ENVELOPE: 1, "t": self.clock(), "v": value}))

    def _expired(self, key: str, fetched_at: float) -> bool:
        kind = kind_of(key)
        if kind == "text":
            return False
        if kind == "fresh" and self.refresh:
            return True
        days = self.fresh_days if kind == "fresh" else self.meta_days
        return days > 0 and (self.clock() - fetched_at) > days * DAY

    def _cached_or_live(self, key: str, url: str, cache: bool, fetch):
        """The cached value when it is fresh enough; otherwise fetch it (falling back to a stale copy on failure)."""
        stale = None
        if cache:
            hit, t = self._cache_entry(key)
            if hit is not None:
                if self.replay or not self._expired(key, t):
                    return hit
                stale = hit
        host = urllib.parse.urlsplit(url).hostname or ""
        if host in self.off:                     # it refused earlier in this run: not asked again
            if stale is not None:
                self.stale_used += 1
                return stale
            raise HttpError(429, url, f"not asked again: {self.off[host]}")
        if self.replay:
            # The earlier attempt never got this far (it stopped here), or this request failed then: either way the
            # replay is over. Go live from here on; cached downloads are still used, only missing ones are fetched.
            self.replay = False
            log.info("resume: caught up with the earlier attempt; continuing live from here")
        try:
            value = fetch()
        except HttpError as e:
            self._gap(key, e)
            if stale is not None:
                self.stale_used += 1
                log.info("using the cached copy from an earlier run (a new fetch failed: HTTP %s): %s", e.status, url[:120])
                return stale
            raise
        if cache:
            self._cache_put(key, value)
        self._filled(key)
        return value

    # -- requests --------------------------------------------------------------
    def _send(self, req: urllib.request.Request, timeout: float, retries: int) -> bytes:
        delay = 2.0
        host = urllib.parse.urlsplit(req.full_url).hostname or ""
        if host in self.fail_fast:
            retries = min(retries, self.fail_fast[host])
        real = req                               # what is sent; `req` (without the secret) is what is shown
        sec = self.secrets.get(host)
        if sec and req.get_method() == "GET":
            real = urllib.request.Request(req.full_url + ("&" if "?" in req.full_url else "?") + urllib.parse.urlencode(sec),
                                          headers=dict(req.header_items()))
        for attempt in range(retries + 1):
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleeper(wait)
            self._last = self.clock()
            try:
                with urllib.request.urlopen(real, timeout=timeout) as resp:
                    data = resp.read()
                # Answered: relax the spacing a 429 widened, step by step, back to the polite default.
                if self.min_interval > self.base_interval:
                    self.min_interval = max(self.base_interval, self.min_interval * 0.85)
                return data
            except urllib.error.HTTPError as e:
                body = self._scrub(e.read().decode("utf-8", "replace") if hasattr(e, "read") else "")
                if e.code == 429:
                    self.rate_limited += 1
                    # Slow every later request down too: a refused burst means the shared pool is busy.
                    self.min_interval = min(max(self.min_interval * 1.5, 1.1), 5.0)
                spent = e.code == 429 and host in self.fail_fast     # a daily allowance used up: waiting will not help
                if e.code in (429, 500, 502, 503, 504, 529) and attempt < retries and not spent:
                    told = retry_after_seconds(e.headers.get("Retry-After") if e.headers else None, self.clock())
                    base = delay * (2.5 if e.code == 429 else 1.0)
                    sleep_for = min(told if told is not None else base * (0.8 + 0.4 * random.random()), 120.0)
                    log.info("HTTP %s, retrying in %.1fs: %s", e.code, sleep_for, req.full_url[:120])
                    self.sleeper(sleep_for)
                    delay = min(delay * 2, 60)
                    continue
                if spent and host not in self.off:
                    self.off[host] = "it answered HTTP 429: its daily allowance is used up"
                    log.warning("%s refused with HTTP 429: its daily allowance is used up (%s). It is not asked again "
                                "in this run; answers already cached are still used.", host,
                                "with your API key" if host in self.secrets else "no API key was set")
                raise HttpError(e.code, req.full_url, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < retries:
                    log.info("Network error (%s), retrying in %.1fs", self._scrub(str(e)), delay)
                    self.sleeper(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise HttpError(0, req.full_url, self._scrub(str(e)))
        raise HttpError(0, req.full_url, "exhausted retries")

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None, cache: bool = True,
                 timeout: float = 40, retries: int = 6) -> Any:
        if params:
            q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None and v != ""})
            url = url + ("&" if "?" in url else "?") + q
        h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        h.update(headers or {})

        def fetch():
            raw = self._send(urllib.request.Request(url, headers=h), timeout, retries)
            return json.loads(raw.decode("utf-8"))
        return self._cached_or_live("GET " + url, url, cache, fetch)

    def post_json(self, url: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None,
                  timeout: float = 180, retries: int = 4) -> Any:
        h = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
        raw = self._send(req, timeout, retries)
        return json.loads(raw.decode("utf-8"))

    def get_text(self, url: str, cache: bool = True, timeout: float = 30, max_bytes: int = 2_000_000) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})

        def fetch():
            return self._send(req, timeout, 2)[:max_bytes].decode("utf-8", "replace")
        return self._cached_or_live("TEXT " + url, url, cache, fetch)

    def get_bytes(self, url: str, timeout: float = 60, max_bytes: int = 40_000_000) -> bytes:
        """Raw bytes (for PDFs). Not cached: callers cache what they extract."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
        return self._send(req, timeout, 2)[:max_bytes]
