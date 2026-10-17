"""Simplified-Chinese UI chrome: every pair matches, no English chrome is left, English stays as it was."""
from __future__ import annotations

import html
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.report import render  # noqa: E402
from tastecal.report.i18n_zh import PAIRS, is_zh, localize  # noqa: E402

GRAPH = {
    "schema": "deepanalyze.graph/1",
    "meta": {"seed": "s", "generator": "test"},
    "field": {"name": "Test field", "driving_forces": [{"id": "F1", "name": "Force", "threads": ["T1"]}]},
    "threads": [{"id": "T1", "name": "Thread", "force": "F1", "question": "Q?", "status": "open",
                 "ladder": {"rungs": [{"kind": "symptom", "text": "a"}, {"kind": "root", "text": "b"}]}}],
    "nodes": [
        {"id": "s", "title": "Seed Paper", "short": "SeedNet", "kind": "paper", "role": "seed", "date": "2022-12",
         "threads": ["T1"], "card": {"summary": "x"}},
        {"id": "a", "title": "Alpha", "short": "Alpha", "kind": "paper", "role": "improvement", "date": "2023-05",
         "threads": ["T1"], "card": {"summary": "y"}},
    ],
    "edges": [{"source": "s", "target": "a", "type": "resolves", "label": "fixes it", "confidence": "stated"}],
}

# English UI phrases that must not survive in a zh render (template text only, data excluded).
ENGLISH_UI = [
    "How the field works", "Who solved whose problem", "Why each thread is hard", "Read it as a story",
    "Does the explanation hold?", "What holds up", "Attention versus contribution", "How this map was grown",
    "Driving forces", "Outside pressure", "Knock-on effects", "Still open", "Blogs &amp; reports", "Fit width",
    "Turning point", "Outside driver", "Folded works", "Show everything", "Showing the links of",
    "resolves a limitation of", "was inspired by", "competes with", "works explained by at least one driving force",
    "Raised by", "addressed by", "claimed, not delivered", ">via ", "as of ", "works gated", "other attempt",
    "Treasure candidate", "Claim not delivered", "Possible hidden gem", "Possibly overhyped", "Safe to skip",
    "Fairly valued", "Too early to tell", "Hardware limit", "Mathematical fact", "Outside driver",
    "Not on the map", "not on the map", "Open the source", "Key insight", "Leaves open", "Builds on", "Led to",
    "Problems it addresses", "Adversarial review", "Claim vs delivery", "Field reaction", "Check next",
    "Partly delivered", "Analogy only", "No reason given", "One setting", "Unequal tuning", "Stated in the source",
    "\"Jan\"", "\"Dec\"", "citations per year", "GitHub stars per year", "lineage of", "Hover a station",
    "Prediction cutoff", "No later match", "Realised", "Full problem ledger", "Read the seed", "Synthesize",
    "Hidden gem?", "Overhyped?", "\"Classic\"", "\"Noise\"", "Fold these works back", "click to ",
    "Symptom", "\"Why?\"", "Show on map", "None recorded", "Close details", "Work details", "Lineage map",
]


def strip_data(page: str) -> str:
    return re.sub(r'(<script id="da-data" type="application/json">).*?(</script>)', r"\1\2", page, flags=re.S)


def with_lang(lang):
    g = json.loads(json.dumps(GRAPH))
    if lang is not None:
        g["meta"]["language"] = lang
    return g


class I18nZhTest(unittest.TestCase):
    def setUp(self):
        with open(render.TEMPLATE, encoding="utf-8") as f:
            self.tpl = f.read()

    def test_every_pair_matches_the_template(self):
        missing = [en for en, _ in PAIRS if en not in self.tpl]
        self.assertEqual(missing, [])
        out = localize(self.tpl)
        self.assertIn(render.MARKER, out)
        self.assertIn("__TITLE__", out)

    def test_localize_raises_on_template_drift(self):
        with self.assertRaises(ValueError):
            localize(self.tpl.replace("How the field works", "How the field operates"))

    def test_language_detection(self):
        self.assertTrue(is_zh(with_lang("zh-CN")))
        self.assertTrue(is_zh(with_lang("zh")))
        self.assertTrue(is_zh(with_lang("ZH-Hans")))
        self.assertFalse(is_zh(with_lang("en")))
        self.assertFalse(is_zh(with_lang(None)))

    def test_zh_render_has_no_english_ui(self):
        page = render.render_html(with_lang("zh-CN"))
        self.assertIn('<html lang="zh-CN">', page)
        self.assertIn("<title>SeedNet 脉络</title>", page)
        self.assertIn('"Noto Sans CJK SC"', page)
        chrome = strip_data(page)
        left = [p for p in ENGLISH_UI if p in chrome]
        self.assertEqual(left, [])
        # values the script compares against stay English
        for kept in ('x.basis !== "full text"', 'p.overlap === "same idea"', 'e.confidence === "stated"',
                     'r.kind === "symptom"', 'n.kind !== "paper"', 'verdict === "not-delivered"'):
            self.assertIn(kept, chrome)
        frag = render.render_html(with_lang("zh-CN"), fragment=True)
        self.assertNotIn("<html", frag)
        self.assertIn("谁解决了谁的问题", frag)

    def test_english_render_is_unchanged(self):
        for lang in (None, "en", "en-US"):
            g = with_lang(lang)
            data = json.dumps(g, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
            body = self.tpl.replace(render.MARKER, data).replace("__TITLE__", html.escape("SeedNet Lineage"))
            self.assertEqual(render.render_html(g), render.STANDALONE_HEAD + body + render.STANDALONE_TAIL)
            self.assertEqual(render.render_html(g, fragment=True), body)
            self.assertEqual(render.page_title(g), "SeedNet Lineage")


if __name__ == "__main__":
    unittest.main()
