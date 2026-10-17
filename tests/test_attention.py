"""Hidden gems: attention is ranked against the neighbourhood, absolute ceilings apply, and the counts are checked."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.judge.audit import Thresholds, assess_packs, attention, final_flag, noticed  # noqa: E402

TH = Thresholds()
TODAY = "2026-10"


def pack(pid, cites, date="2023-06", **kw):
    return dict({"id": pid, "title": pid, "date": date, "citations": cites, "citations_lower_bound": False}, **kw)


# A map of famous works: within it, a work with 800 citations is near the bottom.
MAP = [pack("famous" + str(i), 5000 + 1000 * i) for i in range(6)] + [pack("voxposer", 800)]
# What the grower saw around them: mostly ordinary papers.
NEAR = [{"citations": c, "date": "2024-01"} for c in range(0, 120, 2)]


class AttentionTest(unittest.TestCase):
    def test_map_alone_makes_a_cited_work_look_unnoticed(self):
        a = attention(MAP, TODAY)
        self.assertLess(a["voxposer"]["pct"], 0.2)
        self.assertEqual(a["voxposer"]["reference"], "assessed")

    def test_neighbourhood_reference_fixes_it(self):
        a = attention(MAP, TODAY, NEAR)
        self.assertGreater(a["voxposer"]["pct"], 0.8)
        self.assertIn("neighbourhood", a["voxposer"]["reference"])

    def test_small_reference_is_ignored(self):
        a = attention(MAP, TODAY, NEAR[:5])
        self.assertEqual(a["voxposer"]["reference"], "assessed")

    def test_absolute_ceilings(self):
        a = attention(MAP, TODAY)
        self.assertIn("citations", noticed(MAP[-1], a["voxposer"], TH))
        quiet = pack("quiet", 30)
        self.assertEqual(noticed(quiet, {"citations_per_year": 9.0}, TH), "")
        self.assertIn("top", noticed(dict(quiet, field_pct=0.97), {"citations_per_year": 9.0}, TH))

    def test_noticed_work_is_never_a_gem_candidate(self):
        scores = {p["id"]: {"score": 0.7 if p["id"] == "voxposer" else 0.5} for p in MAP}
        out = assess_packs(MAP, scores, TODAY, TH)          # map-only ranking: it falls in the "gem" quadrant
        self.assertEqual(out["voxposer"]["quadrant"], "gem")
        self.assertEqual(out["voxposer"]["candidate"], "")
        self.assertIn("Not an unnoticed work", out["voxposer"]["gem_blocked"])

    def test_attention_check_can_overrule_the_judge(self):
        self.assertEqual(final_flag("hidden-gem", {"verdict": "substantial"}, 40, TH), "hidden-gem")
        self.assertEqual(final_flag("hidden-gem", {"verdict": "substantial", "under_noticed": False}, 40, TH), "fair")
        self.assertEqual(final_flag("hidden-gem", {"verdict": "substantial", "under_noticed": True}, 40, TH), "hidden-gem")

    def test_review_attention_is_read(self):
        packs = [pack("quiet", 20)] + [pack(f"loud{i}", 3000 + i) for i in range(5)]
        scores = {p["id"]: {"score": 0.75 if p["id"] == "quiet" else 0.5} for p in packs}
        first = assess_packs(packs, scores, TODAY, TH)
        self.assertEqual(first["quiet"]["candidate"], "hidden-gem")
        rev = {"quiet": {"judge": {"verdict": "substantial"}, "attention": {"verdict": "well noticed", "why": "x"}}}
        self.assertEqual(assess_packs(packs, scores, TODAY, TH, rev)["quiet"]["flag"], "fair")
        rev["quiet"]["attention"]["verdict"] = "under-noticed"
        self.assertEqual(assess_packs(packs, scores, TODAY, TH, rev)["quiet"]["flag"], "hidden-gem")


if __name__ == "__main__":
    unittest.main()
