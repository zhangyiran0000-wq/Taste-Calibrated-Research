"""Taste sees what the gate read found (never the other way round), and the report suggests what to rate next."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.judge.gates import evidence_line, rate_next  # noqa: E402
from tastecal.prompts.gates import gates_taste  # noqa: E402

READ = {"claimed": "c", "delivery": "partial", "partial_kind": "unisolated", "delivered": "a 3-point gain on one benchmark",
        "reason_type": "mechanism", "reason": "r", "fails_when_stated": False, "robustness": "single",
        "robustness_note": "one benchmark", "levers": [
            {"lever": "unequal-tuning", "status": "present", "where": "Table 4", "note": "only the method was tuned"},
            {"lever": "cost-assumption", "status": "suspected", "note": "maybe"}],
        "checks": {"fair_baselines": "no", "novelty_ablation": "no"}, "fairness_notes": ["open-loop metrics only"]}


class EvidenceTest(unittest.TestCase):
    def test_line_carries_the_details_a_card_drops(self):
        line = evidence_line(READ)
        for bit in ("3-point gain", "unisolated", "never says when it would not help", "Tuning the baselines",
                    "baselines not treated equally", "no ablation", "open-loop"):
            self.assertIn(bit.lower(), line.lower())
        self.assertNotIn("cost or price", line)          # a suspected lever is not reported as shown
        self.assertEqual(evidence_line(None), "")

    def test_prompt_includes_it(self):
        p = gates_taste("I skip gains from tuning.", [{"id": "a", "short": "A", "inherits": "x", "move": "y",
                                                      "insight": "z", "evidence": evidence_line(READ)}])
        self.assertIn("found in the paper:", p)
        self.assertIn("baselines not treated equally", p)


class RateNextTest(unittest.TestCase):
    def graph(self, n=10):
        return {"nodes": [{"id": f"w{i}", "title": f"Work {i}", "kind": "paper",
                           "assessment": {"contribution": {"score": i / 10}}} for i in range(n)]}

    def test_spread_over_the_blind_score(self):
        got = rate_next(self.graph(), "")
        self.assertEqual(got[0], "w0")
        self.assertEqual(got[-1], "w9")
        self.assertEqual(len(got), 5)

    def test_rated_papers_are_skipped_and_enough_stops_it(self):
        prof = "## Papers I liked\n- Work 0 (my score 0.9)\n"
        self.assertNotIn("w0", rate_next(self.graph(), prof))
        many = "## Papers I liked\n" + "".join(f"- Paper {i} (my score 0.5)\n" for i in range(8))
        self.assertEqual(rate_next(self.graph(), many), [])


if __name__ == "__main__":
    unittest.main()
