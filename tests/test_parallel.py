"""Several runs sharing one cache folder: writes are atomic, half-written or empty entries count as misses."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.files import atomic_write  # noqa: E402
from tastecal.core.http import Http  # noqa: E402
from tastecal.core.llm import LLM  # noqa: E402


class Echo(LLM):
    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        self.live = 0

    def _retrying(self, system, prompt, max_tokens):
        self.live += 1
        return "answer " + prompt


class ParallelCacheTest(unittest.TestCase):
    def test_concurrent_writers_leave_one_whole_file(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "entry.json")
        texts = [("x%d" % i) * 5000 for i in range(8)]
        threads = [threading.Thread(target=atomic_write, args=(p, t)) for t in texts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with open(p, encoding="utf-8") as f:
            self.assertIn(f.read(), texts)
        self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])

    def test_two_runs_share_the_llm_cache(self):
        d = tempfile.mkdtemp()
        a, b = Echo(d), Echo(d)
        self.assertEqual(a.complete("s", "p"), "answer p")
        self.assertEqual(b.complete("s", "p"), "answer p")
        self.assertEqual((a.live, b.live), (1, 0))

    def test_empty_cache_entry_is_a_miss(self):
        d = tempfile.mkdtemp()
        a = Echo(d)
        path = os.path.join(a.cache_dir, a._key("s", "q") + ".txt")
        open(path, "w").close()
        self.assertEqual(a.complete("s", "q"), "answer q")
        self.assertEqual(a.live, 1)

    def test_http_cache_round_trip(self):
        h = Http(tempfile.mkdtemp())
        h._cache_put("GET https://x.org/a", {"v": 1})
        self.assertEqual(h._cache_get("GET https://x.org/a"), {"v": 1})


if __name__ == "__main__":
    unittest.main()
