"""The backtest cannot see the answer: early forces only, a no-forces baseline, blind matching, outside papers."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.config import Config  # noqa: E402
from tastecal.core.model import Item  # noqa: E402
from tastecal.lineage import backtest  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tests.fakes import CORPUS, FakeLLM, FakeSource  # noqa: E402


def grown():
    llm = FakeLLM()
    g = Grower(Config(budget=8), FakeSource(), llm).run("seed")
    nodes = sorted(g.nodes.values(), key=lambda n: n.item.sort_date)
    return g, llm, nodes


class BacktestTest(unittest.TestCase):
    def test_forces_come_from_early_works_only(self):
        g, llm, nodes = grown()
        check = backtest.run(g, llm, nodes, {"field": "Adaptation", "goal": "cheap tuning"})
        cutoff = check["cutoff"]
        prompt = next(p for t, p in llm.prompts if t == "early_forces")
        for n in nodes:
            if n.item.sort_date[:7] > cutoff and n.card:
                self.assertNotIn(n.card.move, prompt)
        self.assertIn("predict_null", llm.tasks)

    def test_matching_is_blind_to_which_set(self):
        g, llm, nodes = grown()
        backtest.run(g, llm, nodes, {"field": "Adaptation"})
        prompt = next(p for t, p in llm.prompts if t == "check_blind")
        self.assertNotIn("baseline", prompt.lower())
        self.assertNotIn("driving force", prompt.lower())

    def test_vague_matches_do_not_count_and_lift_is_reported(self):
        g, llm, nodes = grown()
        check = backtest.run(g, llm, nodes, {"field": "Adaptation"})
        self.assertEqual([r["text"] for r in check["predictions"]], ["quantize more", "allocate rank"])
        self.assertTrue(check["predictions"][0]["hit"])
        self.assertFalse(check["baseline"][0]["hit"])                 # matched, but specificity 1
        self.assertEqual((check["hits"], check["baseline_hits"], check["lift"]), (1, 0, 1))
        self.assertIn("without forces", check["note"])

    def test_no_better_than_baseline_is_said_plainly(self):
        class Same(FakeLLM):
            def t_predict_null(self, p):
                return {"predictions": ["quantize more"]}
        llm = Same()
        g = Grower(Config(budget=8), FakeSource(), llm).run("seed")
        nodes = sorted(g.nodes.values(), key=lambda n: n.item.sort_date)
        check = backtest.run(g, llm, nodes, {"field": "Adaptation"})
        self.assertLessEqual(check["lift"], 0)
        self.assertIn("no better than the baseline", check["note"])

    def test_outside_sample_skips_mapped_and_early_papers(self):
        class Src(FakeSource):
            def search(self, query, year_from, limit=15, year_to=None):
                return [Item(id="new1", title="A later paper", date="2025-01", year=2025),
                        Item(id="old1", title="An early paper", date="2019-01", year=2019),
                        CORPUS["e"]]
        g, _, nodes = grown()
        g.src = Src()
        rows = backtest.outside_sample(g, "Adaptation", "Seed", "2023-06", set(g.nodes))
        self.assertEqual([r["title"] for r in rows], ["A later paper"])

    def test_model_cutoff_marks_illustrative(self):
        g, llm, nodes = grown()
        os.environ["TASTECAL_MODEL_CUTOFF"] = "2030-01"
        try:
            check = backtest.run(g, llm, nodes, {"field": "Adaptation"})
        finally:
            del os.environ["TASTECAL_MODEL_CUTOFF"]
        self.assertTrue(check["illustrative"])
        self.assertIn("illustrative", check["note"])


if __name__ == "__main__":
    unittest.main()
