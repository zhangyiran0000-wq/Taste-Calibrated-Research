"""Taste calibration loop: rate papers in a report (saved to taste.json), check how well the profile predicts
your ratings with each paper's own rating held out, and order the reading list by your scale."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.taste.calibration import pair_agreement, taste_check  # noqa: E402
from tastecal.core.model import Item  # noqa: E402
from tastecal.app.serve import make_server  # noqa: E402
from tastecal.taste.profiles import build_profile, drop_rated, load_store, rate_paper, rated_papers  # noqa: E402

RATED = [{"ref": "Alpha", "score": 0.9}, {"ref": "Beta", "score": 0.6}, {"ref": "Gamma", "score": 0.3},
         {"ref": "Delta", "score": 0.1}]


class Src:
    def resolve(self, ref):
        if ref == "Missing":
            raise LookupError(ref)
        return Item(id="s2:" + ref.lower(), title=ref, url=f"https://example.org/{ref}")


class TasteLLM:
    """Cards echo the title; taste scores follow a hidden truth, and must never see the held-out paper's own line."""
    TRUTH = {"Alpha": 0.8, "Beta": 0.55, "Gamma": 0.35, "Delta": 0.2}

    def __init__(self):
        self.leaks = 0

    def json(self, system, prompt):
        task = prompt.split("\n", 1)[0]
        if task == "TASK: cards":
            ids = [ln.split("]")[0][1:] for ln in prompt.splitlines() if ln.startswith("[s2:")]
            return [{"id": i, "short": i.split(":")[1].title()} for i in ids]
        rows = [ln for ln in prompt.splitlines() if ln.startswith("[r")]
        out = {}
        for ln in rows:
            rid, short = ln[1:].split("]", 1)[0], ln.split("] ", 1)[1].split(":", 1)[0]
            if f"- {short} (my score" in prompt:
                self.leaks += 1
            out[rid] = {"score": self.TRUTH[short], "why": "close to what you like"}
        return out


class TasteLoopTest(unittest.TestCase):
    def test_rate_paper_upserts_and_removes(self):
        base = tempfile.mkdtemp()
        r = rate_paper("Planning-oriented Autonomous Driving", 0.9, "clear interface idea", base=base)
        self.assertEqual((r["profile"], r["rated"]), ("mine", 1))
        self.assertEqual(load_store(base)["default"], "mine")
        r = rate_paper("planning oriented autonomous driving", 0.7, base=base)          # same paper, new score
        self.assertEqual(r["rated"], 1)
        self.assertEqual(load_store(base)["profiles"]["mine"]["papers"][0]["score"], 0.7)
        self.assertEqual(load_store(base)["profiles"]["mine"]["papers"][0]["comment"], "clear interface idea")
        self.assertEqual(rate_paper("Planning-oriented Autonomous Driving", None, base=base)["rated"], 0)

    def test_drop_rated(self):
        text = build_profile("Mine", "I like mechanisms.", RATED)
        kept = rated_papers(drop_rated(text, ["Beta", "Delta"]))
        self.assertEqual([p["ref"] for p in kept], ["Alpha", "Gamma"])
        self.assertIn("I like mechanisms.", drop_rated(text, ["Beta"]))

    def test_check_holds_each_paper_out(self):
        llm = TasteLLM()
        tc = taste_check(build_profile("Mine", "", RATED + [{"ref": "Missing", "score": 0.5}]), Src(), llm)
        self.assertEqual(llm.leaks, 0)                          # no paper was scored with its own rating in view
        self.assertTrue(tc["usable"])
        self.assertEqual((tc["n"], tc["agree"], tc["pairs"], tc["not_found"]), (4, 6.0, 6, 1))
        self.assertAlmostEqual(tc["gap"], 0.075, delta=0.006)               # mean of 0.1, 0.05, 0.05, 0.1
        self.assertIsNone(taste_check("# Mine\n\nNo papers.", Src(), llm))
        self.assertFalse(taste_check(build_profile("Mine", "", RATED[:2]), Src(), llm)["usable"])
        self.assertEqual(pair_agreement([(0.5, 0.9), (0.5, 0.1)]), (0.5, 1))

    def test_rating_endpoints(self):
        base = tempfile.mkdtemp()
        rid = "uniad-20261017-0900"
        os.makedirs(os.path.join(base, "runs", rid))
        with open(os.path.join(base, "runs", rid, "request.json"), "w") as f:
            json.dump({"seed": "UniAD", "provider": "claude-cli", "taste_name": "Driving"}, f)
        rate_paper("Old paper", 0.4, base=base, profile="driving")       # makes "mine"; "driving" does not exist yet
        srv = make_server(port=0, base=base)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            with urllib.request.urlopen(f"{url}/api/taste/ratings?group=runs&run={urllib.parse.quote(rid)}") as r:
                got = json.loads(r.read())
            self.assertEqual((got["profile"], [p["ref"] for p in got["papers"]]), ("mine", ["Old paper"]))
            body = json.dumps({"group": "runs", "run": rid, "ref": "VAD", "score": 0.7, "comment": "vectors"}).encode()
            req = urllib.request.Request(url + "/api/taste/rate", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-TasteCal": "1"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(json.loads(r.read()), {"profile": "mine", "title": "Mine", "rated": 2})
            bad = urllib.request.Request(url + "/api/taste/rate", data=body, method="POST", headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad)                                   # the page's header is required
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
