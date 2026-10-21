"""Report template, v2 data contract: no reading-notes section (the notes are what the taste calibration measures
papers on, and are not shown), the "What's next" section, and the work card's context from the audit.

The static checks always run. The browser checks run the page's script in headless Chromium and
are skipped when Playwright or a Chromium build is not available.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tastecal.report import render  # noqa: E402
from tastecal.report.i18n_zh import localize  # noqa: E402

CHROMIUM = os.environ.get("TASTECAL_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def gates(verdict, **kw):
    g = {"verdict": verdict, "basis": "full text", "delivery": "delivered", "delivered": "It does what it says.",
         "reason_type": "mechanism", "reason": "A stated mechanism.", "robustness": "repeats",
         "robustness_note": "Two benchmarks.", "reaction": {}, "why": f"{verdict} work."}
    g.update(kw)
    return g


def assessment(flag, score, pct):
    return {"flag": flag, "why": f"{flag} on the evidence.", "contribution": {"score": score},
            "attention": {"pct": pct, "basis": "citations"}}


# A small graph with gates and an audit, and none of the v2 fields.
BASE = {
    "schema": "deepanalyze.graph/1",
    "meta": {"seed": "s", "generator": "test"},
    "field": {"name": "Test field", "driving_forces": [{"id": "F1", "name": "Force", "threads": ["T1", "T2"]}]},
    "threads": [{"id": "T1", "name": "Thread one", "force": "F1", "question": "Q1?", "status": "open"},
                {"id": "T2", "name": "Thread two", "force": "F1", "question": "Q2?", "status": "active"}],
    "problems": [{"id": "P1", "text": "A problem nobody has solved.", "status": "open", "thread": "T1", "raised_by": ["s"]}],
    "nodes": [
        {"id": "s", "title": "Seed Paper", "short": "SeedNet", "kind": "paper", "role": "seed", "date": "2022-12",
         "threads": ["T1", "T2"], "card": {"summary": "x"},
         "gates": gates("solid"), "assessment": assessment("fair", 0.6, 0.7)},
        {"id": "a", "title": "Alpha", "short": "Alpha", "kind": "paper", "role": "improvement", "date": "2025-03",
         "threads": ["T1"], "card": {"summary": "y"},
         "gates": gates("treasure", robustness="single", attractiveness=0.7, taste_why="Close to the profile."),
         "assessment": assessment("hidden-gem", 0.7, 0.2)},
        {"id": "b", "title": "Beta", "short": "Beta", "kind": "paper", "role": "branch", "date": "2025-08",
         "threads": ["T2"], "card": {"summary": "z"},
         "gates": gates("incremental", reason_type="analogy", robustness="single", fold=True,
                        fold_reason={"summary": "An analogy and one setting.", "evidence": ["Table 1 only."]}),
         "assessment": assessment("skip", 0.3, 0.4)},
        {"id": "c", "title": "Gamma", "short": "Gamma", "kind": "paper", "role": "frontier", "date": "2026-02",
         "threads": ["T2"], "card": {"summary": "w"},
         "gates": gates("solid"), "assessment": assessment("overhyped", 0.4, 0.9)},
    ],
    "edges": [{"source": "s", "target": "a", "type": "resolves", "label": "fixes it", "confidence": "stated"},
              {"source": "s", "target": "b", "type": "extends", "label": "builds on it", "confidence": "inferred"},
              {"source": "a", "target": "c", "type": "extends", "label": "builds on it", "confidence": "inferred"}],
    "gates": {"today": "2026-10", "taste": True, "method": "Four gates.", "caveats": ["A reading aid."]},
    "audit": {"today": "2026-10", "method": "Blind scores.", "caveats": ["Candidates only."]},
}


def with_v2(graph, zh=False):
    """Add every v2 field. Data strings are Chinese for the zh variant, as a zh run would write them."""
    g = copy.deepcopy(graph)
    t = (lambda en, cn: cn) if zh else (lambda en, cn: en)
    if zh:
        g["meta"]["language"] = "zh-CN"
    by = {n["id"]: n for n in g["nodes"]}
    by["a"]["gates"].update(basis="abstract", source="abstract only")
    by["b"]["gates"].update(checks={"numbers": "mismatch", "numbers_note": t("Table 2 differs.", "表 2 不一致。"),
                                    "fair_baselines": "no", "baselines_note": t("Only the method was tuned.", "只调了本文方法。"),
                                    "novelty_ablation": "no", "code": "none"},
                            fails_when_stated=False, source="arXiv HTML")
    by["c"]["gates"].update(checks={"numbers": "match", "fair_baselines": "yes", "novelty_ablation": "yes",
                                    "code": "released", "code_note": "https://example.org/code"},
                            fails_when_stated=True, source="local file")
    g["gates"]["taste_name"] = t("practitioner", "实践派")
    g["quality"] = {"disagreements": [
        {"id": "c", "gate": "solid", "audit": "overhyped", "note": t("Holds up, but got more notice than it earned.", "站得住，但关注多于贡献。")},
        {"id": "b", "gate": "incremental", "audit": "skip", "note": t("Both say little is new.", "两边都认为新意不多。")},
    ]}
    g["outlook"] = {
        "today": "2026-10", "window_months": 12,
        "active": [{"thread": "T1", "nodes": ["a"]}, {"thread": "T2", "nodes": ["c", "b"]}],
        "next_steps": [
            {"problem": "P1", "text": t("What if the label is wrong?", "标注错了怎么办？"), "attempts": ["a", "b"],
             "settle": t("Train with noisy labels on purpose.", "故意用带噪声的标注训练。")},
            {"text": t("Does the order matter?", "顺序重要吗？"), "attempts": ["c"], "settle": t("Swap the order.", "交换顺序。")},
        ],
        "assumptions": [{"text": t("Labels are correct.", "标注是对的。"), "threads": ["T1"], "nodes": ["s", "a"],
                         "if_broken": t("Every method needs a label check first.", "每种方法都要先检查标注。")}],
        "note": t("A new paradigm cannot be predicted.", "新范式无法预测。"),
    }
    return g


# Reader-visible English that the v2 template adds. None of it may survive a zh render.
NEW_UI = [
    "What's next", "Who is working on what now",
    "Active now", "months</span>", "Open questions", "Closest attempts:", "Would settle it:", "Shared assumptions",
    "If it is wrong:", "<h3>Context</h3>",
    '"Not read in full"', "Only the abstract could be read", "Only a short summary could be read",
]
# The same strings as they appear on the page once the script has run (English render).
NEW_VISIBLE = [
    "What's next", "Active now", "Last 12 months",
    "Open questions", "Closest attempts:", "Would settle it:", "Shared assumptions", "If it is wrong:", "Context",
]
# What the reading-notes section used to show: none of it is on the page any more.
GONE = ['<section id="quality"', 'id="toc-quality"', 'id="gates"', 'id="dr-gates"', "<h3>Reading notes</h3>",
        "What each paper shows", "How well your taste profile predicts you", "Rate these next", "function gBlock",
        "function renderGates", "function renderQuality", "function checksBlock", "Taste profile:"]


def strip_data(page: str) -> str:
    return re.sub(r'(<script id="da-data" type="application/json">).*?(</script>)', r"\1\2", page, flags=re.S)


def embedded(page: str) -> dict:
    m = re.search(r'<script id="da-data" type="application/json">(.*?)</script>', page, flags=re.S)
    return json.loads(m.group(1))


class StaticTest(unittest.TestCase):
    def setUp(self):
        with open(render.TEMPLATE, encoding="utf-8") as f:
            self.tpl = f.read()

    def test_no_reading_notes_section(self):
        page = render.render_html(BASE)
        for gone in GONE + ['<section id="gates"', '<section id="audit"', "toc-gates", "toc-audit"]:
            self.assertNotIn(gone, page)
        self.assertNotIn('<section id="check"', page)          # the backtest is no longer shown
        # What's next sits after the story and before the method
        self.assertLess(page.index('<section id="story"'), page.index('<section id="next"'))
        self.assertLess(page.index('<section id="next"'), page.index('<section id="method"'))
        self.assertEqual(embedded(page), BASE)                  # the notes stay in the data, for `fit`

    def test_examples_render_in_both_languages(self):
        for name in ("uniad-50", "hugcl-50"):
            path = os.path.join(ROOT, "examples", name, "graph.json")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                g = json.load(f)
            for lang in ("en", "zh-CN"):
                page = render.render_html(dict(g, meta=dict(g.get("meta") or {}, language=lang)))
                self.assertNotIn('<section id="quality"', page)

    def test_fixture_embeds_every_new_field(self):
        g = with_v2(BASE)
        page = render.render_html(g)
        data = embedded(page)
        self.assertEqual(data["quality"], g["quality"])
        self.assertEqual(data["outlook"], g["outlook"])
        self.assertEqual(data["gates"]["taste_name"], "practitioner")
        for hook in ('id="next"', 'id="nx-active"', 'id="nx-steps"', 'id="nx-assume"', 'id="nx-note"',
                     "function renderNext", "function auBlock"):
            self.assertIn(hook, page)
        for gone in GONE:
            self.assertNotIn(gone, page)

    def test_every_new_ui_string_has_a_chinese_pair(self):
        missing_en = [s for s in NEW_UI if s not in self.tpl]
        self.assertEqual(missing_en, [], "the list above no longer matches the template")
        zh = localize(self.tpl)
        left = [s for s in NEW_UI if s in zh]
        self.assertEqual(left, [])
        for cn in ("接下来往哪走", "正在进行", "未解的问题", "最接近的尝试：", "能定论的实验：", "共同的假设",
                   "如果它不成立：", "未读全文", "背景"):
            self.assertIn(cn, zh)

    def test_zh_fixture_render_has_no_new_english(self):
        page = render.render_html(with_v2(BASE, zh=True))
        chrome = strip_data(page)
        left = [s for s in NEW_UI if s in chrome]
        self.assertEqual(left, [])
        # values the script compares against stay as the data writes them
        self.assertIn('n.gates.basis !== "full text"', chrome)


def _browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, None
    try:
        pw = sync_playwright().start()
    except Exception:
        return None, None
    try:
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        return pw, pw.chromium.launch(**kw)
    except Exception:
        pw.stop()
        return None, None


class BrowserTest(unittest.TestCase):
    """Runs the page script; checks what a reader actually sees."""

    @classmethod
    def setUpClass(cls):
        cls.pw, cls.browser = _browser()
        if not cls.browser:
            raise unittest.SkipTest("Playwright with Chromium is not available")
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, graph, name, width=1400):
        path = os.path.join(self.tmp.name, name + ".html")
        render.write_report(graph, path)
        page = self.browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
        page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda r: r.abort())
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("file://" + path)
        page.wait_for_timeout(150)
        self.addCleanup(page.close)
        self.assertEqual(errors, [])
        return page

    def visible(self, page, sel):
        return page.evaluate("(s) => { const e = document.querySelector(s); return !!e && !e.closest('[hidden]') && e.getClientRects().length > 0; }", sel)

    def text(self, page, sel):
        return page.evaluate("(s) => Array.from(document.querySelectorAll(s)).map((e) => e.textContent).join(' | ')", sel)

    def count(self, page, sel):
        return page.evaluate("(s) => document.querySelectorAll(s).length", sel)

    def show(self, page, tab):
        """Pick a tab of the first part, as a reader does from the bar."""
        page.evaluate("(t) => document.querySelector(`.line[data-part=logic] [data-tab=${t}]`).click()", tab)

    def open_card(self, page, nid):
        """Open a work's card from a chip naming it (here, in What's next)."""
        page.evaluate("(id) => document.querySelector(`.mention[data-node=\"${id}\"]`).click()", nid)

    def test_old_graph_has_no_notes_tab(self):
        p = self.open(BASE, "base")
        self.assertEqual(self.count(p, "[data-tab=quality]"), 0)
        self.assertEqual(self.count(p, "#quality, #gates, #gt-all, #q-facts"), 0)
        for sel in ("#next", "#toc-next", "#audit", "#q-dis"):
            self.assertFalse(self.visible(p, sel), sel)
        p.evaluate("() => { location.hash = '#logic/quality'; }")          # an old link lands on the first tab
        p.wait_for_timeout(50)
        self.assertTrue(self.visible(p, "#mechanism"))

    def test_fixture_shows_every_new_block(self):
        p = self.open(with_v2(BASE), "v2")
        self.assertTrue(self.visible(p, "#toc-next"))
        self.show(p, "next")
        for sel in ("#next", "#nx-active", "#nx-steps", "#nx-assume", "#nx-note"):
            self.assertTrue(self.visible(p, sel), sel)
        self.assertEqual(self.count(p, "#nx-active li"), 2)
        self.assertIn("Last 12 months", self.text(p, "#nx-active h3"))
        self.assertIn("Feb 2026", self.text(p, "#nx-active li"))
        self.assertEqual(self.count(p, "#nx-steps li"), 2)
        self.assertEqual(self.count(p, "#nx-steps .ps.open"), 1)
        self.assertIn("Would settle it:", self.text(p, "#nx-steps li"))
        self.assertEqual(self.count(p, "#nx-assume li .tchip"), 1)
        self.assertIn("If it is wrong:", self.text(p, "#nx-assume li"))
        self.assertIn("cannot be predicted", self.text(p, "#nx-note"))

    def test_card_has_context_but_no_reading_notes(self):
        p = self.open(with_v2(BASE), "v2-drawer")
        self.show(p, "next")
        for nid in ("a", "b"):
            self.open_card(p, nid)
            self.assertTrue(self.visible(p, "#dr-audit"))
            self.assertIn("Context", self.text(p, "#dr-audit h3"))
            self.assertEqual(self.count(p, "#dr-gates"), 0)
            self.assertNotIn("Reading notes", self.text(p, "#drawer"))
            self.assertNotIn("Close to the profile", self.text(p, "#drawer"))     # an old taste score is not shown

    def test_zh_fixture_shows_no_new_english(self):
        p = self.open(with_v2(BASE, zh=True), "v2-zh", width=390)
        self.show(p, "next")
        seen = p.evaluate("() => [document.querySelector('.navbar'), document.getElementById('next')].map((e) => e.innerText).join('\\n')")
        for nid in ("a", "b"):
            self.open_card(p, nid)
            seen += "\n" + p.evaluate("() => document.getElementById('drawer').innerText")
            seen += "\n" + p.evaluate("() => Array.from(document.querySelectorAll('[title]')).map((e) => e.title).join('\\n')")
        left = [s for s in NEW_VISIBLE if s in seen]
        self.assertEqual(left, [])
        for cn in ("接下来往哪走", "近 12 个月", "背景", "机制"):
            self.assertIn(cn, seen)
        self.assertEqual(p.evaluate("document.documentElement.scrollWidth"), 390)


if __name__ == "__main__":
    unittest.main()
