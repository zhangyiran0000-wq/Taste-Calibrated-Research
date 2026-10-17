"""Gates that tell works apart: shown levers, unfair baselines without an ablation, checked quotes, skew warnings."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.judge.gates import (GateThresholds, apply_gates, clean_gates, confounders, gates_meta,  # noqa: E402
                                  quote_in_text, verdict, verify)

TH = GateThresholds()
QUIET = {"adopted_by": [], "challenged_by": [], "robust": False, "too_early": False}
ADOPTED = {"adopted_by": ["x", "y"], "challenged_by": [], "robust": True, "too_early": False}
PAPER = ("We present a method. " * 40 + "Our approach would not help when the scene contains no movable objects, "
         "because the planner then has nothing to reason about. " + "More results follow. " * 40)


def ans(**kw):
    base = {"claimed": "c", "delivery": "delivered", "delivered": "d", "delivery_evidence": "Table 2",
            "reason_type": "mechanism", "reason": "because", "fails_when": "", "fails_when_stated": True,
            "robustness": "repeats", "robustness_note": "three benchmarks", "levers": [], "check_next": ""}
    base.update(kw)
    return clean_gates(base)


class ConfounderTest(unittest.TestCase):
    def test_suspected_levers_do_not_count(self):
        g = ans(levers=[{"lever": "unequal-tuning", "status": "suspected", "note": "maybe"}])
        self.assertEqual(confounders(g), [])
        self.assertEqual(verdict(g, QUIET, None, TH), "solid")

    def test_old_answers_without_status_count_as_suspected(self):
        g = ans(levers=[{"lever": "unequal-tuning", "note": "only the method was tuned"}])
        self.assertEqual(g["levers"][0]["status"], "suspected")
        self.assertEqual(verdict(g, QUIET, None, TH), "solid")

    def test_present_serious_lever_with_pointer(self):
        g = ans(levers=[{"lever": "unequal-tuning", "status": "present", "where": "Table 4",
                         "note": "only the method got a hyper-parameter sweep"}])
        self.assertEqual(verdict(g, QUIET, None, TH), "unattributed")
        self.assertIn("Table 4", confounders(g)[0])

    def test_present_lever_without_note_is_ignored(self):
        g = ans(levers=[{"lever": "unequal-tuning", "status": "present", "note": ""}])
        self.assertEqual(verdict(g, QUIET, None, TH), "solid")

    def test_minor_lever_does_not_confound(self):
        g = ans(levers=[{"lever": "small-or-saturated-benchmark", "status": "present", "note": "200 test items"}])
        self.assertEqual(verdict(g, QUIET, None, TH), "solid")

    def test_unfair_baselines_need_a_missing_ablation(self):
        unfair = {"fair_baselines": "no", "baselines_note": "baselines get no depth", "novelty_ablation": "no"}
        self.assertEqual(verdict(ans(checks=unfair), QUIET, None, TH), "unattributed")
        ablated = dict(unfair, novelty_ablation="yes")
        self.assertEqual(verdict(ans(checks=ablated), QUIET, None, TH), "solid")

    def test_unisolated_partial(self):
        g = ans(delivery="partial", partial_kind="unisolated", checks={"novelty_ablation": "no"})
        self.assertEqual(verdict(g, QUIET, None, TH), "unattributed")
        g = ans(delivery="partial", partial_kind="narrower", checks={"novelty_ablation": "no"})
        self.assertEqual(verdict(g, QUIET, None, TH), "solid")

    def test_only_headline_mismatches_count(self):
        minor = {"numbers": "mismatch", "numbers_severity": "minor", "numbers_note": "a rounding in section 4"}
        self.assertEqual(verdict(ans(checks=minor), QUIET, None, TH), "solid")
        head = dict(minor, numbers_severity="headline", numbers_note="abstract says 54.9, Table 3 says 44.7")
        self.assertEqual(verdict(ans(checks=head), QUIET, None, TH), "unattributed")

    def test_adoption_by_the_field_overrides(self):
        g = ans(robustness="single", checks={"fair_baselines": "no", "novelty_ablation": "no", "baselines_note": "x"})
        self.assertEqual(verdict(g, ADOPTED, None, TH), "solid")

    def test_incremental_stays_incremental(self):
        g = ans(reason_type="none", robustness="single", checks={"fair_baselines": "no", "novelty_ablation": "no"})
        self.assertEqual(verdict(g, QUIET, None, TH), "incremental")

    def test_not_delivered_wins(self):
        g = ans(delivery="not", checks={"fair_baselines": "no", "novelty_ablation": "no"})
        self.assertEqual(verdict(g, QUIET, None, TH), "not-delivered")


class QuoteTest(unittest.TestCase):
    def test_exact_and_near_quotes(self):
        self.assertTrue(quote_in_text("Our approach would not help when the scene contains no movable objects", PAPER))
        self.assertTrue(quote_in_text("our approach would NOT help when the scene contains no movable objects.", PAPER))
        self.assertTrue(quote_in_text("Our approach would not help when a scene contains no movable objects at all",
                                      PAPER))          # a word changed and two added: still most of the run
        self.assertFalse(quote_in_text("It fails on long-horizon tasks with deformable objects and clutter", PAPER))
        self.assertFalse(quote_in_text("small data", PAPER))       # too short to count as a quote
        self.assertIsNone(quote_in_text("anything", "short"))      # nothing to check against

    def test_verify_sets_only_what_was_checked(self):
        r = {"fails_when_stated": True, "fails_when": "It fails on long-horizon tasks with deformable objects"}
        self.assertEqual(verify(r, PAPER), {"fails_when": False})
        self.assertEqual(verify(r, ""), {})
        self.assertEqual(verify({"fails_when_stated": False}, PAPER), {"fails_when": False})

    def test_unfound_quote_removes_the_reason(self):
        raw = {"claimed": "c", "delivery": "delivered", "delivered": "d", "reason_type": "mechanism",
               "reason": "because", "fails_when_stated": True, "fails_when": "made up", "robustness": "single",
               "robustness_note": "one benchmark (Table 2)", "levers": []}
        found = clean_gates(dict(raw, verified={"fails_when": True}))
        lost = clean_gates(dict(raw, verified={"fails_when": False}))
        self.assertEqual(verdict(found, QUIET, None, TH), "treasure")
        self.assertEqual(verdict(lost, QUIET, None, TH), "incremental")


class SkewTest(unittest.TestCase):
    def test_one_verdict_everywhere_is_flagged(self):
        nodes = [{"id": f"n{i}", "gates": {"verdict": "solid", "fold": False}} for i in range(9)]
        nodes.append({"id": "n9", "gates": {"verdict": "incremental", "fold": True}})
        meta = gates_meta({"nodes": nodes}, "2026-10", TH, False, 0)
        self.assertEqual(meta["skew"]["verdict"], "solid")
        self.assertIn("same verdict", meta["caveats"][0])

    def test_mixed_verdicts_are_not(self):
        vs = ["solid"] * 5 + ["unattributed"] * 3 + ["incremental"] * 2
        nodes = [{"id": f"n{i}", "gates": {"verdict": v, "fold": False}} for i, v in enumerate(vs)]
        self.assertNotIn("skew", gates_meta({"nodes": nodes}, "2026-10", TH, False, 0))


class StationTest(unittest.TestCase):
    def test_unattributed_keeps_its_station(self):
        g = {"meta": {"seed": "s"}, "nodes": [{"id": "s", "role": "seed", "date": "2020-01"},
                                               {"id": "a", "date": "2021-01"}], "edges": [], "problems": []}
        raw = {"a": {"claimed": "c", "delivery": "delivered", "delivered": "d", "delivery_evidence": "Table 2",
                     "reason_type": "proof", "reason": "a bound", "robustness": "repeats", "robustness_note": "x",
                     "levers": [{"lever": "mismatched-setup", "status": "present", "where": "Table 1",
                                 "note": "the method uses LiDAR, baselines cameras only"}],
                     "basis": "full text"}}
        apply_gates(g, raw, today="2026-10")
        a = g["nodes"][1]["gates"]
        self.assertEqual(a["verdict"], "unattributed")
        self.assertFalse(a["fold"])
        self.assertIn("LiDAR", a["why"])
        self.assertEqual(g["gates"]["counts"]["unattributed"], 1)


if __name__ == "__main__":
    unittest.main()
