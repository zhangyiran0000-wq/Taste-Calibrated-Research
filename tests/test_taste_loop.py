"""Rating papers: in a report opened from the page (saved to the list its ratings came from), and the rated papers
in a profile."""
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

    def test_rate_in_file_keeps_the_file_shape(self):
        from tastecal.taste.axes import read_table
        from tastecal.taste.profiles import rate_in_file
        base = tempfile.mkdtemp()
        path = os.path.join(base, "ratings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"title": "Planning-oriented Autonomous Driving", "score": 0.7, "comment": "clear interface"}], f)
        r = rate_in_file(path, "VAD: Vectorized Scene Representation", 0.654, "vectors")
        self.assertEqual(r["rated"], 2)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[1], {"title": "VAD: Vectorized Scene Representation", "score": 0.65, "comment": "vectors"})
        rate_in_file(path, "Planning-Oriented Autonomous Driving.", 0.8)     # the same paper: changed, comment kept
        self.assertEqual(read_table(path)[0], {"ref": "Planning-oriented Autonomous Driving", "score": 0.8, "comment": "clear interface"})
        rate_in_file(path, "VAD: Vectorized Scene Representation", None)      # removed
        self.assertEqual(len(read_table(path)), 1)
        new = os.path.join(base, "ratings-new.json")                           # no file yet: a list in the usual keys
        rate_in_file(new, "Alpha", 0.3, "a line")
        with open(new, encoding="utf-8") as f:
            self.assertEqual(json.load(f), [{"paper": "Alpha", "score": 0.3, "reason": "a line"}])
        wrapped = os.path.join(base, "ratings-w.json")
        with open(wrapped, "w", encoding="utf-8") as f:
            json.dump({"note": "mine", "papers": [{"paper": "Beta", "score": 0.5, "reason": "ok"}]}, f)
        rate_in_file(wrapped, "Gamma", 0.9, "great")
        with open(wrapped, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"note": "mine", "papers": [{"paper": "Beta", "score": 0.5, "reason": "ok"},
                                                                       {"paper": "Gamma", "score": 0.9, "reason": "great"}]})

    def test_rating_endpoints(self):
        base = tempfile.mkdtemp()

        def run(rid, req):
            os.makedirs(os.path.join(base, "runs", rid))
            with open(os.path.join(base, "runs", rid, "request.json"), "w") as f:
                json.dump(dict({"seed": "UniAD", "provider": "claude-cli"}, **req), f)
        run("from-a-taste", {"taste_name": "Driving", "taste_key": "driving"})
        run("from-a-file", {"taste_file": "ratings-cv.json"})
        run("from-nothing", {"taste_name": "Gone"})                       # no such taste: ratings.json
        rate_paper("Old paper", 0.4, base=base, profile="driving")       # makes "mine"; "driving" does not exist yet
        store = load_store(base)
        store["profiles"]["driving"] = {"title": "Driving", "papers": [{"ref": "UniAD", "score": 0.8, "comment": "x"}]}
        from tastecal.taste.profiles import save_store
        save_store(store, base)
        with open(os.path.join(base, "ratings-cv.json"), "w") as f:
            json.dump([{"paper": "ResNet", "score": 0.9, "reason": "residuals"}], f)
        srv = make_server(port=0, base=base)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"

        def get(rid):
            with urllib.request.urlopen(f"{url}/api/taste/ratings?group=runs&run={urllib.parse.quote(rid)}") as r:
                return json.loads(r.read())

        def rate(rid, ref, score, comment=""):
            body = json.dumps({"group": "runs", "run": rid, "ref": ref, "score": score, "comment": comment}).encode()
            req = urllib.request.Request(url + "/api/taste/rate", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-TasteCal": "1"})
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        try:
            got = get("from-a-taste")
            self.assertEqual((got["target"], got["title"], [p["ref"] for p in got["papers"]]), ("profile", "Driving", ["UniAD"]))
            self.assertEqual(rate("from-a-taste", "VAD", 0.7, "vectors"), {"target": "profile", "title": "Driving", "rated": 2})
            got = get("from-a-file")
            self.assertEqual((got["target"], got["title"], [p["ref"] for p in got["papers"]]), ("file", "ratings-cv.json", ["ResNet"]))
            self.assertEqual(rate("from-a-file", "ViT", 0.65, "patches")["rated"], 2)
            with open(os.path.join(base, "ratings-cv.json")) as f:
                self.assertEqual(json.load(f)[1], {"paper": "ViT", "score": 0.65, "reason": "patches"})
            self.assertEqual(get("from-nothing"), {"target": "file", "title": "ratings.json", "papers": []})
            self.assertEqual(rate("from-nothing", "VAD", 0.7), {"target": "file", "title": "ratings.json", "rated": 1})
            self.assertTrue(os.path.exists(os.path.join(base, "ratings.json")))
            self.assertEqual([p["ref"] for p in load_store(base)["profiles"]["mine"]["papers"]], ["Old paper"])   # untouched
            body = json.dumps({"group": "runs", "run": "from-nothing", "ref": "VAD", "score": 0.7}).encode()
            bad = urllib.request.Request(url + "/api/taste/rate", data=body, method="POST", headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad)                                   # the page's header is required
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
