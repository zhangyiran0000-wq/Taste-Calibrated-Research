"""Works not read in full: the seed's card from its full text, the file name to give a PDF, and `missing`."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tastecal import cli  # noqa: E402
from tastecal.core.config import Config  # noqa: E402
from tastecal.core.model import Item  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tastecal.sources.fulltext import card_excerpt, local_file, suggested_name  # noqa: E402
from fakes import FakeLLM, FakeSource  # noqa: E402


class NamesTest(unittest.TestCase):
    def test_suggested_name_is_matched_back(self):
        d = tempfile.mkdtemp()
        item = Item(id="x1", title="Human-guided continual learning", ids={"doi": "10.1038/s41467-026-77370-x"})
        node = {"id": "x1", "title": item.title, "url": ""}
        name = suggested_name(node, item)
        self.assertEqual(name, "10.1038_s41467-026-77370-x.pdf")
        open(os.path.join(d, name), "w").close()
        self.assertTrue(local_file(node, item, d))
        self.assertEqual(suggested_name({"id": "y", "title": "A Study of Things", "url": "https://arxiv.org/abs/2401.01234"}),
                         "2401.01234.pdf")

    def test_card_excerpt_keeps_start_and_conclusion(self):
        text = "Abstract. We do X.\n" + "intro " * 2000 + "\n6 Conclusion\nIt fails on night scenes.\n" + \
               "\nReferences\n" + "[1] ref " * 500
        ex = card_excerpt(text)
        self.assertTrue(ex.startswith("Abstract. We do X."))
        self.assertIn("It fails on night scenes.", ex)
        self.assertNotIn("[1] ref", ex)
        self.assertLess(len(ex), 7500)


class JunkTitleTest(unittest.TestCase):
    def test_broken_records_are_dropped(self):
        from tastecal.core.model import junk_title
        from tastecal.sources.semantic_scholar import to_item
        self.assertTrue(junk_title("and s"))
        self.assertTrue(junk_title("Machine Learning manuscript No. (will be inserted by the editor) Search"))
        for real in ("Mask R-CNN", "The Unreasonable Effectiveness of Data", "Attention Is All You Need", "场景生成方法"):
            self.assertFalse(junk_title(real), real)
        self.assertIsNone(to_item({"paperId": "x", "title": "and s"}))


class SeedTextTest(unittest.TestCase):
    def test_seed_card_reads_the_local_pdf_text(self):
        d = tempfile.mkdtemp()
        llm = FakeLLM()
        src = FakeSource()
        seed = src.resolve("seed")
        with open(os.path.join(d, seed.id + ".txt"), "w", encoding="utf-8") as f:
            f.write("FULLTEXT-MARKER " + "body " * 1500)
        Grower(Config(budget=4, papers_dir=d), src, llm).run("seed")
        first = next(p for t, p in llm.prompts if t == "cards")
        self.assertIn("FULLTEXT-MARKER", first)
        self.assertIn("excerpts of the full paper", first)

    def test_without_full_text_the_seed_uses_its_abstract(self):
        llm = FakeLLM()
        with self.assertLogs("tastecal.grow", level="WARNING") as logs:
            Grower(Config(budget=4, papers_dir=tempfile.mkdtemp()), FakeSource(), llm).run("seed")
        self.assertIn("no full text", " ".join(logs.output))
        first = next(p for t, p in llm.prompts if t == "cards")
        self.assertNotIn("excerpts of the full paper", first)


class MissingTest(unittest.TestCase):
    def test_lists_unread_works_and_rated_papers(self):
        d = tempfile.mkdtemp()
        g = {"nodes": [
            {"id": "a", "title": "Alpha Method", "url": "https://doi.org/10.1/abc", "gates": {"basis": "full text"}},
            {"id": "b", "title": "Beta Method", "url": "https://doi.org/10.1234/beta.5678", "gates": {"basis": "card"}},
            {"id": "c", "title": "Gamma Method", "url": "", "assessment": {"flag": "thin"}}],
            "audit": {"calibration": {"anchors": [
                {"ref": "Rated One", "title": "Rated One", "url": "https://arxiv.org/abs/2401.00001", "basis": "abstract"},
                {"ref": "Rated Two", "title": "Rated Two", "blind": 0.5, "basis": "full text"}]}}}
        open(os.path.join(d, "10.1234_beta.5678.pdf"), "w").close()
        rows = cli.missing_works(g, d)
        self.assertEqual([r["title"] for r in rows], ["Beta Method", "Gamma Method", "Rated One"])
        self.assertTrue(rows[0]["found"])
        self.assertEqual(rows[2]["file"], "2401.00001.pdf")
        gp = os.path.join(d, "graph.json")
        with open(gp, "w", encoding="utf-8") as f:
            json.dump(g, f)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["missing", gp, "--papers-dir", d])
        out = buf.getvalue()
        self.assertIn("[found]", out)
        self.assertIn("[missing]", out)
        self.assertIn("tastecal assess", out)


if __name__ == "__main__":
    unittest.main()
