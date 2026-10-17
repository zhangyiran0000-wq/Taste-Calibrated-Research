"""Papers you rated set 'your scale': they are scored blind like the rest, the blind score is fitted to your
ratings, and each work shows both. Your ratings never reach the scorer."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.judge.audit import Auditor, Thresholds, audit  # noqa: E402
from tastecal.taste.calibration import on_your_scale, your_scale  # noqa: E402
from tastecal.core.config import Config  # noqa: E402
from tastecal.core.model import Item  # noqa: E402
from tastecal.report.render import render_html  # noqa: E402
from tastecal.taste.profiles import build_profile, rated_papers  # noqa: E402

BLIND = {"Alpha": 0.8, "Beta": 0.5, "Gamma": 0.2, "Delta": 0.6, "Map Work": 0.7}


class Src:
    def resolve(self, ref):
        if ref == "Missing":
            raise LookupError("no")
        return Item(id="s2:" + ref.lower(), title=ref, year=2020, url=f"https://example.org/{ref}")


class LLM:
    def __init__(self):
        self.prompts = []

    def json(self, system, prompt):
        self.prompts.append(prompt)
        return [{"id": "x", "short": "X"}]


class FakeAuditor(Auditor):
    def gather(self, item, card, short="", challenges=None, reading=None):
        return {"id": item.id, "title": item.title, "short": short, "date": "2020"}

    def score(self, pack):
        return {"score": BLIND[pack["title"]]}


class YourScaleTest(unittest.TestCase):
    def test_rated_papers_round_trip(self):
        text = build_profile("Mine", "I like mechanisms.", [{"ref": "Alpha", "score": 0.9, "comment": "clear idea"},
                                                            {"ref": "Gamma", "score": 0.1}, {"ref": "Noted", "score": None}])
        self.assertEqual(rated_papers(text), [{"ref": "Alpha", "score": 0.9, "comment": "clear idea"},
                                              {"ref": "Gamma", "score": 0.1, "comment": ""}])

    def test_rated_papers_are_read_like_map_papers(self):
        seen = []

        def reader(node, item):
            seen.append(node["title"])
            return {"basis": "full text", "source": "arXiv HTML", "claimed": "c", "delivery": "partial",
                    "delivered": "only open-loop averages", "reason_type": "analogy", "reason": "game theory",
                    "robustness": "single", "robustness_note": "one benchmark", "levers": []}
        au = FakeAuditor(Config(), Src(), LLM(), reader=reader)
        cal = au.calibrate([{"ref": "Alpha", "score": 0.9}, {"ref": "Gamma", "score": 0.3}, {"ref": "Map Work", "score": 0.7}],
                           [{"id": "map-work", "title": "Map Work"}], {"map-work": {"contribution": {"score": 0.7}}},
                           readings={"map-work": {"basis": "abstract", "claimed": "c", "delivery": "delivered",
                                                  "reason_type": "none", "robustness": "single", "levers": []}})
        rows = {r["ref"]: r for r in cal["anchors"]}
        self.assertEqual(seen, ["Alpha", "Gamma"])                  # off-map rated papers get the careful read
        self.assertEqual((rows["Alpha"]["basis"], rows["Alpha"]["source"]), ("full text", "arXiv HTML"))
        self.assertIn("open-loop", rows["Gamma"]["evidence"])
        self.assertEqual(rows["Map Work"]["basis"], "abstract")     # on the map: the map's own reading

    def test_fit(self):
        fit = your_scale([(0.8, 0.9), (0.5, 0.5), (0.2, 0.1)])
        self.assertTrue(fit["usable"])
        self.assertEqual((fit["agree"], fit["pairs"]), (3.0, 3))
        self.assertAlmostEqual(on_your_scale(0.5, fit), 0.5, places=2)
        self.assertGreater(on_your_scale(0.7, fit), 0.7)                      # your scale is steeper here
        self.assertFalse(your_scale([(0.8, 0.1), (0.5, 0.5), (0.2, 0.9)])["usable"])   # disagrees: not used
        self.assertFalse(your_scale([(0.8, 0.9), (0.2, 0.1)])["usable"])               # too few
        self.assertIsNone(on_your_scale(0.5, {"usable": False}))

    def test_calibrate_reuses_map_scores_and_hides_ratings(self):
        llm = LLM()
        au = FakeAuditor(Config(), Src(), llm)
        packs = [{"id": "map-work", "title": "Map Work"}]
        assessments = {"map-work": {"contribution": {"score": 0.7}}}
        cal = au.calibrate([{"ref": "Alpha", "score": 0.9}, {"ref": "Gamma", "score": 0.1, "comment": "secret dislike"},
                            {"ref": "Map Work", "score": 0.75}, {"ref": "Missing", "score": 0.5}], packs, assessments)
        rows = {r["ref"]: r for r in cal["anchors"]}
        self.assertEqual(rows["Map Work"]["on_map"], "map-work")              # already assessed: reused, not re-scored
        self.assertFalse(rows["Missing"]["found"])
        self.assertTrue(cal["usable"])
        self.assertFalse(any("0.9" in p or "secret" in p for p in llm.prompts))   # the scorer never sees your ratings

    def test_audit_attaches_your_scale_and_report_shows_it(self):
        class A(FakeAuditor):
            def run(self, packs, reference=None):
                return {p["id"]: {"contribution": {"score": BLIND[p["title"]]}, "attention": {"pct": 0.5}, "flag": "fair",
                                  "label": "Fairly valued", "candidate": "", "why": ""} for p in packs}
        au = A(Config(), Src(), LLM())
        g = {"meta": {"seed": "map-work"}, "nodes": [{"id": "map-work", "title": "Map Work", "short": "MW", "kind": "paper",
                                                     "date": "2020", "threads": ["t"], "card": {"summary": "s"}, "role": "seed"}],
             "edges": [], "threads": [{"id": "t", "name": "T"}], "field": {}, "problems": []}
        targets = [{"item": Item(id="map-work", title="Map Work", year=2020), "card": {}, "short": "MW"}]
        audit(g, targets, au, anchors=[{"ref": "Alpha", "score": 0.9}, {"ref": "Beta", "score": 0.5}, {"ref": "Gamma", "score": 0.1}])
        a = g["nodes"][0]["assessment"]
        self.assertEqual(a["contribution"]["score"], 0.7)                    # the blind score is unchanged
        self.assertIn("your_scale", a)
        self.assertTrue(g["audit"]["calibration"]["usable"])
        html = render_html(g)
        self.assertIn("On your scale", html)
        g["meta"]["language"] = "zh-CN"
        self.assertIn("按你的尺度", render_html(g))


if __name__ == "__main__":
    unittest.main()
