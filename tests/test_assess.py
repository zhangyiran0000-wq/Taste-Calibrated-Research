"""Audit stage: blinding, attention, flags, and the whole stage on the fake corpus.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tastecal.judge.audit import (Auditor, Thresholds, attention, audit, blind_pack, final_flag,  # noqa: E402
                                quadrant, targets_from_grower)
from tastecal.core.config import Config  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tastecal.report.render import render_html  # noqa: E402
from tastecal.core.schema import validate  # noqa: E402
from tastecal.lineage.synthesize import synthesize  # noqa: E402
from fakes import CORPUS, FakeLLM, FakeSource  # noqa: E402

TODAY = "2026-10"

PACK = {
    "id": "uniad", "title": "Planning-oriented Autonomous Driving", "short": "UniAD", "authors": "Hu et al.",
    "date": "2022-12", "venue": "CVPR 2023 (Best Paper Award)", "url": "https://arxiv.org/abs/2212.10156",
    "citations": 906, "citations_note": "OpenAlex W4386076520", "type": "method",
    "card": {"inherits": "Modular stacks lose information", "move": "UniAD chains perception, prediction and planning queries",
             "insight": "Plan-oriented joint training", "leaves": ["Open-loop metrics only"]},
    "claims": [{"claim": "UniAD beats prior planners", "support": "partial",
                "evidence": "Table 7 (arXiv 2212.10156); CVPR 2023 Oral; 4.7k GitHub stars"}],
    "fairness_notes": ["Hu et al. use ego status in BEV"],
    "precedents": [{"title": "ST-P3", "year": 2022, "overlap": "partial", "cited_by_target": True, "note": "earlier joint model"}],
    "uptake": [{"citer": "NAVSIM (2024-06)", "role": "baseline", "sentence": "We compare with UniAD [12] (Hu et al., 2023)."}],
    "later_challenges": ["Ego-status paper shows UniAD's L2 is matched by an MLP; cited by 906 papers"],
    "notes": "Code at github.com/OpenDriveLab/UniAD (4,700 stars). Planning-Oriented Autonomous Driving won the award.",
}


class BlindingTest(unittest.TestCase):
    def test_blind_pack_hides_identity_and_fame(self):
        text = blind_pack(PACK)
        for leak in ("UniAD", "Planning-oriented Autonomous Driving", "Planning-Oriented", "Hu et al", "CVPR",
                     "Best Paper", "Oral", "2212.10156", "906", "4.7k", "4,700", "github.com", "OpenDriveLab", "NAVSIM",
                     "W4386076520"):
            self.assertNotIn(leak, text, leak)
        self.assertIn("[THIS WORK]", text)
        self.assertIn("ST-P3", text)              # other works keep their names
        self.assertIn("2022-12", text)            # the date stays: novelty is judged against earlier work
        self.assertIn("baseline", text)


class AttentionTest(unittest.TestCase):
    def test_lower_bounds_and_stars(self):
        packs = [
            {"id": "big", "date": "2022-12", "citations": 900, "citations_note": "venue record"},
            {"id": "mid", "date": "2023-06", "citations": 120, "citations_note": "venue record"},
            {"id": "small", "date": "2023-06", "citations": 10, "citations_note": "venue record"},
            {"id": "undercounted", "date": "2024-02", "citations": 3, "citations_note": "arXiv record only; severe undercount"},
            {"id": "starred", "date": "2024-02", "citations": 2, "citations_note": "lower bound", "stars": 3000},
            {"id": "other", "date": "2024-02", "citations": 50, "citations_note": "venue record", "stars": 100},
        ]
        att = attention(packs, TODAY)
        self.assertGreater(att["big"]["pct"], att["small"]["pct"])
        self.assertTrue(att["undercounted"]["lower_bound"])
        self.assertFalse(att["starred"]["lower_bound"])          # stars stand in for the missing citations
        self.assertEqual(att["starred"]["basis"], "stars")
        self.assertEqual(att["other"]["basis"], "citations+stars")
        th = Thresholds()
        # low attention that is only a lower bound is "unknown", never a hidden gem
        self.assertEqual(quadrant(0.9, att["undercounted"]["pct"], True, th), "unknown")
        self.assertEqual(quadrant(0.9, 0.1, False, th), "gem")
        self.assertEqual(quadrant(0.2, 0.9, True, th), "hyped")   # high attention stands even as a lower bound

    def test_final_flags(self):
        th = Thresholds()
        self.assertEqual(final_flag("hidden-gem", {"verdict": "substantial"}, 30, th), "hidden-gem")
        self.assertEqual(final_flag("hidden-gem", {"verdict": "modest"}, 30, th), "fair")
        self.assertEqual(final_flag("overhyped", {"verdict": "negligible"}, 30, th), "overhyped")
        self.assertEqual(final_flag("overhyped", {"verdict": "substantial"}, 30, th), "fair")
        self.assertEqual(final_flag("skip", {"verdict": "modest"}, 30, th), "skip")
        self.assertEqual(final_flag(None, None, 30, th), "fair")
        self.assertEqual(final_flag("overhyped", {"verdict": "negligible"}, 6, th), "too-early")


class StarsTest(unittest.TestCase):
    def test_repository_stars_from_arxiv_page(self):
        class FakeHttp:
            def get_text(self, url, **kw):
                return "<p>Code is available at https://github.com/foo/bar.git.</p>"

            def get_json(self, url, **kw):
                assert url == "https://api.github.com/repos/foo/bar", url
                return {"stargazers_count": 42}
        item = CORPUS["seed"]
        item.ids["arxiv"] = "2101.00001"
        pack = {}
        Auditor(Config(), FakeSource(), FakeLLM(), http=FakeHttp())._stars(item, pack)
        del item.ids["arxiv"]
        self.assertEqual((pack.get("stars"), pack.get("repo")), (42, "foo/bar"))


class AuditStageTest(unittest.TestCase):
    def test_thin_evidence_is_never_flagged(self):
        cfg = Config(budget=8, max_rounds=3, use_openalex=False, use_web=False, cache_dir=tempfile.mkdtemp(),
                     assess=True, assess_max=12, assess_pool=3)
        llm = FakeLLM()
        g = Grower(cfg, FakeSource(), llm).run("seed")
        graph = synthesize(g, llm, "seed")
        targets, pool = targets_from_grower(g, graph)
        audit(graph, targets, Auditor(cfg, FakeSource(), llm, today=TODAY), pool)   # no full texts: abstracts only
        flags = {n["assessment"]["flag"] for n in graph["nodes"]}
        self.assertTrue(flags <= {"thin", "too-early"}, flags)
        self.assertNotIn("audit_judge", llm.tasks)                   # nothing to review
        self.assertNotIn("audit_contribution", llm.tasks)            # and no blind score from a summary
        for n in graph["nodes"]:
            self.assertIsNone(n["assessment"]["contribution"]["score"])
            self.assertEqual(n["assessment"]["quadrant"], "unscored")
        self.assertEqual(validate(graph), [])
        render_html(graph)                                           # the report still draws

    def test_audit_on_fake_corpus(self):
        cfg = Config(budget=8, max_rounds=3, use_openalex=False, use_web=False, cache_dir=tempfile.mkdtemp(),
                     assess=True, assess_max=12, assess_pool=3)
        llm = FakeLLM()
        g = Grower(cfg, FakeSource(), llm).run("seed")
        graph = synthesize(g, llm, "seed")
        targets, pool = targets_from_grower(g, graph)
        au = Auditor(cfg, FakeSource(), llm, today=TODAY)
        au._fulltext = lambda item: ((item.abstract + " ") * 30, "full text")     # as if every paper was found in full
        audit(graph, targets, au, pool)
        self.assertEqual(validate(graph), [])

        by_title = {n["title"]: n for n in graph["nodes"]}
        weak = by_title["Beta Adapters"]["assessment"]
        strong = by_title["Epsilon: Rank Allocation"]["assessment"]
        self.assertEqual(weak["candidate"], "overhyped")
        self.assertEqual(weak["flag"], "overhyped")
        self.assertEqual(strong["flag"], "hidden-gem")
        self.assertEqual(graph["audit"]["counts"]["hidden-gem"], 1)

        # Only flagged works are reviewed; everything else has no review.
        for n in graph["nodes"]:
            a = n["assessment"]
            self.assertEqual(bool(a["review"]), bool(a["candidate"]), n["title"])
        reviewed = sum(1 for n in graph["nodes"] if n["assessment"]["review"])
        self.assertEqual(llm.tasks.count("audit_judge"), reviewed)
        self.assertEqual(llm.tasks.count("audit_contribution"), len(targets) + len(pool))

        # The blind prompts never see titles, authors, venues or citation counts.
        counts = {str(i.citations) for i in CORPUS.values()}
        for task, prompt in llm.prompts:
            if task not in ("audit_contribution", "audit_advocate", "audit_critic", "audit_judge"):
                continue
            # Other works keep their names in the "earlier work" list; the work itself must not appear.
            head, _, rest = prompt.partition("Earlier work with a similar core idea")
            body = head + rest.partition("What later papers do with it")[2]
            for it in CORPUS.values():
                self.assertNotIn(it.title, body)
                self.assertNotIn(it.title.split(":")[0], body)
            for leak in ("Lovelace", "Turing", "TestConf", "example.org"):
                self.assertNotIn(leak, prompt)
            found = set(re.findall(r"\b\d+\b", prompt)) & counts
            self.assertFalse(found, f"{task} leaks a citation count: {found}")

        html = render_html(graph)
        self.assertIn('"audit":', html)


if __name__ == "__main__":
    unittest.main()
