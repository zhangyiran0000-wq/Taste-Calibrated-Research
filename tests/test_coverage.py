"""Every paper on the map is read and audited by default; a limit keeps the seed and the most connected works,
not the oldest; the report says which papers were left out and why."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.config import Config  # noqa: E402
from tastecal.judge.gates import Gatekeeper  # noqa: E402
from tastecal.judge.quality import note_coverage, pick_for_reading  # noqa: E402


def graph(n=10):
    nodes = [{"id": f"p{i}", "short": f"P{i}", "kind": "paper", "date": f"20{10 + i}-01", "role": "seed" if i == 0 else ""}
             for i in range(n)]
    edges = [{"source": "p0", "target": f"p{i}"} for i in (8, 9)] + [{"source": "p8", "target": "p9"}]
    return {"meta": {"seed": "p0"}, "nodes": nodes, "edges": edges}


class CoverageTest(unittest.TestCase):
    def test_defaults_cover_everything(self):
        self.assertEqual((Config().gates_max, Config().assess_max), (0, 0))
        g = graph(80)
        self.assertEqual(len(Gatekeeper(Config(), None).targets(g)), 80)

    def test_limit_keeps_connected_and_recent_not_oldest(self):
        g = graph(10)
        picked = [n["id"] for n in pick_for_reading(g["nodes"], "p0", g["edges"], 4)]
        self.assertEqual(picked, ["p0", "p7", "p8", "p9"])      # seed, two most linked, then the newest; date order kept

    def test_report_says_what_was_left_out(self):
        g = graph(5)
        g["gates"], g["audit"] = {"caveats": ["x"]}, {"caveats": []}
        for n in g["nodes"][:3]:
            n["gates"], n["assessment"] = {"verdict": "solid"}, {"flag": "fair"}
        note_coverage(g, 3, 3)
        self.assertEqual(g["gates"]["not_covered"], ["p3", "p4"])
        self.assertIn("2 of 5 papers on the map were not read through the gates (the limit was 3; run with --gates-max 0",
                      g["gates"]["caveats"][-1])
        self.assertEqual(g["gates"]["caveats"][0], "x")
        note_coverage(g, 3, 3)                                    # run twice: one note, not two
        self.assertEqual(len(g["audit"]["caveats"]), 1)
        g["meta"]["language"] = "zh-CN"
        note_coverage(g, 0, 0)
        self.assertIn("没有审计（拿不到原文或证据）", g["audit"]["caveats"][-1])
        self.assertEqual(len(g["audit"]["caveats"]), 1)


if __name__ == "__main__":
    unittest.main()
