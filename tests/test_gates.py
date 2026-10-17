"""Gates: rules, ledger, folding, and the whole stage on the fictional fake corpus.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tastecal import cli  # noqa: E402
from tastecal.core.config import Config  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tastecal.judge.gates import (GateThresholds, Gatekeeper, apply_gates, clean_gates, reaction,  # noqa: E402
                               split_ledger, verdict)
from tastecal.report.render import render_html  # noqa: E402
from tastecal.core.schema import validate  # noqa: E402
from tastecal.lineage.synthesize import synthesize  # noqa: E402
from fakes import FakeLLM, FakeSource  # noqa: E402

TODAY = "2026-10"
TH = GateThresholds()
PROFILE = "I read work with a clear reason for why it should work. (profile marker 7f3a)"


def answer(delivery="delivered", reason="mechanism", robust="single", **kw):
    r = {"claimed": "a method that improves itself", "delivery": delivery, "delivered": "a tuned configuration",
         "delivery_evidence": "Table 3: the gain appears only with the extra tuning", "reason_type": reason,
         "reason": "r", "robustness": robust, "robustness_note": "one benchmark, no variance", "levers": [],
         "check_next": "x"}
    r.update(kw)
    return clean_gates(r)


QUIET = {"adopted_by": [], "challenged_by": [], "builds_on_share": None, "too_early": False, "robust": False}
ADOPTED = dict(QUIET, adopted_by=["p", "q"], robust=True)


class RuleTest(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(verdict(answer("not", "proof", "repeats"), ADOPTED, 0.9, TH), "not-delivered")
        self.assertEqual(verdict(answer(reason="mechanism", robust="repeats"), QUIET, None, TH), "solid")
        self.assertEqual(verdict(answer(reason="mechanism"), QUIET, None, TH), "treasure")      # no profile: every reasoned, unverified work
        self.assertEqual(verdict(answer(reason="mechanism"), QUIET, 0.8, TH), "treasure")
        self.assertEqual(verdict(answer(reason="mechanism"), QUIET, 0.3, TH), "solid")          # reasoned but not for this reader
        self.assertEqual(verdict(answer(reason="none", robust="repeats"), QUIET, None, TH), "solid")  # robustness without a reason
        self.assertEqual(verdict(answer(reason="none"), ADOPTED, None, TH), "solid")             # the field adopted it
        self.assertEqual(verdict(answer(reason="analogy"), QUIET, 0.9, TH), "incremental")       # an analogy is not a reason
        self.assertEqual(verdict(answer("partial", "none", "unclear"), QUIET, None, TH), "incremental")

    def test_clean_gates(self):
        self.assertIsNone(clean_gates({"delivery": "maybe", "reason_type": "proof"}))
        self.assertIsNone(clean_gates("not a dict"))
        g = clean_gates({"delivery": "partial", "reason_type": "none", "robustness": "huge",
                         "levers": [{"lever": "metric-trained", "note": "n"}, {"lever": "vibes"}, "small-or-saturated-benchmark"]})
        self.assertEqual(g["robustness"], "unclear")
        self.assertEqual([lv["lever"] for lv in g["levers"]], ["metric-trained", "other", "small-or-saturated-benchmark"])
        self.assertEqual(g["levers"][1]["note"], "vibes")

    def test_reaction(self):
        graph = {"nodes": [{"id": "x"}], "edges": [
            {"source": "x", "target": "p", "type": "extends"}, {"source": "x", "target": "q", "type": "resolves"},
            {"source": "x", "target": "r", "type": "challenges"}, {"source": "y", "target": "x", "type": "extends"}]}
        r = reaction(graph, "x", 24, TH)
        self.assertEqual(r["adopted_by"], ["p", "q"])
        self.assertEqual(r["challenged_by"], ["r"])
        self.assertTrue(r["robust"])
        self.assertFalse(reaction(graph, "x", 3, TH)["robust"])          # too recent to count
        graph["edges"] += [{"source": "x", "target": "s", "type": "challenges"}, {"source": "x", "target": "t", "type": "challenges"}]
        self.assertFalse(reaction(graph, "x", 24, TH)["robust"])         # more challenges than adoptions


def mini_graph():
    return {"meta": {"seed": "s"}, "edges": [],
            "nodes": [{"id": "s", "role": "seed", "date": "2024-01"}, {"id": "a", "date": "2024-06"},
                      {"id": "b", "date": "2025-01"}, {"id": "c", "date": "2025-02"}],
            "problems": [{"id": "P1", "text": "x", "raised_by": ["s"], "addressed_by": ["b"]},
                         {"id": "P2", "text": "y", "raised_by": ["s"], "addressed_by": ["a", "b"]},
                         {"id": "P3", "text": "z", "raised_by": ["a"], "addressed_by": []}]}


class ApplyTest(unittest.TestCase):
    def test_fold_rules_and_ledger(self):
        g = mini_graph()
        raw = {"s": dict(answer("not", "none"), basis="full text"),        # the seed is never folded
               "a": dict(answer(reason="none"), basis="abstract"),         # incremental, but only an abstract was read
               "b": dict(answer("not", "mechanism"), basis="full text"),   # folded, and its problems reopen
               "c": dict(answer(reason="mechanism", robust="repeats"), basis="full text")}
        apply_gates(g, raw, {}, TODAY)
        v = {n["id"]: n["gates"]["verdict"] for n in g["nodes"]}
        fold = {n["id"]: n["gates"]["fold"] for n in g["nodes"]}
        self.assertEqual(v, {"s": "not-delivered", "a": "incremental", "b": "not-delivered", "c": "solid"})
        self.assertEqual(fold, {"s": False, "a": False, "b": True, "c": False})
        p = {x["id"]: x for x in g["problems"]}
        self.assertEqual((p["P1"]["status"], p["P1"]["claimed_by"]), ("claimed", ["b"]))
        self.assertEqual((p["P2"]["status"], p["P2"]["addressed_by"], p["P2"]["claimed_by"]), ("addressed", ["a"], ["b"]))
        self.assertEqual(p["P3"]["status"], "open")
        self.assertEqual(g["gates"]["reopened"], 1)
        self.assertEqual(g["gates"]["folded"], 1)

        # Re-gating is idempotent, and a work that now delivers gets its problems back.
        apply_gates(g, {"b": dict(answer(reason="mechanism", robust="repeats"), basis="full text")}, {}, TODAY)
        p = {x["id"]: x for x in g["problems"]}
        self.assertEqual((p["P1"]["status"], p["P1"]["addressed_by"], p["P1"]["claimed_by"]), ("addressed", ["b"], []))
        self.assertEqual(p["P2"]["addressed_by"], ["a", "b"])
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "a")["gates"]["verdict"], "incremental")  # kept from before
        self.assertEqual(split_ledger(g), 0)

    def test_every_fold_has_a_reason(self):
        g = mini_graph()
        bare = dict(answer("not", "none"), delivery_evidence="", basis="full text")           # no pointer to the text
        vague = dict(answer(reason="none"), robustness_note="none given", basis="full text")  # boilerplate is not evidence
        lever = dict(answer(reason="analogy"), robustness_note="", basis="full text",
                     levers=[{"lever": "metric-trained", "note": "the scorer is trained on the benchmark's own score (Sec. 3.2)"}])
        good = dict(answer("not", "mechanism"), basis="full text")
        apply_gates(g, {"a": bare, "b": vague, "c": lever, "s": good}, {}, TODAY)
        x = {n["id"]: n["gates"] for n in g["nodes"]}
        self.assertFalse(x["a"]["fold"])
        self.assertIn("without evidence", x["a"]["fold_blocked"])
        self.assertFalse(x["b"]["fold"])
        self.assertTrue(x["c"]["fold"])                                    # a located lever is evidence
        self.assertIn("analogy", x["c"]["fold_reason"]["evidence"][0] + x["c"]["fold_reason"]["evidence"][-1])
        self.assertIn("A component trained on the metric: the scorer", " ".join(x["c"]["fold_reason"]["evidence"]))
        self.assertFalse(x["s"]["fold"])
        self.assertEqual(x["s"]["fold_blocked"], "The seed is never folded.")
        for n in g["nodes"]:                                               # every fold names its reason
            if n["gates"]["fold"]:
                self.assertTrue(n["gates"]["fold_reason"]["summary"] and n["gates"]["fold_reason"]["evidence"])
        self.assertIn("Claims: a method that improves itself.", x["s"]["fold_reason"]["summary"])

    def test_unusable_answers_leave_nodes_ungated(self):
        g = mini_graph()
        apply_gates(g, {"a": {"delivery": "?"}}, {}, TODAY)
        self.assertNotIn("gates", next(n for n in g["nodes"] if n["id"] == "a"))
        self.assertEqual(g["gates"]["gated"], 0)


class StageTest(unittest.TestCase):
    def build(self, full_text: bool, profile: str = ""):
        cfg = Config(budget=8, max_rounds=3, use_openalex=False, use_web=False, cache_dir=tempfile.mkdtemp(), gates_max=40)
        llm = FakeLLM()
        grower = Grower(cfg, FakeSource(), llm).run("seed")
        graph = synthesize(grower, llm, "seed")
        keeper = Gatekeeper(cfg, llm, None, today=TODAY, profile=profile)
        if full_text:
            keeper.fulltext = lambda node, item=None: ("Section 1. " * 800 + "It would not help when the training data "
                                                      "are small and noisy. " + "Section 2. " * 50, "full text")
        items = {n.item.id: n.item for n in grower.nodes.values()}
        keeper.run(graph, items)
        return graph, llm

    def verdicts(self, graph):
        return {n["title"]: (n["gates"]["verdict"], n["gates"]["fold"]) for n in graph["nodes"] if n.get("gates")}

    def test_full_text_folds_and_validates(self):
        graph, llm = self.build(full_text=True, profile=PROFILE)
        v = self.verdicts(graph)
        self.assertEqual(v["SeedNet: Cheap Adaptation"], ("solid", False))
        self.assertEqual(v["Alpha: Small Updates Suffice"], ("solid", False))
        self.assertEqual(v["Beta Adapters"], ("not-delivered", True))
        self.assertEqual(v["Gamma: Quantized SeedNet"], ("incremental", True))
        self.assertEqual(v["Delta: Fixing Gamma Error"], ("incremental", True))
        self.assertEqual(v["Epsilon: Rank Allocation"], ("treasure", False))
        self.assertEqual(validate(graph), [])
        self.assertTrue(graph["gates"]["taste"])
        html = render_html(graph)
        self.assertIn('id="gates"', html)
        self.assertIn('"verdict":"treasure"', html)

    def test_taste_never_reaches_the_gate_prompt(self):
        _, llm = self.build(full_text=True, profile=PROFILE)
        audits = [p for t, p in llm.prompts if t == "gates_audit"]
        tastes = [p for t, p in llm.prompts if t == "gates_taste"]
        self.assertTrue(audits and tastes)
        self.assertTrue(all("7f3a" not in p for p in audits))
        self.assertTrue(all("7f3a" in p and "Section 1." not in p for p in tastes))

    def test_without_full_text_nothing_folds(self):
        graph, _ = self.build(full_text=False)
        self.assertTrue(any(n.get("gates") for n in graph["nodes"]))
        self.assertFalse(any(n["gates"]["fold"] for n in graph["nodes"] if n.get("gates")))
        self.assertEqual({n["gates"]["basis"] for n in graph["nodes"] if n.get("gates")}, {"abstract"})
        self.assertEqual(validate(graph), [])

    def test_cli_with_raw_answers(self):
        cfg = Config(budget=8, max_rounds=3, use_openalex=False, use_web=False, cache_dir=tempfile.mkdtemp())
        llm = FakeLLM()
        graph = synthesize(Grower(cfg, FakeSource(), llm).run("seed"), llm, "seed")
        d = tempfile.mkdtemp()
        gpath, rpath = os.path.join(d, "graph.json"), os.path.join(d, "raw.json")
        with open(gpath, "w") as f:
            json.dump(graph, f)
        some = [n["id"] for n in graph["nodes"] if n["role"] != "seed"][:2]
        raw = {some[0]: dict(answer("not", "none"), basis="full text"),
               some[1]: dict(answer(reason="mechanism"), basis="full text", taste={"score": 0.9, "why": "yes"})}
        with open(rpath, "w") as f:
            json.dump(raw, f)
        self.assertEqual(cli.main(["gates", gpath, "--raw", rpath, "--today", TODAY]), 0)
        with open(gpath) as f:
            out = json.load(f)
        self.assertEqual(validate(out), [])
        by = {n["id"]: n for n in out["nodes"]}
        self.assertEqual(by[some[0]]["gates"]["verdict"], "not-delivered")
        self.assertTrue(by[some[0]]["gates"]["fold"])
        self.assertEqual(by[some[1]]["gates"]["verdict"], "treasure")
        self.assertEqual(by[some[1]]["gates"]["attractiveness"], 0.9)
        self.assertTrue(os.path.exists(os.path.join(d, "report.html")))


if __name__ == "__main__":
    unittest.main()
