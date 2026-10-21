"""The combined report: the lineage in tabs, and the taste calibration as its second part when the run has one.

The static checks always run. The browser checks run the page's script in headless Chromium and are skipped when
Playwright or a Chromium build is not available.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from tastecal.report import axes_view, render  # noqa: E402
from tastecal.report.i18n_zh import localize  # noqa: E402
from tastecal.taste import axes  # noqa: E402
import test_axes  # noqa: E402
from test_report_v2 import BASE, CHROMIUM, _browser, with_v2  # noqa: E402


def taste_result():
    """A taste calibration as fit writes it (a scripted model, no network)."""
    return axes.run(test_axes.Scripted(), test_axes.graph(), test_axes.RATED)


def tokens(css: str, block: str) -> dict:
    """The colour tokens of one block of a stylesheet ("light" or "dark")."""
    if block == "light":
        body = re.search(r":root\{(.*?)\}", css, re.S).group(1)
    else:
        body = re.search(r':root\[data-theme="dark"\]\{(.*?)\}', css, re.S).group(1)
    return {k: v.strip() for k, v in re.findall(r"(--(?:bg|surface|surface-2|ink|ink-2|muted|hair|challenge|focus|ok|warn|l\d)):([^;]+);?", body)}


class StaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = taste_result()

    def test_without_a_taste_fit_there_is_one_part(self):
        page = render.render_html(BASE)
        self.assertNotIn(render.TASTE_MARKER, page)
        self.assertNotIn("taste-host", page.split('<script id="da-data"')[0])
        self.assertIn('id="parts"', page)                          # the part switch is there, and stays hidden

    def test_the_taste_part_sits_in_a_shadow_root(self):
        page = render.render_html(BASE, taste=self.res)
        self.assertNotIn(render.TASTE_MARKER, page)
        self.assertIn('<div id="taste-host"><template shadowrootmode="open"><style>', page)
        self.assertIn("window.tasteFit=function(R,opts)", page)
        part = page[page.index('<div id="taste-host">'):page.index("</template></div>")]
        for tab in axes_view.TAB_KEYS:
            self.assertIn(f'id="panel-{tab}"', part)
        self.assertNotIn('<nav class="tabs"', part)                  # the report's bar picks the tab
        self.assertEqual(part.count('tabindex=-1'), len(axes_view.TAB_KEYS))
        self.assertIn('id="fit-data"', part)
        # the graph data is still read from its own script, untouched by the taste part
        m = re.search(r'<script id="da-data" type="application/json">(.*?)</script>', page, flags=re.S)
        self.assertEqual(json.loads(m.group(1)), BASE)

    def test_zh_taste_part_has_no_english(self):
        page = render.render_html(with_v2(BASE, zh=True), taste=self.res)
        part = page[page.index('<div id="taste-host">'):page.index("</template></div>")]
        part = re.sub(r'<script type="application/json" id="fit-data">.*?</script>', "", part, flags=re.S)
        for en in ("Overview", "Clauses", "How it was fitted", "Trust in the result", "Papers compared", "Every paper towards y = x"):
            self.assertNotIn(en, part)
        for cn in ("结果可信度", "所有文章向 y = x 靠拢"):
            self.assertIn(cn, page)

    def test_map_papers_not_read_in_full_are_listed_with_their_file_name(self):
        g = test_axes.graph()
        thin = test_axes.node("m9", "Map m9 Abstract Only")
        thin["gates"] = dict(thin["gates"], basis="abstract")
        g["nodes"] += [thin, dict(test_axes.node("t9", "Iota Open Urban Simulator", kind="tool"), gates={"basis": "card"})]
        res = axes.enrich(dict(self.res), g)
        self.assertEqual([u["id"] for u in res["unread_map"]], ["m9"])          # a tool is never scored anyway
        self.assertTrue(res["unread_map"][0]["file"].endswith(".pdf"))
        for lang, head in (("en", "Not scored: only an abstract or a summary could be read"), ("zh-CN", "不打分：只读到了摘要")):
            html = axes_view.page(res, lang)
            self.assertIn(head, html)
            self.assertIn(res["unread_map"][0]["file"], html)
        self.assertNotIn("Not scored: only an abstract", axes_view.page(axes.enrich(dict(self.res), test_axes.graph()), "en"))

    def test_write_report_takes_the_taste_fit_beside_it(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "taste_fit.json"), "w", encoding="utf-8") as f:
            json.dump(self.res, f)
        path = render.write_report(BASE, os.path.join(d, "report.html"))
        with open(path, encoding="utf-8") as f:
            self.assertIn('id="taste-host"', f.read())
        render.write_report(BASE, path, taste=None)
        with open(path, encoding="utf-8") as f:
            self.assertNotIn('<div id="taste-host">', f.read())
        with open(os.path.join(d, "taste_fit.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(render.taste_beside(BASE, d))              # a broken file leaves the part out

    def test_the_standalone_page_and_the_report_share_their_colours(self):
        with open(render.TEMPLATE, encoding="utf-8") as f:
            tpl = f.read()
        css = tpl[tpl.index("<style>"):tpl.index("</style>")]
        for block in ("light", "dark"):
            mine, report = tokens(axes_view.TOKENS, block), tokens(css, block)
            self.assertTrue(report)
            self.assertEqual(mine, report, block)

    def test_every_new_string_has_a_chinese_pair(self):
        with open(render.TEMPLATE, encoding="utf-8") as f:
            tpl = f.read()
        zh = localize(tpl)
        for en in ("Lineage and logic", "Taste calibration", ">Mechanism<", ">Threads<", "Show on the map",
                   "Unlocked by these insights", "The lineage of"):
            self.assertIn(en, tpl)
            self.assertNotIn(en, zh)
        self.assertIn("Noto+Serif+SC", zh)                            # one Chinese serif on every system
        self.assertNotIn("Noto+Serif+SC", tpl)

    def test_cli_fit_redraw_writes_the_combined_report(self):
        from tastecal import cli
        d = tempfile.mkdtemp()
        g = json.loads(json.dumps(BASE))
        gp = os.path.join(d, "graph.json")
        with open(gp, "w", encoding="utf-8") as f:
            json.dump(g, f)
        with open(os.path.join(d, "taste_fit.json"), "w", encoding="utf-8") as f:
            json.dump(self.res, f)
        self.assertEqual(cli.main(["fit", gp, "--redraw"]), 0)
        with open(os.path.join(d, "report.html"), encoding="utf-8") as f:
            self.assertIn('id="taste-host"', f.read())
        self.assertTrue(os.path.exists(os.path.join(d, "taste_fit.html")))


class BrowserTest(unittest.TestCase):
    """Runs the page script; checks what a reader sees and can do."""

    @classmethod
    def setUpClass(cls):
        cls.pw, cls.browser = _browser()
        if not cls.browser:
            raise unittest.SkipTest("Playwright with Chromium is not available")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.res = taste_result()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, graph, name, taste=None, width=1400, hash_=""):
        path = os.path.join(self.tmp.name, name + ".html")
        render.write_report(graph, path, taste=taste)
        page = self.browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
        page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"), lambda r: r.abort())
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("file://" + path + hash_)
        page.wait_for_timeout(150)
        self.addCleanup(page.close)
        self.errors = errors
        self.assertEqual(errors, [])
        return page

    def js(self, page, expr, arg=None):
        return page.evaluate(expr, arg)

    def shown(self, page):
        """The part and tab in view, as the bar and the panels have them."""
        return self.js(page, """() => {
          const part = document.querySelector('main > .part:not([hidden])').dataset.part;
          const line = document.querySelector(`.line[data-part=${part}]`);
          const on = line.querySelector('[aria-selected=true]');
          const panels = part === 'logic' ? Array.from(document.querySelectorAll('#part-logic > .panel')).filter((s) => !s.classList.contains('off')).map((s) => s.id)
            : Array.from(document.getElementById('taste-host').shadowRoot.querySelectorAll('.panel')).filter((s) => getComputedStyle(s).display !== 'none').map((s) => s.id);
          return [part, on && on.dataset.tab, panels];
        }""")

    def test_one_tab_at_a_time_and_the_address_keeps_it(self):
        p = self.open(with_v2(BASE), "tabs")
        self.assertEqual(self.shown(p), ["logic", "mechanism", ["mechanism"]])
        self.assertTrue(self.js(p, "() => document.getElementById('parts').hidden"))     # no taste fit: one part
        p.click('.line[data-part=logic] [data-tab=map]')
        self.assertEqual(self.shown(p), ["logic", "map", ["map"]])
        self.assertGreater(self.js(p, "() => document.getElementById('mapsvg').getBoundingClientRect().width"), 300)
        self.assertTrue(p.url.endswith("#logic/map"))
        p.click('.line[data-part=logic] [data-tab=threads]')
        self.assertEqual(self.js(p, "() => Array.from(document.querySelectorAll('#threadrows > .thread')).filter((a) => !a.hidden).map((a) => a.id)"), ["thread-T1"])
        p.click('#thr-list [data-thread=T2]')
        self.assertEqual(self.js(p, "() => Array.from(document.querySelectorAll('#threadrows > .thread')).filter((a) => !a.hidden).map((a) => a.id)"), ["thread-T2"])
        self.assertEqual(self.js(p, "() => document.querySelector('#thr-list [data-thread=T2]').getAttribute('aria-selected')"), "true")
        # a link to a section that is gone lands on the first tab
        for old in ("#gates", "#logic/quality"):
            q = self.open(with_v2(BASE), "old-hash", hash_=old)
            self.assertEqual(self.shown(q), ["logic", "mechanism", ["mechanism"]])
        self.assertEqual(self.js(q, "() => document.querySelectorAll('[data-tab=quality]').length"), 0)

    def test_a_work_named_in_the_story_opens_where_you_are(self):
        g = json.loads(json.dumps(with_v2(BASE)))
        g["story"] = {"title": "T", "paragraphs": ["It started with [[a]]."]}
        p = self.open(g, "story", hash_="#logic/story")
        p.click("#s-body .mention[data-node=a]")
        self.assertEqual(self.shown(p)[1], "story")                   # still reading the story
        self.assertFalse(self.js(p, "() => document.getElementById('drawer').hidden"))
        p.click("#drawer [data-show-map]")
        self.assertEqual(self.shown(p)[1], "map")
        self.assertTrue(self.js(p, "() => document.querySelector('#drawer [data-show-map]').hidden"))
        self.assertIn("sel", self.js(p, "() => document.querySelector('#mapsvg .st[data-node=a]').getAttribute('class')"))

    def test_the_taste_part(self):
        g = with_v2(BASE)
        # an older run's taste check is in the data, and is never shown: the taste part is the only taste score
        g["gates"]["taste_check"] = {"usable": True, "n": 3, "agree": 2, "pairs": 3, "gap": 0.2,
                                     "papers": [{"title": "Alpha", "ref": "Alpha", "yours": 0.7, "predicted": 0.6}]}
        alone = self.open(g, "taste-alone")
        self.assertNotIn("How well your taste profile predicts you", self.js(alone, "() => document.body.innerText"))
        p = self.open(g, "taste", taste=self.res)
        self.assertFalse(self.js(p, "() => document.getElementById('parts').hidden"))
        self.assertTrue(self.js(p, "() => document.getElementById('part-taste').hidden"))
        p.click('.line[data-part=logic] [data-tab=next]')
        p.click('#parts [data-part=taste]')
        self.assertEqual(self.shown(p), ["taste", "overview", ["panel-overview"]])
        self.assertTrue(p.url.endswith("#taste/overview"))
        self.assertEqual(self.js(p, "() => Array.from(document.querySelectorAll('.line[data-part=taste] [data-tab]')).map((b) => b.dataset.tab)"),
                         list(axes_view.TAB_KEYS))
        p.click('.line[data-part=taste] [data-tab=papers]')
        self.assertEqual(self.shown(p), ["taste", "papers", ["panel-papers"]])
        # a paper opens the taste part's own card; going back to the lineage closes it
        p.locator("#taste-host").locator("#ptable tbody tr").first.click()
        self.assertFalse(self.js(p, "() => document.getElementById('taste-host').shadowRoot.getElementById('drawer').hidden"))
        p.keyboard.press("Escape")
        self.assertTrue(self.js(p, "() => document.getElementById('taste-host').shadowRoot.getElementById('drawer').hidden"))
        # a button inside the part takes its own bar along
        p.click('.line[data-part=taste] [data-tab=overview]')
        p.locator("#taste-host").locator("[data-goto=process]").click()
        self.assertEqual(self.shown(p), ["taste", "process", ["panel-process"]])
        p.click('#parts [data-part=logic]')
        self.assertEqual(self.shown(p)[0], "logic")
        self.assertEqual(self.shown(p)[1], "next")                    # back where you were
        q = self.open(with_v2(BASE), "taste-hash", taste=self.res, hash_="#taste/clauses")
        self.assertEqual(self.shown(q), ["taste", "clauses", ["panel-clauses"]])
        self.assertEqual(self.errors, [])

    def test_must_read_papers_are_marked(self):
        g = json.loads(json.dumps(with_v2(BASE)))
        next(n for n in g["nodes"] if n["id"] == "c")["must"] = True
        g["meta"]["must_missing"] = ["A paper nobody could find"]
        g["rounds"] = [{"round": 0, "expanded": [], "must": ["c"], "kept": 2, "new_problems": 1, "addressed": 0,
                        "note": "Read the seed and 1 must-read paper; open their limitations"}]
        p = self.open(g, "must", hash_="#logic/method")
        self.assertIn("Gamma", self.js(p, "() => document.querySelector('#r-body tr td:nth-child(2)').textContent"))
        meta = self.js(p, "() => document.getElementById('r-meta').textContent")
        self.assertIn("Must-read", meta)
        self.assertIn("A paper nobody could find", meta)
        p.click("#r-body .mention[data-node=c]")
        self.assertIn("Must-read, named by you", self.js(p, "() => document.querySelector('#drawer .dr-top').textContent"))

    def test_phone_width_has_no_side_scroll(self):
        for hash_ in ("#logic/mechanism", "#logic/threads", "#taste/overview", "#taste/process"):
            p = self.open(with_v2(BASE, zh=True), "phone", taste=self.res, width=390, hash_=hash_)
            self.assertEqual(self.js(p, "() => document.documentElement.scrollWidth"), 390, hash_)


if __name__ == "__main__":
    unittest.main()
