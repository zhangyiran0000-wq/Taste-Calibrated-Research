"""Gates: rules, ledger (nothing is folded), and the whole stage on the fictional fake corpus.

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
        self.assertEqual(verdict(answer(reason="mechanism"), QUIET, 0.3, TH), "treasure")       # taste cannot change evidence
        self.assertEqual(verdict(answer(reason="none", robust="repeats"), QUIET, None, TH), "solid")  # robustness without a reason
        self.assertEqual(verdict(answer(reason="none"), ADOPTED, None, TH), "incremental")       # adoption is not validation
        self.assertEqual(verdict(answer(reason="analogy"), QUIET, 0.9, TH), "incremental")       # an analogy is not a reason
        self.assertEqual(verdict(answer("partial", "none", "unclear"), QUIET, None, TH), "uncertain")

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
    def test_nothing_folds_and_the_ledger_keeps_every_solution(self):
        g = mini_graph()
        raw = {"s": dict(answer("not", "none"), basis="full text"),        # the seed is never folded
               "a": dict(answer(reason="none"), basis="abstract"),         # only an abstract was read: no verdict
               "b": dict(answer("not", "mechanism"), basis="full text"),   # not delivered, yet stays on the map
               "c": dict(answer(reason="mechanism", robust="repeats"), basis="full text")}
        apply_gates(g, raw, TODAY)
        v = {n["id"]: n["gates"]["verdict"] for n in g["nodes"]}
        fold = {n["id"]: n["gates"]["fold"] for n in g["nodes"]}
        self.assertEqual(v, {"s": "not-delivered", "a": "unread", "b": "not-delivered", "c": "solid"})
        self.assertEqual(fold, {"s": False, "a": False, "b": False, "c": False})
        p = {x["id"]: x for x in g["problems"]}
        self.assertEqual((p["P1"]["status"], p["P1"]["addressed_by"], p["P1"]["claimed_by"]), ("addressed", ["b"], []))
        self.assertEqual((p["P2"]["status"], p["P2"]["addressed_by"], p["P2"]["claimed_by"]), ("addressed", ["a", "b"], []))
        self.assertEqual(p["P3"]["status"], "open")
        self.assertEqual(g["gates"]["reopened"], 0)
        self.assertEqual(g["gates"]["folded"], 0)
        self.assertTrue(all("fold_reason" not in n["gates"] and "fold_blocked" not in n["gates"] for n in g["nodes"]))

        # A graph gated before, with solutions moved to "claimed", gets them back on the next gating.
        p1 = next(x for x in g["problems"] if x["id"] == "P1")
        p1.update(addressed_by=[], claimed_by=["b"], status="claimed")
        apply_gates(g, {"b": dict(answer(reason="mechanism", robust="repeats"), basis="full text")}, TODAY)
        p = {x["id"]: x for x in g["problems"]}
        self.assertEqual((p["P1"]["status"], p["P1"]["addressed_by"], p["P1"]["claimed_by"]), ("addressed", ["b"], []))
        self.assertEqual(p["P2"]["addressed_by"], ["a", "b"])
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "a")["gates"]["verdict"], "unread")  # kept from before
        self.assertEqual(split_ledger(g), 0)

    def test_every_work_stays_and_keeps_a_summary(self):
        g = mini_graph()
        bare = dict(answer("not", "none"), delivery_evidence="", basis="full text")           # no pointer to the text
        lever = dict(answer(reason="analogy"), robustness_note="", basis="full text",
                     levers=[{"lever": "metric-trained", "note": "the scorer is trained on the benchmark's own score (Sec. 3.2)"}])
        good = dict(answer("not", "mechanism"), basis="full text")
        apply_gates(g, {"a": bare, "c": lever, "s": good}, TODAY)
        x = {n["id"]: n["gates"] for n in g["nodes"] if "gates" in n}
        self.assertFalse(any(v["fold"] for v in x.values()))
        self.assertIn("Claims: a method that improves itself.", x["s"]["why"])
        self.assertTrue(all(v["why"] for v in x.values()))

    def test_chinese_report_gets_chinese_reasons(self):
        g = mini_graph()
        g.setdefault("meta", {})["language"] = "zh-CN"
        lever = dict(answer(reason="analogy"), robustness_note="", basis="full text",
                     levers=[{"lever": "metric-trained", "note": "评分器在基准分数上训练（3.2节）"}])
        apply_gates(g, {"a": dict(answer(reason="none"), basis="card"), "c": lever,
                        "s": dict(answer("not", "mechanism"), basis="full text")}, TODAY)
        x = {n["id"]: n["gates"] for n in g["nodes"] if "gates" in n}
        self.assertTrue(x["c"]["why"].startswith("兑现了主张"))
        self.assertIn("摘要卡片", x["a"]["why"])
        for v in x.values():
            self.assertNotRegex(v["why"], r"^(It delivers|Claims|Reason|No stated|Delivered)")

    def test_adoption_is_not_a_robustness_explanation(self):
        from tastecal.judge.gates import why_line
        react = dict(QUIET, builds_on_share=0.4, robust=True)
        g = answer(reason="none", robust="unclear")
        self.assertEqual(verdict(g, react, None, TH), "uncertain")
        self.assertNotIn("40%", why_line("solid", g, react))
        self.assertNotIn("40%", why_line("solid", g, react, "zh"))
        self.assertEqual(why_line("solid", g, ADOPTED), g["robustness_note"])

    def test_unusable_answers_leave_nodes_ungated(self):
        g = mini_graph()
        apply_gates(g, {"a": {"delivery": "?"}}, TODAY)
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

    def test_full_text_validates_and_nothing_folds(self):
        graph, llm = self.build(full_text=True, profile=PROFILE)
        v = self.verdicts(graph)
        self.assertEqual(v["SeedNet: Cheap Adaptation"], ("solid", False))
        self.assertEqual(v["Alpha: Small Updates Suffice"], ("solid", False))
        self.assertEqual(v["Beta Adapters"], ("not-delivered", False))
        # No reason and one setting: the label says so, but the work stays on the map.
        self.assertEqual(v["Gamma: Quantized SeedNet"], ("incremental", False))
        self.assertEqual(v["Delta: Fixing Gamma Error"], ("incremental", False))
        self.assertEqual(v["Epsilon: Rank Allocation"], ("treasure", False))
        self.assertEqual(validate(graph), [])
        self.assertEqual(graph["gates"]["taste_profile"], PROFILE)            # kept for `fit`, not scored here
        self.assertFalse(any(k in n["gates"] for n in graph["nodes"] if n.get("gates")
                             for k in ("attractiveness", "taste_why", "treasure_candidate")))
        self.assertNotIn("taste_check", graph["gates"])
        self.assertNotIn("rate_next", graph["gates"])
        html = render_html(graph)
        self.assertNotIn('id="gates"', html)                                  # the notes are not shown
        self.assertNotIn("Treasure candidate", html)

    def test_taste_is_never_scored_and_never_reaches_the_gate_prompt(self):
        _, llm = self.build(full_text=True, profile=PROFILE)
        audits = [p for t, p in llm.prompts if t == "gates_audit"]
        self.assertTrue(audits)
        self.assertTrue(all("7f3a" not in p for p in audits))
        self.assertFalse(any("7f3a" in p for _, p in llm.prompts))          # no prompt sees the profile

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
               some[1]: dict(answer(reason="mechanism"), basis="full text", taste={"score": 0.9, "why": "yes"})}  # ignored
        with open(rpath, "w") as f:
            json.dump(raw, f)
        self.assertEqual(cli.main(["gates", gpath, "--raw", rpath, "--today", TODAY]), 0)
        with open(gpath) as f:
            out = json.load(f)
        self.assertEqual(validate(out), [])
        by = {n["id"]: n for n in out["nodes"]}
        self.assertEqual(by[some[0]]["gates"]["verdict"], "not-delivered")
        self.assertFalse(by[some[0]]["gates"]["fold"])
        self.assertEqual(by[some[1]]["gates"]["verdict"], "treasure")
        self.assertNotIn("attractiveness", by[some[1]]["gates"])
        self.assertTrue(os.path.exists(os.path.join(d, "report.html")))


if __name__ == "__main__":
    unittest.main()
