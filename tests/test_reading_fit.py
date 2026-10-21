"""Full-text selection keeps the experiments; an evaluation that cannot show the claim blocks 'solid'."""
import unittest

from tastecal.judge.gates import GateThresholds, clean_gates, confounders, verdict, verify
from tastecal.sources.fulltext import coverage_note, select_for_reading


def paper(intro=20000, related=15000, method=20000, exp=20000, refs=10000):
    return ("Abstract\nWe propose X.\n1. Introduction\n" + "i" * intro +
            "\n2. Related Work\n" + "r" * related +
            "\n3. Method\n" + "m" * method +
            "\n4. Experiments\nRESULTS-TABLE " + "e" * exp + "\n5. Conclusion\nDone.\n"
            "\nReferences\n" + "".join(f"[{i}] x\n" for i in range(1, refs // 6)))


class SelectionTest(unittest.TestCase):
    def test_short_paper_drops_only_references(self):
        text, cov = select_for_reading(paper(intro=1000, related=1000, method=1000, exp=1000, refs=600))
        self.assertIn("RESULTS-TABLE", text)
        self.assertNotIn("[2] x", text)
        self.assertEqual(cov["main_coverage"], 1.0)
        self.assertEqual(cov["omitted"], ["references"])

    def test_reference_list_without_a_heading_is_dropped(self):
        text = paper(intro=1000, related=1000, method=1000, exp=1000, refs=600).replace("\nReferences\n", "\n")
        shown, cov = select_for_reading(text)
        self.assertIn("RESULTS-TABLE", shown)
        self.assertNotIn("[2] x", shown)
        self.assertIn("references", cov["omitted"])

    def test_long_paper_keeps_experiments(self):
        text, cov = select_for_reading(paper(), limit=40000)
        self.assertIn("RESULTS-TABLE", text)
        self.assertIn("Conclusion", text)
        self.assertLessEqual(len(text), 40000 + 200)
        self.assertIn("related work", cov["omitted"])
        self.assertLess(cov["main_coverage"], 1.0)
        self.assertIn("Left out", coverage_note(cov))


def answer(can_show, quote="adds strategic reasoning"):
    return {"delivery": "delivered", "reason_type": "proof", "robustness": "repeats", "levers": [],
            "checks": {"numbers": "match", "fair_baselines": "yes", "novelty_ablation": "yes", "code": "released"},
            "eval_fit": {"property": "strategic reasoning", "property_quote": quote, "shown_by": "ADE on logs",
                         "can_show": can_show, "fit_why": "Distance to logged paths does not change with reasoning.",
                         "kind": "method", "threat_model": ""}}


class EvalFitTest(unittest.TestCase):
    TEXT = "Our model adds strategic reasoning to planning. " + "Filler sentence about the experiments. " * 20

    def g(self, r):
        r = dict(r, verified=verify(r, self.TEXT))
        return clean_gates(r)

    def test_cannot_show_is_a_confounder(self):
        g = self.g(answer("no"))
        self.assertTrue(confounders(g))
        self.assertEqual(verdict(g, {"robust": False}, None, GateThresholds()), "unattributed")

    def test_can_show_is_not(self):
        g = self.g(answer("yes"))
        self.assertFalse(confounders(g))
        self.assertEqual(verdict(g, {"robust": False}, None, GateThresholds()), "solid")

    def test_unfound_quote_does_not_count(self):
        g = self.g(answer("no", quote="words that are not in the paper at all"))
        self.assertFalse(confounders(g))


if __name__ == "__main__":
    unittest.main()
