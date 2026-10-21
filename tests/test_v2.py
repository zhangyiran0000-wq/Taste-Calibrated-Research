"""v2: plain language, the shared reading, full text from local files, outlook, disagreements, taste profiles."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tastecal.report import polish as style  # noqa: E402
from tastecal.core.config import Config  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tastecal.judge.gates import Gatekeeper, apply_gates, clean_gates, verdict  # noqa: E402
from tastecal.lineage.outlook import build as build_outlook  # noqa: E402
from tastecal.judge.quality import combine  # noqa: E402
from tastecal.core.schema import validate  # noqa: E402
from tastecal.sources.fulltext import find_fulltext, local_file  # noqa: E402
from tastecal.lineage.synthesize import synthesize  # noqa: E402
from tastecal.taste.profiles import list_profiles, load_profile  # noqa: E402
from fakes import FakeLLM, FakeSource  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def grown_graph():
    cfg = Config(budget=8, max_rounds=3, use_openalex=False, use_web=False, cache_dir=tempfile.mkdtemp())
    llm = FakeLLM()
    g = Grower(cfg, FakeSource(), llm).run("seed")
    return synthesize(g, llm, "seed"), g, llm, cfg


class StyleTest(unittest.TestCase):
    def test_lint_english(self):
        long = " ".join(["word"] * 35) + "."
        self.assertTrue(any("long sentence" in x for x in style.lint(long)))
        many = "[[a]], [[b]], [[c]] and [[d]] all tried it."
        self.assertTrue(any("4 works named" in x for x in style.lint(many)))
        self.assertTrue(any("praise word: novel" in x for x in style.lint("A novel method.")))
        self.assertEqual(style.lint("Hu et al. (2021) fixed it. Fig. 2 shows 3.5% gains."), [])

    def test_lint_chinese(self):
        long = "这是" + "很长的一句话" * 12 + "。"
        self.assertTrue(any("characters" in x for x in style.lint(long)))
        self.assertEqual(style.lint("它解决了显存问题。数据只需 1%。"), [])
        self.assertTrue(any("开创性" in x for x in style.lint("这是开创性的工作。")))

    def test_rewrite_must_keep_links_and_numbers(self):
        old = "[[a]] and [[b]] gained 4.8% on 20 cases."
        self.assertTrue(style.keeps_facts(old, "[[a]] gained 4.8% on 20 cases. So did [[b]]."))
        self.assertFalse(style.keeps_facts(old, "[[a]] gained 4.8% on 20 cases."))       # lost a link
        self.assertFalse(style.keeps_facts(old, "[[a]] and [[b]] gained a little on 20 cases."))  # lost a number

    def test_polish_rewrites_only_flagged_text(self):
        graph, _, llm, _ = grown_graph()
        graph["story"]["paragraphs"] = ["A remarkable start, and a second clause follows here.", "Short and fine."]
        stats = style.polish(graph, llm, "en")
        self.assertGreaterEqual(stats["rewritten"], 1)
        self.assertEqual(graph["story"]["paragraphs"][1], "Short and fine.")
        self.assertNotIn("remarkable", graph["story"]["paragraphs"][0])
        self.assertIn("style", graph["meta"])

    def test_system_note_sets_language(self):
        self.assertIn("Simplified Chinese", style.system_note("zh-CN"))
        self.assertIn("at most 25 words", style.system_note("en"))


class SharedReadingTest(unittest.TestCase):
    def test_audit_reuses_the_reading(self):
        from tastecal.judge.audit import Auditor
        graph, g, llm, cfg = grown_graph()
        keeper = Gatekeeper(cfg, llm)
        keeper.fulltext = lambda node, item=None: ("Section 1. " * 800, "full text", "local file")
        items = {n.item.id: n.item for n in g.nodes.values()}
        readings = keeper.read(graph, items)
        self.assertTrue(readings)
        aud = Auditor(cfg, FakeSource(), llm)
        seed = graph["meta"]["seed"]
        before = llm.tasks.count("audit_claims")
        pack = aud.gather(items[seed], {}, "SEED", [], readings[seed])
        self.assertEqual(llm.tasks.count("audit_claims"), before)        # no second read of the paper
        self.assertEqual(pack["claims"][0]["support"], "partial")
        keeper.run(graph, items, raw=readings)
        x = next(n["gates"] for n in graph["nodes"] if n["id"] == seed)
        self.assertEqual(x["source"], "local file")
        self.assertEqual(x["checks"]["code"], "released")
        self.assertNotIn("bogus", x["checks"])
        self.assertEqual(validate(graph), [])

    def test_unbounded_mechanism_is_not_a_reason(self):
        base = {"claimed": "c", "delivery": "delivered", "delivered": "d", "reason_type": "mechanism", "reason": "r",
                "robustness": "single", "levers": []}
        react = {"robust": False, "adopted_by": []}
        self.assertEqual(verdict(clean_gates(dict(base, fails_when_stated=True)), react, 0.9, None or _th()), "treasure")
        self.assertEqual(verdict(clean_gates(dict(base, fails_when_stated=False)), react, 0.9, _th()), "incremental")
        self.assertEqual(verdict(clean_gates(base), react, 0.9, _th()), "treasure")     # older answers without the field


def _th():
    from tastecal.judge.gates import GateThresholds
    return GateThresholds()


class FullTextTest(unittest.TestCase):
    def test_local_file_by_arxiv_id_and_title(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "2106.09685.txt"), "w") as f:
            f.write("full text " * 600)
        with open(os.path.join(d, "Overcoming catastrophic forgetting.md"), "w") as f:
            f.write("ewc text " * 600)
        node = {"id": "lora", "title": "LoRA", "url": "https://arxiv.org/abs/2106.09685"}
        self.assertTrue(local_file(node, None, d).endswith("2106.09685.txt"))
        text, basis, source = find_fulltext(node, None, None, d)
        self.assertEqual((basis, source), ("full text", "local file"))
        node2 = {"id": "ewc", "title": "Overcoming catastrophic forgetting in neural networks", "url": "https://doi.org/10.1073/pnas.1611835114"}
        self.assertTrue(local_file(node2, None, d).endswith(".md"))
        node3 = {"id": "x", "title": "Something else", "url": ""}
        self.assertEqual(find_fulltext(node3, None, None, d)[1], "card")


class OutlookTest(unittest.TestCase):
    def test_outlook_checks_ids(self):
        graph, _, llm, _ = grown_graph()
        build_outlook(graph, llm, today="2024-06")
        o = graph["outlook"]
        self.assertTrue(o["next_steps"] and o["assumptions"])
        self.assertNotIn("not-a-node", o["next_steps"][0]["attempts"])
        self.assertNotIn("T9", o["assumptions"][0]["threads"])
        self.assertEqual(validate(graph), [])

    def test_active_without_llm(self):
        graph, _, _, _ = grown_graph()
        latest = max(n["date"] for n in graph["nodes"])
        build_outlook(graph, None, today=latest[:7])
        ids = [x for a in graph["outlook"]["active"] for x in a["nodes"]]
        self.assertTrue(ids)
        self.assertNotIn(graph["meta"]["seed"], ids)


class QualityTest(unittest.TestCase):
    def test_disagreements(self):
        g = {"meta": {}, "gates": {}, "nodes": [
            {"id": "a", "gates": {"verdict": "solid"}, "assessment": {"flag": "skip"}},
            {"id": "b", "gates": {"verdict": "incremental"}, "assessment": {"flag": "hidden-gem"}},
            {"id": "c", "gates": {"verdict": "solid"}, "assessment": {"flag": "fair"}}]}
        out = combine(g)
        self.assertEqual([d["id"] for d in out], ["a", "b"])
        g["meta"]["language"] = "zh-CN"
        self.assertIn("盲评", combine(g)[0]["note"])


class TasteTest(unittest.TestCase):
    def test_profiles_and_paths(self):
        self.assertEqual([k for _, _, k in list_profiles()], ["yours"] * len(list_profiles()))   # none shipped
        self.assertEqual(load_profile("")[0], "")
        with self.assertRaises(FileNotFoundError):
            load_profile("no-such-profile")
        name, _, _ = load_profile(os.path.join(ROOT, "docs", "taste-template.md"))
        self.assertTrue(name)

    def test_taste_json_profiles(self):
        from tastecal.taste.profiles import default_spec, put_profile
        d = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(d)
        try:
            self.assertEqual(default_spec(), "")
            key = put_profile("My Taste", [{"ref": "ResNet", "score": 0.9, "comment": "clear"},
                                           {"ref": "Hype", "score": 0.2, "comment": ""}])
            self.assertEqual((key, default_spec()), ("my-taste", "my-taste"))
            name, text, path = load_profile("my-taste")
            self.assertEqual(name, "My Taste")
            self.assertIn("## Papers I liked\n- ResNet (my score 0.90): clear", text)
            self.assertIn("## Papers I disliked\n- Hype (my score 0.20)", text)
            self.assertEqual(path, "taste.json#my-taste")
        finally:
            os.chdir(cwd)

    def test_taste_name_reaches_the_report_data(self):
        graph, g, llm, cfg = grown_graph()
        raw = {graph["meta"]["seed"]: {"claimed": "c", "delivery": "delivered", "delivered": "d",
                                       "reason_type": "proof", "reason": "r", "robustness": "repeats", "basis": "full text"}}
        apply_gates(graph, raw, "2026-10", None, "practitioner")
        self.assertEqual(graph["gates"]["taste_name"], "practitioner")


if __name__ == "__main__":
    unittest.main()
