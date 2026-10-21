"""The audit's evidence line carries what the careful reading found (details a summary card drops)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.judge.gates import evidence_line  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
