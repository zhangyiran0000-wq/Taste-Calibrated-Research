"""Rating papers: in a report opened from the page (saved to taste.json), and the rated papers in a profile."""
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

from tastecal.app.serve import make_server  # noqa: E402
from tastecal.taste.profiles import build_profile, load_store, rate_paper, rated_papers  # noqa: E402

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

    def test_rated_papers_round_trip(self):
        text = build_profile("Mine", [{"ref": "Alpha", "score": 0.9, "comment": "clear idea"},
                                      {"ref": "Gamma", "score": 0.1}, {"ref": "Noted", "score": None}])
        self.assertEqual(rated_papers(text), [{"ref": "Alpha", "score": 0.9, "comment": "clear idea"},
                                              {"ref": "Gamma", "score": 0.1, "comment": ""}])

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
