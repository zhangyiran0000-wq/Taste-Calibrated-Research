"""Stability: cache expiry, gap filling on resume, Retry-After, and readable `claude -p` errors."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core import http as H  # noqa: E402
from tastecal.core.http import Http, HttpError, kind_of, retry_after_seconds  # noqa: E402
from tastecal.core.llm import LLM, ClaudeCLILLM  # noqa: E402

SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search?query=x"
RECORD = "https://api.semanticscholar.org/graph/v1/paper/abc?fields=title"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(**kw):
    h = Http(tempfile.mkdtemp(), **kw)
    h.clock = Clock()
    h.sleeper = lambda s: None
    return h


class CacheExpiryTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(kind_of("GET " + SEARCH), "fresh")
        self.assertEqual(kind_of("GET https://api.openalex.org/works?filter=cites%3AW1"), "fresh")
        self.assertEqual(kind_of("GET " + RECORD), "meta")
        self.assertEqual(kind_of("TEXT https://arxiv.org/html/1"), "text")

    def test_fresh_lists_expire_and_are_fetched_again(self):
        h = make(fresh_days=14)
        h._cache_put("GET " + SEARCH, {"data": ["old"]})
        calls = []
        h._send = lambda req, timeout, retries: calls.append(1) or b'{"data": ["new"]}'
        self.assertEqual(h.get_json(SEARCH), {"data": ["old"]})       # still fresh
        h.clock.t += 15 * H.DAY
        self.assertEqual(h.get_json(SEARCH), {"data": ["new"]})       # expired: fetched again
        self.assertEqual(len(calls), 1)

    def test_records_last_longer(self):
        h = make(fresh_days=14, meta_days=60)
        h._cache_put("GET " + RECORD, {"title": "t"})
        h._send = lambda *a: self.fail("should not fetch")
        h.clock.t += 30 * H.DAY
        self.assertEqual(h.get_json(RECORD), {"title": "t"})

    def test_refresh_forces_lists_only(self):
        h = make(refresh=True)
        h._cache_put("GET " + SEARCH, {"data": ["old"]})
        h._cache_put("GET " + RECORD, {"title": "t"})
        h._send = lambda req, timeout, retries: b'{"data": ["new"]}'
        self.assertEqual(h.get_json(SEARCH), {"data": ["new"]})
        self.assertEqual(h.get_json(RECORD), {"title": "t"})

    def test_failed_refresh_falls_back_to_the_old_copy(self):
        h = make(fresh_days=1)
        h._cache_put("GET " + SEARCH, {"data": ["old"]})
        h.clock.t += 3 * H.DAY

        def boom(*a):
            raise HttpError(429, SEARCH, "slow down")
        h._send = boom
        self.assertEqual(h.get_json(SEARCH), {"data": ["old"]})
        self.assertEqual(h.stale_used, 1)

    def test_replay_ignores_expiry(self):
        h = make(fresh_days=1)
        h._cache_put("GET " + SEARCH, {"data": ["old"]})
        h.clock.t += 30 * H.DAY
        h.replay = True
        h._send = lambda *a: self.fail("replay must not fetch")
        self.assertEqual(h.get_json(SEARCH), {"data": ["old"]})

    def test_old_cache_entries_still_read(self):
        h = make()
        p = h._cache_path("GET " + RECORD)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"title": "legacy"}, f)
        self.assertEqual(h.get_json(RECORD), {"title": "legacy"})


class GapTest(unittest.TestCase):
    def test_passing_failures_are_recorded_and_filled_on_resume(self):
        run = tempfile.mkdtemp()
        gaps = os.path.join(run, "gaps.json")
        h = make()
        h.gaps_path = gaps

        def refused(*a):
            raise HttpError(429, SEARCH, "too many")
        h._send = refused
        with self.assertRaises(HttpError):
            h.get_json(SEARCH)
        with open(gaps, encoding="utf-8") as f:
            self.assertEqual([r["key"] for r in json.load(f)], ["GET " + SEARCH])

        h2 = Http(h.cache_dir.rsplit(os.sep, 1)[0])
        h2.clock, h2.sleeper = Clock(), (lambda s: None)
        self.assertEqual(h2.load_gaps(gaps), 1)
        h2.replay = True
        h2._send = lambda *a: b'{"data": [1]}'
        self.assertEqual(h2.get_json(SEARCH), {"data": [1]})     # a gap goes live even while replaying
        self.assertEqual(h2.filled, 1)
        self.assertFalse(h2.replay)                               # the run now differs from the old one
        with open(gaps, encoding="utf-8") as f:
            self.assertEqual(json.load(f), [])

    def test_not_found_is_not_a_gap(self):
        h = make()
        h.gaps_path = os.path.join(tempfile.mkdtemp(), "gaps.json")

        def missing(*a):
            raise HttpError(404, RECORD, "no")
        h._send = missing
        with self.assertRaises(HttpError):
            h.get_json(RECORD)
        self.assertEqual(h.gaps, {})

    def test_gaps_from_an_old_log(self):
        run = tempfile.mkdtemp()
        with open(os.path.join(run, "run.log"), "w", encoding="utf-8") as f:
            f.write(f'15:56:22 tastecal.s2: S2 search failed for \'x\': HTTP 429 for {SEARCH}: {{"message": "Too Many"}}\n')
        h = make()
        h.gaps_path = os.path.join(run, "gaps.json")
        self.assertEqual(h.gaps_from_log(os.path.join(run, "run.log")), 1)
        self.assertIn("GET " + SEARCH, h.retry)


class SpacingTest(unittest.TestCase):
    def test_429_widens_the_spacing_and_success_relaxes_it(self):
        import io
        import urllib.error
        h = make(min_interval=0.0)
        answers = [urllib.error.HTTPError("u", 429, "slow", {}, io.BytesIO(b""))] + [b"{}"] * 30

        def fake_open(req, timeout=None):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a

            class R:
                def __enter__(self):
                    return self

                def __exit__(self, *x):
                    return False

                def read(self):
                    return a
            return R()
        H.urllib.request.urlopen, saved = fake_open, H.urllib.request.urlopen
        try:
            h.get_json(RECORD, cache=False)
            self.assertGreater(h.min_interval, 0)
            for _ in range(29):
                h.get_json(RECORD, cache=False)
            self.assertLess(h.min_interval, 0.01)       # back to the default after a run of answers
        finally:
            H.urllib.request.urlopen = saved


class RetryAfterTest(unittest.TestCase):
    def test_seconds_and_dates(self):
        self.assertEqual(retry_after_seconds("7"), 7.0)
        self.assertAlmostEqual(retry_after_seconds("Wed, 21 Oct 2015 07:28:10 GMT", now=1445412480.0), 10.0, places=0)
        self.assertIsNone(retry_after_seconds("soon"))
        self.assertIsNone(retry_after_seconds(None))


class ClaudeErrorTextTest(unittest.TestCase):
    def test_null_result_still_says_something(self):
        msg = ClaudeCLILLM._error_text({"type": "result", "is_error": True, "result": None,
                                     "subtype": "error_during_execution"}, "")
        self.assertIn("error_during_execution", msg)
        self.assertNotEqual(msg.strip(), "None")
        self.assertTrue(LLM.TRANSIENT.search("claude -p reported an error: " + msg))

    def test_empty_everything(self):
        msg = ClaudeCLILLM._error_text({"is_error": True, "result": None}, "")
        self.assertTrue(LLM.TRANSIENT.search(msg))

    def test_real_message_kept(self):
        msg = ClaudeCLILLM._error_text({"is_error": True, "result": "Claude usage limit reached", "subtype": "success"})
        self.assertEqual(msg, "Claude usage limit reached")


if __name__ == "__main__":
    unittest.main()
