"""The problem ledger: restatements are merged, merged ids keep working, and growth stops when papers repeat problems."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.config import Config  # noqa: E402
from tastecal.core.model import Edge, Item, Ledger, Node, word_overlap  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tests.fakes import FakeLLM, FakeSource  # noqa: E402


class LedgerTest(unittest.TestCase):
    def test_word_overlap(self):
        self.assertGreater(word_overlap("Planning depends on hand-crafted cost functions",
                                        "Planning still depends on hand-crafted cost functions"), 0.8)
        self.assertLess(word_overlap("Planning depends on hand-crafted cost functions",
                                     "No real-robot evaluation of the policy"), 0.1)

    def test_similar_and_merge(self):
        led = Ledger()
        a = led.add("Planning depends on hand-crafted cost functions", raised_by="x")
        b = led.add("Rare situations are missing from the training data", raised_by="y")
        self.assertIs(led.similar("planning still depends on hand crafted cost function", 0.6), a)
        self.assertIsNone(led.similar("Evaluation is open-loop only", 0.6))
        c = led.add("Costs for planning are designed by hand", raised_by="z")
        c.addressed_by.append("w")
        self.assertTrue(led.merge(a.id, c.id))
        self.assertNotIn(c.id, led.problems)
        self.assertIs(led.get(c.id), a)                 # the old id still resolves
        self.assertEqual(set(a.raised_by), {"x", "z"})   # both raisers are kept
        self.assertNotIn("w", a.raised_by)
        self.assertIn("w", a.addressed_by)
        self.assertFalse(led.merge(a.id, c.id))          # already merged
        self.assertTrue(led.merge(b.id, a.id))
        self.assertIs(led.get(c.id), b)                  # aliases follow chains


class MergingLLM(FakeLLM):
    """Says every new open problem repeats the oldest open one."""

    def t_ledger_merge(self, p):
        import re
        ids = re.findall(r"^\[(P\d+)\]( \(new\))?", p, re.M)
        old = [i for i, new in ids if not new]
        fresh = [i for i, new in ids if new]
        return {"groups": [[old[0]] + fresh] if old and fresh else []}


class ConsolidateTest(unittest.TestCase):
    def grower(self, llm):
        g = Grower(Config(budget=10), FakeSource(), llm)
        g.seed_id = "s"
        g.nodes["s"] = Node(item=Item(id="s", title="Seed"), card=None, hop=0)
        return g

    def test_paraphrases_are_folded_and_edges_follow(self):
        g = self.grower(MergingLLM())
        for k in range(6):
            g.ledger.add(f"old problem number {k} about topic {k}", raised_by="s")
        new = [g.ledger.add("a fresh way to say problem zero", raised_by="s").id,
               g.ledger.add("yet another way to say problem zero", raised_by="s").id]
        g.edges[("s", "t")] = Edge(source="s", target="t", type="resolves", label="", problem=new[1])
        folded = g._consolidate(new)
        self.assertEqual(folded, 2)
        self.assertNotIn(new[0], g.ledger.problems)
        self.assertEqual(g.edges[("s", "t")].problem, "P1")

    def test_too_few_problems_skip_the_call(self):
        llm = MergingLLM()
        g = self.grower(llm)
        fresh = [g.ledger.add("only problem", raised_by="s").id]
        self.assertEqual(g._consolidate(fresh), 0)
        self.assertNotIn("ledger_merge", llm.tasks)

    def test_core_problems(self):
        g = self.grower(FakeLLM())
        g.nodes["far"] = Node(item=Item(id="far", title="Far"), card=None, hop=2)
        g.nodes["near"] = Node(item=Item(id="near", title="Near"), card=None, hop=-1)
        far = g.ledger.add("a problem only a distant work raised", raised_by="far")
        near = g.ledger.add("a problem a direct neighbour raised", raised_by="near")
        shared = g.ledger.add("a problem two works raised", raised_by="far")
        shared.raised_by.append("x")
        self.assertFalse(g._core(far))
        self.assertTrue(g._core(near))
        self.assertTrue(g._core(shared))

    def test_growth_still_runs_end_to_end(self):
        g = Grower(Config(budget=8), FakeSource(), MergingLLM()).run("seed")
        self.assertGreater(len(g.nodes), 1)
        for p in g.ledger.problems.values():           # merged entries are gone; every entry is reachable
            self.assertIs(g.ledger.get(p.id), p)


if __name__ == "__main__":
    unittest.main()
