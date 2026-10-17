"""End-to-end smoke test with fake sources and a fake LLM.

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

from tastecal.core.config import Config  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tastecal.core.llm import extract_json  # noqa: E402
from tastecal.report.render import render_html  # noqa: E402
from tastecal.core.schema import validate  # noqa: E402
from tastecal.lineage.synthesize import synthesize  # noqa: E402
from fakes import FakeLLM, FakeSource  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PipelineTest(unittest.TestCase):
    def grow(self, **kw):
        cfg = Config(budget=kw.get("budget", 8), max_rounds=3, use_openalex=False, use_web=False,
                     cache_dir=tempfile.mkdtemp())
        llm = FakeLLM()
        g = Grower(cfg, FakeSource(), llm).run("seed")
        return g, llm

    def test_growth_follows_problems(self):
        g, llm = self.grow()
        titles = {n.item.title for n in g.nodes.values()}
        self.assertIn("Alpha: Small Updates Suffice", titles)      # backward, kept
        self.assertNotIn("Zeta Dataset", titles)                    # merely used, dropped
        self.assertIn("Gamma: Quantized SeedNet", titles)           # forward
        self.assertIn("Delta: Fixing Gamma Error", titles)          # forward, 2 hops
        self.assertIn("Epsilon: Rank Allocation", titles)           # found by problem search
        self.assertLessEqual(len(g.nodes), 8)
        self.assertTrue(any(p.addressed_by for p in g.ledger.problems.values()))
        for (s, t), e in g.edges.items():                           # edges point forward in time
            self.assertLessEqual(g.nodes[s].item.sort_date, g.nodes[t].item.sort_date)

    def test_budget_is_respected(self):
        g, _ = self.grow(budget=3)
        self.assertLessEqual(len(g.nodes), 3)

    def test_synthesis_produces_valid_graph(self):
        g, llm = self.grow()
        graph = synthesize(g, llm, "seed")
        self.assertEqual(validate(graph), [])
        self.assertEqual(graph["nodes"][0]["role"] if graph["nodes"][0]["id"] == graph["meta"]["seed"] else "seed", "seed")
        self.assertNotIn("[[not-a-node]]", " ".join(graph["story"]["paragraphs"]))
        for task in ("cards", "classify_links", "ledger_update", "threads", "why_ladders", "field", "predict", "narrative"):
            self.assertIn(task, llm.tasks)
        html = render_html(graph)
        self.assertIn("<!doctype html>", html)
        self.assertIn('"schema":"deepanalyze.graph/1"', html)
        self.assertNotIn("/*__GRAPH_DATA__*/null", html)

    def test_example_graphs_are_valid(self):
        root = os.path.join(ROOT, "examples")
        found = sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "graph.json"))) if os.path.isdir(root) else []
        if not found:
            self.skipTest("no example runs in this copy")
        for ex in found:
            with open(os.path.join(root, ex, "graph.json"), encoding="utf-8") as f:
                graph = json.load(f)
            self.assertEqual(validate(graph), [], ex)

    def test_extract_json(self):
        self.assertEqual(extract_json('Sure!\n```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertEqual(extract_json('noise [ {"x": "a ] b"} ] tail'), [{"x": "a ] b"}])


if __name__ == "__main__":
    unittest.main()
