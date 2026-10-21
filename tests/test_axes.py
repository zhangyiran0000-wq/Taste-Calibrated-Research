"""Fitting the reader's taste (taste/axes.py): indicators measured per paper, a non-negative ridge line fitted to the
reader's scores, the loop that improves the indicators, and the papers far from the line. A scripted model whose
reader secretly weighs a fifth indicator ("Shell") stands in for the LLM: the loop has to find it."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.llm import LLM  # noqa: E402
from tastecal.report.axes_view import page  # noqa: E402
from tastecal.taste import axes  # noqa: E402

N, S, V, P, H = "Novelty", "Soundness", "Validity", "Practicality", "Shell"
# hidden levels (0..1); the reader's score is 0.1 + 0.8 x the average of Novelty, Soundness and Shell (Shell: the
# theory is real, not a label): every clause counts the same, so the loop must add Shell and take out the other two
LEVELS = {
    "n1": {N: 1.0, S: .6, V: .6, P: .6, H: 1.0}, "n2": {N: .8, S: .6, V: .2, P: .6, H: 1.0},
    "n3": {N: .8, S: .8, V: .8, P: .6, H: 0.0}, "n4": {N: .2, S: .6, V: .6, P: .6, H: .6},
    "n5": {N: .6, S: .2, V: .6, P: .8, H: .4}, "n6": {N: 0.0, S: .6, V: .2, P: .6, H: 0.0},
    "n7": {N: .4, S: .8, V: .8, P: .2, H: 1.0}, "n8": {N: .2, S: .2, V: .2, P: .2, H: 0.0},
    "m1": {N: 1.0, S: .8, V: .8, P: .8, H: 1.0}, "m2": {N: .6, S: .6, V: .6, P: .6, H: .6},
    "m3": {N: .2, S: .6, V: .6, P: .6, H: .4}, "m4": {N: 0.0, S: .2, V: .2, P: .2, H: 0.0},
    "t1": {N: .6, S: .6, V: .6, P: .6, H: .6},
}
TRUE = {k: round(0.1 + 0.8 * (v[N] + v[S] + v[H]) / 3, 2) for k, v in LEVELS.items()}
RATED = [{"ref": f"Paper {k} Title Words", "score": TRUE[k], "comment": f"reason for {k}"} for k in
         ("n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8")]


def node(i, title, kind="method"):
    return {"id": i, "title": title, "short": title.split()[0] + i, "kind": "paper", "date": "2022-01",
            "card": {"inherits": f"{title} starts from a problem", "move": f"{title} does a thing", "insight": f"insight {i}"},
            "gates": {"basis": "full text", "claimed": "it works", "delivery": "delivered", "delivered": "it works",
                      "reason_type": "mechanism", "reason": "because", "robustness": "single", "levers": []},
            "assessment": {"attention": {"pct": 0.5}, "contribution": {"type": kind}}}


def graph():
    nodes = [node(k, f"Paper {k} Title Words") for k in LEVELS if k.startswith("n")]
    nodes += [node(k, f"Map {k} Work") for k in ("m1", "m2", "m3", "m4")]
    nodes.append(node("t1", "Iota Open Urban Simulator", kind="tool"))
    return {"meta": {"language": "en"}, "nodes": nodes}


class Scripted(LLM):
    def __init__(self, add=(H, "1 = the theory is only a label; 5 = the theory does the work")):
        super().__init__(cache_dir=None)
        self.tasks, self.prompts, self.add = [], [], add

    def _complete(self, system, prompt, max_tokens):
        task = prompt.split("\n", 1)[0].replace("TASK:", "").strip()
        self.tasks.append(task)
        self.prompts.append((task, prompt))
        if task == "fit_indicators":
            return json.dumps({"indicators": [{"name": n, "rubric": f"0 = no {n}; 5 = full {n}", "from": "default"}
                                              for n in (N, S, V, P)] +
                              [{"name": "Appeal", "rubric": "0 = the reader dislikes it; 5 = the reader likes it", "from": "reasons"}]})
        if task == "fit_score":
            names = re.findall(r"^\d+\. ([^:]+):", prompt.split("Indicators:", 1)[1].split("Works:", 1)[0], re.M)
            sec = prompt.split("Works:", 1)[1]
            rows = []
            for wid, body in re.findall(r"^\[([^\]]+)\]\n(.*?)(?=^\[|\Z)", sec, re.M | re.S):
                m = re.search(r"insight (\w\d)", body)
                k = m.group(1) if m else wid
                lv = LEVELS.get(k, {})
                rows.append({"id": wid, "levels": {n: {"basis": f"basis {n}", "level": round(5 * lv.get(n, .6))} for n in names}})
            return json.dumps({"works": rows})
        if task == "gates_audit":
            m = re.search(r"insight (\w\d)|Title: Outside (\w\d)", prompt)
            return json.dumps({"claimed": "it works", "delivery": "delivered", "delivered": "it works",
                               "reason_type": "mechanism", "reason": "because", "robustness": "single",
                               "robustness_note": "one benchmark", "levers": [], "checks": {},
                               "eval_fit": {"kind": "method", "can_show": "partly"}})
        if task == "fit_edit":
            listed = re.findall(r"^(\d+)\. ([^:]+):", prompt, re.M)
            if self.add[0] not in [n for _, n in listed]:
                return json.dumps({"type": "add", "name": self.add[0], "rubric": self.add[1], "why": "the reasons say so"})
            off = [k for k, n in listed if n in (V, P)]         # every clause counts the same: take out what the reader ignores
            if off:
                return json.dumps({"type": "remove", "line": int(off[0]), "why": "the reasons never judge by it"})
            return json.dumps({"type": "none", "why": "nothing general left"})
        if task == "fit_types":                                     # concept works: those this script names
            return json.dumps({"concept": [w for w in getattr(self, "concept", []) if f"[{w}]" in prompt]})
        if task == "fit_fix":                                       # a stubborn model: the rewrite still fails
            return json.dumps({"text": "0 = the reader dislikes it; 5 = the reader likes it"})
        raise AssertionError(task)


class LineTest(unittest.TestCase):
    def test_fit_line(self):
        X = [[0, 1], [1, 0], [1, 1], [0, 0]]
        w, b = axes.fit_line(X, [0.5, 0.2, 0.7, 0.0], 0.001)
        self.assertAlmostEqual(w[0], 0.2, places=2)
        self.assertAlmostEqual(w[1], 0.5, places=2)
        w, _ = axes.fit_line([[0], [1], [2]], [1.0, 0.5, 0.0], 0.001)
        self.assertEqual(w, [0.0])                                     # weights never go negative

    def test_order_errors(self):
        self.assertEqual(axes.order_errors([0.7, 0.3, 0.95], [0.4, 0.6, 0.85]), [(0, 1)])
        self.assertEqual(axes.order_errors([0.7, 0.6], [0.4, 0.6]), [])   # less than 0.3 apart: no constraint

    def test_names_and_notes(self):
        self.assertEqual([r["ref"] for r in axes.parse_rated("1. Alpha | 0.9 | x\nGamma｜0.3\nnot a line")], ["Alpha", "Gamma"])
        n = node("x", "Kappa Planner Net")
        n["card"]["move"] = "Kappa Planner Net 把规划写成扩散"
        text = axes.notes(n)
        self.assertNotIn("Kappa", text)
        self.assertIn("这项工作 把规划写成扩散", text)
        self.assertEqual(axes.work_type(node("y", "Some Simulator", kind="tool")), "tool")


class LoopTest(unittest.TestCase):
    def rated(self):
        rows, skipped = axes.rated_works(graph(), RATED)
        self.assertEqual((len(rows), skipped), (8, []))
        return rows

    def test_the_hidden_indicator_is_found(self):
        llm = Scripted()
        rows = self.rated()
        start = [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)]
        res = axes.calibrate(llm, rows, start)
        self.assertTrue(res["history"][0]["accepted"])
        self.assertIn(H, [d["name"] for d in res["indicators"]])
        self.assertLess(res["eval"]["mae"], res["history"][0]["mae_before"])
        self.assertEqual(res["eval"]["order"], [])

    def test_clauses_must_be_about_the_paper(self):
        self.assertIn("likes", axes.clause_problem("5 = the reader likes it", []))
        self.assertIn("likes", axes.clause_problem("5 = 读者喜欢", []))
        self.assertIn("PaperX", axes.clause_problem("0 = as weak as PaperX", ["PaperX"]))
        self.assertEqual(axes.clause_problem("0 = only open-loop averages; 5 = reactive closed loop", ["PaperX"]), "")
        llm = Scripted(add=("Appeal", "5 = the reader likes it"))
        start = [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)]
        res = axes.calibrate(llm, self.rated(), start)
        self.assertNotIn("Appeal", [d["name"] for d in res["indicators"]])
        self.assertIn("not allowed", res["history"][0]["note"])

    def test_no_more_indicators_than_papers_allow(self):
        rows = self.rated()[:5]                                         # 5 papers: at most max(4, 5 - 2) = 4
        start = [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)]
        res = axes.calibrate(Scripted(), rows, start)
        self.assertEqual(len(res["indicators"]), 4)

    def test_a_useless_indicator_is_not_kept(self):
        llm = Scripted(add=("Length", "1 = short; 5 = long"))           # every paper measures 3: it explains nothing
        start = [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)]
        res = axes.calibrate(llm, self.rated(), start)
        self.assertFalse(any(h["accepted"] for h in res["history"]))
        self.assertNotIn("Length", [d["name"] for d in res["indicators"]])


class Misreader(Scripted):
    """Reads Novelty as 0.6 on every paper until the indicator carries a reading note; proposes that note."""
    def __init__(self, note="compare the method, step by step, with the closest earlier method it builds on"):
        super().__init__()
        self.note = note

    def _complete(self, system, prompt, max_tokens):
        task = prompt.split("\n", 1)[0].replace("TASK:", "").strip()
        if task == "fit_edit":
            self.tasks.append(task)
            return json.dumps({"type": "misread", "name": N, "check": self.note, "why": "novelty is read wrongly"})
        out = super()._complete(system, prompt, max_tokens)
        if task == "fit_score" and "How to read it" not in prompt:
            d = json.loads(out)
            for w in d["works"]:
                if N in w["levels"]:
                    w["levels"][N]["level"] = 3
            out = json.dumps(d)
        return out


class ReadingNoteTest(unittest.TestCase):
    start = [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)]

    def test_a_reading_note_applies_to_every_paper(self):
        llm, rows = Misreader(), axes.rated_works(graph(), RATED)[0]
        res = axes.calibrate(llm, rows, [dict(d) for d in self.start], max_rounds=1)
        self.assertTrue(res["history"][0]["accepted"])
        nov = next(d for d in res["indicators"] if d["name"] == N)
        self.assertEqual(nov["how"], [llm.note])
        noted = [p for t, p in llm.prompts if t == "fit_score" and "How to read it" in p]
        self.assertEqual(set(re.findall(r"^\[(R\d+)\]", "".join(noted), re.M)), {r["key"] for r in rows})
        self.assertEqual({r["x"][N] for r in rows}, {LEVELS[k][N] for k in ("n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8")})

    def test_a_long_reading_note_ends_at_a_whole_sentence(self):
        long = ("Write down the operations the method performs. " * 14) + "If they match a known technique"
        llm, rows = Misreader(note=long), axes.rated_works(graph(), RATED)[0]
        res = axes.calibrate(llm, rows, [dict(d) for d in self.start], max_rounds=1)
        how = next(d for d in res["indicators"] if d["name"] == N)["how"][0]
        self.assertLessEqual(len(how), axes.NOTE_CAP)
        self.assertTrue(how.endswith("performs."))                       # never "... If"
        self.assertEqual(axes.whole_note("短读法。"), "短读法。")
        self.assertTrue(axes.whole_note("第一句话。" + "第二句很长" * 200).endswith("。"))

    def test_a_reading_note_may_not_name_a_paper(self):
        llm, rows = Misreader(note="read it as Paper n1 does"), axes.rated_works(graph(), RATED)[0]
        res = axes.calibrate(llm, rows, [dict(d) for d in self.start], max_rounds=1, names_banned=["Paper n1"])
        self.assertIn("not allowed", res["history"][0]["note"])        # refused, and the rewrite failed too
        self.assertIn("fit_fix", llm.tasks)
        self.assertNotIn("how", next(d for d in res["indicators"] if d["name"] == N))


def xlsx(path, rows):
    """A minimal spreadsheet: shared strings for text, plain numbers for scores (no extra packages needed)."""
    import zipfile
    strings, sheet = [], []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in zip("ABC", row):
            if isinstance(v, str):
                strings.append(v)
                cells.append(f'<c r="{c}{r}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                cells.append(f'<c r="{c}{r}"><v>{v}</v></c>')
        sheet.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{t}</t></si>" for t in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(sheet)}</sheetData></worksheet>')


class TableTest(unittest.TestCase):
    def test_spreadsheet_ratings(self):
        p = os.path.join(tempfile.mkdtemp(), "Book1.xlsx")
        xlsx(p, [("文章", "分数", "原因"), ("Paper Alpha", 0.9, "思路清楚，被广泛复用"), ("Paper Beta", 0.2, "包装多于内容"),
                 ("no score row", "", "")])
        self.assertEqual(axes.read_table(p), [{"ref": "Paper Alpha", "score": 0.9, "comment": "思路清楚，被广泛复用"},
                                              {"ref": "Paper Beta", "score": 0.2, "comment": "包装多于内容"}])

    def test_rated_papers_outside_the_run_are_read(self):
        from tastecal.core.config import Config
        from tastecal.core.model import Item
        from tastecal.judge.gates import Gatekeeper

        class Src:
            def resolve(self, ref):
                if "missing" in ref:
                    raise LookupError("no such paper")
                return Item(id="s2:" + ref, title=ref, year=2021, date="2021-01", url="https://arxiv.org/abs/2101.00001")
        saved = Gatekeeper.fulltext
        Gatekeeper.fulltext = lambda self, node, item=None: ("full text of the paper " * 400, "full text", "arXiv HTML")
        try:
            rated = [{"ref": "Outside Work One", "score": 0.7, "comment": "x"}, {"ref": "A missing paper", "score": 0.2, "comment": ""}]
            done, missing = axes.read_rated(rated, Config(), Scripted(), None, Src(), graph())
        finally:
            Gatekeeper.fulltext = saved
        self.assertEqual([n["title"] for n in done], ["Outside Work One"])
        self.assertEqual(done[0]["gates"]["basis"], "full text")
        self.assertEqual(missing[0]["why"][:9], "not found")
        rows, _ = axes.rated_works(graph(), rated, done)
        self.assertEqual([r["ref"] for r in rows], ["Outside Work One"])

    def test_same_paper_rated_twice_keeps_the_later_rating(self):
        g = graph()
        node = next(n for n in g["nodes"] if axes.readable(n) and axes.is_method(n))
        rated = [{"ref": node["short"] or node["title"], "score": 0.3, "comment": "profile"},
                 {"ref": node["title"], "score": 0.1, "comment": "sheet"}]
        rows, _ = axes.rated_works(g, rated)
        self.assertEqual([(r["node"], r["yours"]) for r in rows], [(node["id"], 0.1)])

    def test_rated_benchmark_outside_the_run_is_listed_not_read(self):
        from tastecal.core.config import Config
        from tastecal.core.model import Item

        class Src:
            def resolve(self, ref):
                return Item(id="s2:x", title=ref, year=2021, date="2021-01")
        llm = Scripted()
        rated = [{"ref": "A Robustness Benchmark for Imaginary Forecasting", "score": 0.5, "comment": "x"}]
        done, missing = axes.read_rated(rated, Config(), llm, None, Src(), graph())
        self.assertEqual((len(done), missing, llm.tasks), (1, [], []))
        rows, other = axes.rated_works(graph(), rated, done)
        self.assertEqual((rows, other[0]["why"], other[0]["type"]), ([], "not a method paper", "benchmark"))
        from tastecal.report.axes_view import page
        html = page({"indicators": [], "weights": [], "b": 0, "a": 1, "mae": 0, "order_errors": 0, "noise": 0, "far": 0.15,
                     "rated": [], "map": [], "history": [], "others": [],
                     "skipped": [{"ref": "Soft sheets", "yours": 0.8, "why": "no full-text reading of it in this run"}],
                     "unread": [{"ref": "Soft sheets", "why": "no full text", "file": "soft-sheets.pdf"}]}, "zh")
        self.assertIn("soft-sheets.pdf", html)
        self.assertIn("找不到全文", html)


class CornerTest(unittest.TestCase):
    def rows(self):
        # (id, predicted on your scale, attention percentile, date); h is under a year old
        spec = [("a", .90, .05, "2022-01"), ("b", .60, .40, "2022-01"), ("c", .70, .70, "2022-01"), ("d", .20, .95, "2022-01"),
                ("e", .25, .90, "2022-01"), ("f", .50, .50, "2022-01"), ("g", .55, .55, "2022-01"), ("h", .95, .02, "2026-06"),
                ("i", .85, .03, "2022-01"), ("j", .40, .60, "2022-01")]
        return [{"id": i, "pred": p, "attention": a, "date": d, "unsure": 0.04} for i, p, a, d in spec]

    def test_off_the_diagonal_by_rank(self):
        cn = axes.corners(self.rows(), "2026-10-19")
        self.assertEqual(cn["new"], ["h"])                          # under a year old: drawn, never off the line
        self.assertEqual(set(cn["gem"]), {"a", "i"})                # below y = x: high on your line, little cited
        self.assertEqual(set(cn["hyped"]), {"d", "e"})              # above it: much cited, low on your line
        self.assertEqual(cn["hyped"][0], "d")                       # sorted by distance from the line
        self.assertEqual(cn["pos"]["f"]["x"], 0.35)                 # ranks among these papers, 0 to 1
        self.assertEqual(cn["pos"]["d"]["y"], 0.95)

    def test_an_uncertain_paper_stays_on_the_line(self):
        rows = self.rows()
        rows[8]["unsure"] = 0.6                                     # the near end of its bar is within the band
        self.assertNotIn("i", axes.corners(rows, "2026-10-19")["gem"])

    def test_untrusted_counts_stay_on_the_line(self):
        rows = self.rows()
        rows[0]["att"] = {"lower_bound": True}
        self.assertNotIn("a", axes.corners(rows, "2026-10-19")["gem"])


RE = "Reuse"
# the field cites what can be reused; the reader's scores do not depend on it (every rated paper reads 0.6 on it)
FIELD_IDS = [f"{c}{d}" for c in "ab" for d in range(1, 8)]
FIELD_LEVELS = {i: {N: (k % 5) / 4, S: .6, V: .6, P: .6, H: ((k * 3) % 5) / 4, RE: ((k * 2) % 7) / 6}
                for k, i in enumerate(FIELD_IDS)}


class FieldScripted(Scripted):
    """The reader's hidden Shell is found in the first loop; the field's Reuse is proposed in the field loop."""
    def _complete(self, system, prompt, max_tokens):
        task = prompt.split("\n", 1)[0].replace("TASK:", "").strip()
        if task == "fit_field_edit":
            self.tasks.append(task)
            self.prompts.append((task, prompt))
            return json.dumps({"type": "add", "name": RE, "rubric": "0 = nothing others can run; 5 = a released setup others can run unchanged",
                               "why": "the field cites what it can run"})
        if task == "fit_score":
            names = re.findall(r"^\d+\. ([^:]+):", prompt.split("Indicators:", 1)[1].split("Works:", 1)[0], re.M)
            sec = prompt.split("Works:", 1)[1]
            rows = []
            for wid, body in re.findall(r"^\[([^\]]+)\]\n(.*?)(?=^\[|\Z)", sec, re.M | re.S):
                m = re.search(r"insight (\w\d)", body)
                k = m.group(1) if m else wid
                lv = FIELD_LEVELS.get(k) or LEVELS.get(k, {})
                rows.append({"id": wid, "levels": {n: {"basis": f"basis {n}", "level": round(5 * lv.get(n, .6))} for n in names}})
            self.tasks.append(task)
            self.prompts.append((task, prompt))
            return json.dumps({"works": rows})
        return super()._complete(system, prompt, max_tokens)


def field_graph():
    g = graph()
    for k, i in enumerate(FIELD_IDS):
        n = node(i, f"Field {i} Work")
        n["assessment"]["attention"] = {"pct": round(0.05 + 0.9 * FIELD_LEVELS[i][RE], 3)}
        n["date"] = "2021-06"
        n["citations"] = round(10 ** (0.5 + 2.5 * FIELD_LEVELS[i][RE]) * 64 / 12)    # the field cites what it can reuse
        g["nodes"].append(n)
    g["meta"]["generated_at"] = "2026-10-19 09:00"
    return g


class FieldTest(unittest.TestCase):
    def test_a_paper_with_nothing_to_change_gives_way(self):
        class Stuck(FieldScripted):
            def _complete(self, system, prompt, max_tokens):
                if prompt.startswith("TASK: fit_field_edit"):
                    self.tasks.append("fit_field_edit")
                    return json.dumps({"type": "none", "why": "timing"})
                return super()._complete(system, prompt, max_tokens)
        res = axes.run(Stuck(), field_graph(), RATED)
        targets = [h["target"] for h in res["field"]["history"]]
        self.assertGreater(len(targets), 2)                             # it went on past two "none"s
        self.assertEqual(len(targets), len(set(targets)))               # never the same paper twice after a "none"

    def test_the_field_brings_in_what_it_attends_to(self):
        llm = FieldScripted()
        res = axes.run(llm, field_graph(), RATED)
        fld = res["field"]
        self.assertNotIn("skipped", fld)
        reuse = next((d for d in res["indicators"] if d["name"] == RE), None)
        self.assertIsNotNone(reuse)                                     # kept: it brings the checking half closer
        self.assertEqual(reuse["from"], "field")                        # and it is marked as the field's
        self.assertLess(fld["end"]["err_B"], fld["start"]["err_B"])
        self.assertGreater(fld["share"], 0)
        self.assertEqual(fld["field_names"], [RE])
        self.assertLess(fld["final"]["dist"], fld["equal"]["dist"])     # every paper closer to y = x than step 1 left it
        for r in res["rated"]:                                          # while your scores still hold
            self.assertLessEqual(abs(r["pred"] - r["yours"]), r["allowed"] + 1e-6)
            self.assertGreaterEqual(r["allowed"], axes.FIT_TOL)
        self.assertEqual(res["order_errors"], 0)
        self.assertEqual(sum(1 for h in fld["history"] if h.get("change", "").startswith("add " + RE)), 1)   # never tried twice
        self.assertTrue(all(RE in r["x1"] and RE in r["x2"] for r in res["rated"]))   # read twice, as in step 1
        self.assertIn("Every paper towards y = x", page(res, "en"))
        for task, prompt in llm.prompts:
            if task in ("fit_score", "fit_field_edit"):
                self.assertNotIn("reason for", prompt)                  # neither measuring nor the field sees your reasons
        html = page(res, "en")
        self.assertIn("from the field", html)

    def test_reception_is_never_a_clause(self):
        self.assertIn("received", axes.clause_problem("5 = widely adopted by later work", []))
        self.assertIn("received", axes.clause_problem("5 = 被后续工作沿用", []))
        self.assertIn("received", axes.clause_problem("4 = highly cited", []))
        self.assertEqual(axes.clause_problem("5 = a released setup others can run unchanged", []), "")
        self.assertNotIn("later papers use it", axes.notes(dict(node("z1", "Zeta Work"), assessment={"evidence": {"uptake_counts": {"extends": 3}}})))


class Fixer(Scripted):
    """Rewrites a refused clause properly."""
    def _complete(self, system, prompt, max_tokens):
        task = prompt.split("\n", 1)[0].replace("TASK:", "").strip()
        if task == "fit_fix":
            self.tasks.append(task)
            return json.dumps({"text": "0 = nothing others can run; 5 = a released setup others can run unchanged"})
        return super()._complete(system, prompt, max_tokens)


class RuleTest(unittest.TestCase):
    def test_reuse_is_not_reception(self):
        self.assertEqual(axes.clause_problem("5 = 给出别人能直接沿用的问题设定", []), "")
        self.assertEqual(axes.clause_problem("3 = the authors report runtime", []), "")
        self.assertIn("received", axes.clause_problem("5 = 被大量后续工作沿用", []))

    def test_a_refused_clause_is_rewritten_once(self):
        llm = Fixer(add=("Appeal", "0 = the reader dislikes it; 5 = the reader likes it"))
        start = [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)]
        rows = axes.rated_works(graph(), RATED)[0]
        axes.calibrate(llm, rows, start, max_rounds=1)
        self.assertIn("fit_fix", llm.tasks)
        inds = axes.start_indicators(llm, rows, "en")
        appeal = next(d for d in inds if d["name"] == "Appeal")
        self.assertIn("released setup", appeal["rubric"])           # kept, as rewritten

    def test_the_line_does_not_go_flat(self):
        # levels that barely spread (0.4 to 0.6) still give a slope: the ridge is relative to their spread
        X = [[0.4], [0.5], [0.6], [0.4], [0.6], [0.5]]
        y = [0.2, 0.5, 0.8, 0.25, 0.75, 0.5]
        w, b = axes.fit_line(X, y, axes.LAMBDAS[-1])
        self.assertGreater(w[0], 1.0)

    def test_your_papers_are_measured_side_by_side(self):
        llm = Scripted()
        rows = axes.rated_works(graph(), RATED)[0]
        axes.calibrate(llm, rows, [{"name": n, "rubric": "r", "from": "default"} for n in (N, S, V, P)], max_rounds=0)
        first = [p for t, p in llm.prompts if t == "fit_score"]
        self.assertEqual(len(first), 8)                             # one call per indicator, in both orders
        self.assertTrue(all(p.count("insight n") == 8 for p in first))   # every rated paper in each


class AttentionTest(unittest.TestCase):
    def test_measures_and_reliability(self):
        from tastecal.taste import attention as A
        n = {"date": "2026-05", "assessment": {"attention": {"pct": 0.4}}}
        raw = {"pct": 0.9, "cited_by": 2, "by_year": {"2026": 2}, "influential": 1}
        m = A.measures(n, raw, "2026-10-19")
        self.assertEqual((m["cumulative"], m["months"], m["citations"]), (0.9, 5, 2))
        self.assertIn("OpenAlex", m["source"])
        self.assertLess(m["rel"], 0.3)                                  # five months, two citations: little to go on
        old = A.measures({"date": "2019-01"}, {"pct": 0.5, "cited_by": 300, "by_year": {"2026": 40, "2025": 50}}, "2026-10-19")
        self.assertEqual(old["rel"], 1.0)
        self.assertAlmostEqual(old["recent"], 90 / 22, places=3)        # the last two calendar years, per month
        fallback = A.measures({"date": "2022-01", "assessment": {"attention": {"pct": 0.4}}}, None, "2026-10-19")
        self.assertEqual((fallback["cumulative"], fallback["source"]), (0.4, "neighbourhood of this run"))

    def test_on_your_scale_by_rank(self):
        from tastecal.taste import attention as A
        rows = [{"id": i, "m": {"cumulative": v, "rel": 1.0}} for i, v in (("a", .1), ("b", .5), ("c", .9))]
        pos = A.on_scale(rows, "cumulative", {"a": .8, "b": .4, "c": .6})
        self.assertEqual([pos[i]["x"] for i in "abc"], [0.467, 0.6, 0.733])   # the scores' own distribution, by rank
        rows[0]["m"]["rel"] = 0.2
        wide = A.on_scale(rows, "cumulative", {"a": .8, "b": .4, "c": .6})["a"]
        self.assertLess(wide["lo"], wide["x"])                          # an unreliable paper gets a bar

    def test_off_the_line(self):
        rows = [{"id": i, "m": {"cumulative": v, "rel": 1.0}} for i, v in (("a", .1), ("b", .3), ("c", .5), ("d", .7), ("e", .9))]
        preds = {"a": .9, "b": .5, "c": .55, "d": .6, "e": .2}
        vw = axes.views(rows, preds, {}, 0.15)["cumulative"]
        self.assertEqual((vw["gem"], vw["hyped"]), (["a"], ["e"]))

    def test_fetch_tolerates_a_failing_source(self):
        from tastecal.taste import attention as A

        class OA:
            def find(self, item):
                return "W1"

            def attention(self, wid):
                return {"pct": 0.7, "cited_by": 10, "by_year": {}, "pub": "2024-01-01"}

        class S2:
            def counts(self, pid):
                raise RuntimeError("rate limited")
        got = A.fetch([{"id": "x", "title": "T", "ids": {"s2": "abc"}}], OA(), S2())
        self.assertEqual(got["x"]["pct"], 0.7)


class RatingsFileTest(unittest.TestCase):
    def test_json_and_yaml_ratings(self):
        d = tempfile.mkdtemp()
        rows = [{"paper": "Paper Alpha", "score": 0.9, "reason": "思路清楚"},
                {"title": "Paper Beta", "score": "0.2", "comment": "包装多于内容"}, {"paper": "no score"}]
        for name, data in (("ratings.json", rows), ("wrapped.json", {"papers": rows})):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            self.assertEqual(axes.read_table(p), [{"ref": "Paper Alpha", "score": 0.9, "comment": "思路清楚"},
                                                  {"ref": "Paper Beta", "score": 0.2, "comment": "包装多于内容"}])
        try:
            import yaml  # noqa: F401
        except ImportError:
            return
        p = os.path.join(d, "ratings.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write("- paper: Paper Alpha\n  score: 0.9\n  reason: 思路清楚\n")
        self.assertEqual(axes.read_table(p), [{"ref": "Paper Alpha", "score": 0.9, "comment": "思路清楚"}])


class ScaleTest(unittest.TestCase):
    def test_the_maps_own_count_is_used(self):
        from tastecal.taste import attention as A
        node = {"date": "2018-10", "citations": None, "assessment": {"attention": {"citations": 179, "pct": 0.48}}}
        m = A.measures(node, {}, "2026-10-20")                        # nothing looked up: the count the audit recorded
        self.assertEqual(m["citations"], 179)
        self.assertAlmostEqual(m["rate"], 179 / (96 / 12), places=2)
        self.assertEqual(A.measures(node, {"cited_by": 300}, "2026-10-20")["citations"], 300)   # a fresh count wins

    def test_openalex_finds_the_paper_not_a_famous_one(self):
        from tastecal.core.model import Item
        from tastecal.sources.openalex import OpenAlex

        class Http:
            def get_json(self, url, params=None, **kw):
                self.params = params
                return {"results": [{"id": "https://openalex.org/W1", "display_name": "Welcome to the Tidyverse", "cited_by_count": 90000},
                                    {"id": "https://openalex.org/W2", "display_name": "Learning to Drive in a Day", "cited_by_count": 300},
                                    {"id": "https://openalex.org/W3", "display_name": "Learning to drive in a day.", "cited_by_count": 900}]}
        http = Http()
        self.assertEqual(OpenAlex(http).find(Item(id="x", title="Learning to Drive in a Day")), "W3")   # the most cited version
        self.assertNotIn("sort", http.params)                         # ranked by relevance, not by citations

    def test_one_source_of_attention_per_ranking(self):
        from tastecal.taste import attention as A
        ms = [{"rate": 500.0, "pct_run": 0.5}, {"rate": None, "pct_run": 0.1}, {"rate": 80.0, "pct_run": 0.7}]
        A.unify(ms)                                                   # too few have a count: the run's percentile for all
        self.assertEqual([m["cumulative"] for m in ms], [0.5, 0.1, 0.7])
        self.assertEqual(ms[0]["scale"], "rank")
        ms = [dict(m) for m in [{"rate": 90.0, "pct_run": 0.5}] * 4 + [{"rate": None, "pct_run": 0.1}]]
        rated = [{"rate": 20000.0, "pct_run": None}]
        A.unify(ms, rated)                                            # enough: counts, the paper without one left out
        self.assertEqual([m["cumulative"] for m in ms], [90.0] * 4 + [None])
        self.assertEqual((rated[0]["cumulative"], rated[0]["scale"]), (20000.0, "log"))

    def test_the_typical_paper_sits_in_the_middle(self):
        import math
        from tastecal.taste import attention as A
        rows = [{"id": i, "m": {"cumulative": v, "scale": "log", "rel": 1.0}}
                for i, v in (("a", 0.0), ("b", 3.0), ("c", 10.0), ("d", 30.0), ("e", 1000.0))]
        pos = A.position(rows, "cumulative", {r["id"]: .5 for r in rows}, anchors=[20000.0], top=19000.0)
        self.assertAlmostEqual(pos["c"]["x"], 0.5, places=3)          # the median of these papers: the middle
        sc = A.scale(rows, "cumulative", top=19000.0)
        q = A.quantile(sorted(math.log1p(v) for v in (0, 3, 10, 30, 1000)), 0.25)
        self.assertAlmostEqual(sc["low"], (math.log1p(10) - q) / 0.6745, places=6)   # below: these papers' own spread
        self.assertAlmostEqual(A.place(19000.0, sc), 0.5 * (1 + math.erf(3 / math.sqrt(2))), places=6)   # the landmark: +3 sigma
        self.assertGreater(pos["a"]["x"], 0.05)                       # no citation is not pressed against 0
        self.assertLess(pos["a"]["x"], pos["b"]["x"])
        self.assertLess(pos["d"]["x"], pos["e"]["x"])
        self.assertLess(pos["e"]["x"], 0.999)                         # nothing of the field reaches the landmark
        sc2 = A.scale(rows, "cumulative", anchors=[20000.0])          # no landmark looked up: the most cited known
        self.assertEqual(sc2["top"], 20000.0)

    def test_every_count_comes_in_the_same_order(self):
        from tastecal.taste import attention as A
        node = {"date": "2020-01", "citations": 50}
        self.assertEqual(A.measures(node, {"s2_cites": 80}, "2026-01-01")["citations"], 80)        # looked up beats recorded
        self.assertEqual(A.measures(node, {"cited_by": 90, "s2_cites": 80}, "2026-01-01")["citations"], 90)

    def test_the_line_never_stretches_more_than_twice(self):
        X = [[0.40], [0.45], [0.50], [0.55], [0.60]]                  # average levels bunched together
        w, b = axes.fit_scale(X, [0.1, 0.3, 0.5, 0.7, 0.95])
        self.assertLessEqual(w[0], axes.MAX_SLOPE)


class SourceLimitTest(unittest.TestCase):
    """OpenAlex answers HTTP 429 once its daily allowance is spent: a few retries, then it is not asked again in the
    run; its API key goes with every request but never into the cache, the log or an error."""
    def test_a_spent_allowance_stops_the_asking(self):
        import io
        import logging as lg
        import urllib.error
        from tastecal.core import http as H
        sent = []

        def fake(req, timeout=None):
            sent.append(req.full_url)
            if "api.openalex.org" in req.full_url and "cached" not in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {},
                                             io.BytesIO(("budget used up for " + req.full_url).encode()))
            return io.BytesIO(b'{"ok": 1}')
        saved = H.urllib.request.urlopen
        H.urllib.request.urlopen = fake
        d = tempfile.mkdtemp()
        logs = []

        class Catch(lg.Handler):
            def emit(self, record):
                logs.append(record.getMessage())
        catch = Catch()
        lg.getLogger("tastecal").addHandler(catch)
        try:
            http = H.Http(d)
            http.sleeper = lambda s: None
            http.daily_limited("api.openalex.org", retries=2, secret={"api_key": "SEKRET123"})
            self.assertEqual(http.get_json("https://api.openalex.org/works", params={"search": "cached"}), {"ok": 1})
            with self.assertRaises(H.HttpError) as err:
                http.get_json("https://api.openalex.org/works", params={"search": "x"})
            self.assertEqual(sum(1 for u in sent if "search=x" in u), 1)          # a spent allowance: no waiting, no retry
            self.assertIn("api.openalex.org", http.off)
            n = len(sent)
            with self.assertRaises(H.HttpError):
                http.get_json("https://api.openalex.org/works", params={"search": "y"})
            self.assertEqual(len(sent), n)                                        # not asked again
            self.assertEqual(http.get_json("https://api.openalex.org/works", params={"search": "cached"}), {"ok": 1})
            self.assertEqual(http.get_json("https://api.example.org/x"), {"ok": 1})   # other sources go on
            self.assertTrue(all("api_key=SEKRET123" in u for u in sent if "openalex" in u))   # sent with every request
            self.assertNotIn("SEKRET123", str(err.exception))
            self.assertFalse(any("SEKRET123" in m for m in logs))
            for root, _, files in os.walk(d):
                for f in files:
                    with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                        self.assertNotIn("SEKRET123", fh.read())
        finally:
            H.urllib.request.urlopen = saved
            lg.getLogger("tastecal").removeHandler(catch)


class RefitTest(unittest.TestCase):
    """--refit: step 2's numbers again from a fit's own result, without a model call."""
    def graph(self):
        g = field_graph()
        for n in g["nodes"]:
            n["venue"], n["authors"] = "ICRA 2021", "Doe et al."
        return g

    def test_refit_gives_back_what_the_run_gave(self):
        g = self.graph()
        res = axes.run(FieldScripted(), g, RATED, anchor={"cited_by": 200000, "by_year": {}, "pub": "2017-06-12"})
        again = axes.refit(json.loads(json.dumps(res)), g)          # as read back from taste_fit.json
        before = {r["id"]: r["pred"] for r in res["map"]}
        after = {r["id"]: r["pred"] for r in again["map"]}
        self.assertEqual(set(before), set(after))
        self.assertLess(max(abs(before[i] - after[i]) for i in before), 0.002)
        for w1, w2 in zip(res["weights"], again["weights"]):
            self.assertAlmostEqual(w1["share"], w2["share"], delta=0.01)
        self.assertEqual([r["recheck"] for r in res["map"] if r.get("recheck")],
                         [r["recheck"] for r in again["map"] if r.get("recheck")])   # the re-checks are kept
        self.assertEqual(again["history"], res["history"])
        self.assertIn("refit", again)
        self.assertIn("--refit", page(again, "en"))

    def test_refit_follows_a_new_scale_and_keeps_your_scores(self):
        g = self.graph()
        res = axes.run(FieldScripted(), g, RATED)
        from tastecal.taste import attention as A
        saved = A.scale

        def wider(rows, metric, anchors=(), top=None):               # any change of scale goes through refit
            sc = saved(rows, metric, anchors, top)
            if sc:
                sc["low"] *= 2
            return sc
        A.scale = wider
        try:
            again = axes.refit(json.loads(json.dumps(res)), g)
        finally:
            A.scale = saved
        self.assertNotEqual([r["pred"] for r in again["map"]], [r["pred"] for r in res["map"]])
        for r in again["rated"]:
            self.assertLessEqual(abs(r["pred"] - r["yours"]), r["allowed"] + 1e-6)

    def test_a_result_from_before_the_counts_is_refitted_on_them(self):
        g = self.graph()
        res = json.loads(json.dumps(axes.run(FieldScripted(), g, RATED)))
        for r in res["map"]:                                         # as results stored them before 2026-10-20
            m = r["m"]
            r["m"] = {"cumulative": 0.5, "recent": m.get("recent"), "influential": None, "stars": None,
                      "source": "field and year (OpenAlex)", "months": m["months"], "citations": m["citations"], "rel": m["rel"]}
        for k in ("attention_scale", "attention_source", "attention_anchor"):
            res.pop(k, None)
        again = axes.refit(res, g, anchor={"cited_by": 200000, "by_year": {}, "pub": "2017-06-12"})
        self.assertEqual(again["attention_source"], "citations a year")
        self.assertEqual(again["attention_scale"]["cumulative"]["top_title"], "Attention Is All You Need")
        r = next(r for r in again["map"] if r["m"].get("citations"))
        self.assertAlmostEqual(r["m"]["rate"], r["m"]["citations"] / (r["m"]["months"] / 12), places=2)

    def test_a_paper_under_a_year_is_never_listed_off_the_line(self):
        cands = [{"id": f"p{i}", "m": {"cumulative": float(v), "scale": "log", "rel": 1.0, "months": mo}}
                 for i, (v, mo) in enumerate([(0, 3), (0, 30), (5, 40), (10, 40), (20, 40), (50, 40), (100, 40)])]
        preds = {c["id"]: 0.95 if c["id"] in ("p0", "p1") else 0.5 for c in cands}
        vw = axes.views(cands, preds, {c["id"]: 0.0 for c in cands}, 0.15)["cumulative"]
        self.assertIn("p1", vw["gem"])                               # old enough: listed
        self.assertNotIn("p0", vw["gem"])                            # three months old: drawn, not listed
        self.assertIn("p0", vw["young"])

    def test_venue_and_authors_on_the_card(self):
        res = axes.run(FieldScripted(), self.graph(), RATED)
        self.assertTrue(all(r.get("venue") == "ICRA 2021" for r in res["map"]))
        html = page(res, "zh")
        self.assertIn("ICRA 2021 · Doe et al.", html)
        self.assertIn("每年", html)                                  # a count is shown as citations a year
        self.assertNotRegex(html, r"关注度分位 [1-9][0-9]{3,}%")      # never as a percentile in the thousands

    def test_cli_refit(self):
        from tastecal import cli
        d = tempfile.mkdtemp()
        g = self.graph()
        res = axes.run(FieldScripted(), g, RATED)
        gp = os.path.join(d, "graph.json")
        with open(gp, "w", encoding="utf-8") as f:
            json.dump(g, f)
        with open(os.path.join(d, "taste_fit.json"), "w", encoding="utf-8") as f:
            json.dump(res, f)
        self.assertEqual(cli.main(["fit", gp, "--refit", "--no-attention"]), 0)   # no lookup in a test
        with open(os.path.join(d, "taste_fit.json"), encoding="utf-8") as f:
            self.assertIn("refit", json.load(f))
        self.assertTrue(os.path.exists(os.path.join(d, "taste_fit.html")))


class CarryOverTest(unittest.TestCase):
    def test_the_next_fit_starts_where_the_last_one_ended(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "taste_clauses.json")
        first = axes.run(Scripted(), graph(), RATED)
        axes.save_clauses(path, "en", first, "runs/a/graph.json")
        axes.save_clauses(path, "zh-CN", {"indicators": [{"name": "创新性", "rubric": "0 = 无；5 = 有"}]})
        start = axes.saved_clauses(path, "en")
        self.assertEqual([x["name"] for x in start["indicators"]], [x["name"] for x in first["indicators"]])
        self.assertEqual(axes.saved_clauses(path, "zh")["indicators"][0]["name"], "创新性")   # kept apart by language
        llm = Scripted()
        second = axes.run(llm, graph(), RATED, start=start)
        self.assertNotIn("fit_indicators", llm.tasks)                  # not written again from the general clauses
        self.assertEqual(second["started_from"], start["saved"])
        self.assertIsNone(axes.saved_clauses(os.path.join(d, "none.json"), "en"))

    def test_notes_an_older_fit_cut_mid_sentence_are_mended(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "taste_clauses.json")
        cut = ("Judge novelty by what the procedure computes. " * 14)[:axes.NOTE_CAP - 2] + " If"
        kept = "Look at the operations."
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"en": {"indicators": [{"name": N, "rubric": "r", "how": [cut, kept]}], "saved": "2026-10-20"}}, f)
        how = axes.saved_clauses(path, "en")["indicators"][0]["how"]
        self.assertTrue(how[0].endswith("computes."))
        self.assertEqual(how[1], kept)


class ConfidenceTest(unittest.TestCase):
    def test_how_far_to_trust_the_chart(self):
        c = axes.confidence([0.3, 0.4, 0.0, 0.0], 1)                    # numbers, never a verdict
        self.assertEqual((c["rms"], c["worst"], c["n"], c["beyond"], c["order"]), (0.25, 0.4, 4, 2, 1))
        self.assertNotIn("level", c)

    def test_a_poor_fit_widens_every_bar(self):
        res = axes.run(Scripted(), graph(), RATED)
        rms = res["confidence"]["rms"]
        self.assertTrue(all(r["unsure"] / 2 >= rms - 1e-3 for r in res["map"]))
        html = page(res, "zh")
        self.assertIn(f"±{rms:.2f}", html)
        self.assertNotIn("不太准", html)


class SampleTest(unittest.TestCase):
    def test_only_papers_on_the_maps_problem_are_kept(self):
        from tastecal.core.model import Item

        class Pick(Scripted):
            def _complete(self, system, prompt, max_tokens):
                if prompt.startswith("TASK: fit_topic"):
                    self.tasks.append("fit_topic")
                    rows = re.findall(r"^\[(d\d+)\]\n(.*)$", prompt, re.M)
                    return json.dumps({"keep": [k for k, t in rows if "scenario" in t]})
                return super()._complete(system, prompt, max_tokens)
        items = [Item(id="s2:a", title="Safety-critical scenario search", abstract="x"),
                 Item(id="s2:b", title="A lidar detector", abstract="y")]
        llm = Pick()
        self.assertEqual([it.title for it in axes.on_topic(llm, graph(), items)], ["Safety-critical scenario search"])
        self.assertEqual(llm.tasks, ["fit_topic"])

    def test_random_sample_is_read_and_drawn(self):
        from tastecal.core.config import Config
        from tastecal.core.model import Candidate, Item
        from tastecal.judge.gates import Gatekeeper

        class Src:
            def by_id(self, pid):
                return Item(id="s2:" + pid, title="Anchor " + pid, ids={"s2": pid})

            def forward(self, item, anchor):
                return [Candidate(item=Item(id=f"s2:f{k}{anchor}", title=f"Citing work {k} of {anchor}", ids={"s2": f"f{k}{anchor}"},
                                            date="2023-01", citations=k), anchor_id=anchor, direction="forward") for k in range(3)] + [
                    Candidate(item=Item(id="s2:dup", title="Paper n1 Title Words", ids={"s2": "dup"}), anchor_id=anchor,
                              direction="forward"),
                    Candidate(item=Item(id="s2:old" + anchor, title="Old work citing " + anchor, ids={"s2": "old" + anchor},
                                        date="2009-05"), anchor_id=anchor, direction="forward")]

            def backward(self, item, anchor):
                raise AssertionError("references are not drawn from")
        g = graph()
        for nd in g["nodes"]:
            nd["ids"] = {"s2": nd["id"]}
        items = axes.draw_sample(g, Src(), 3)
        self.assertEqual(len(items), 6)
        self.assertNotIn("Paper n1 Title Words", [it.title for it in items])       # already on the map
        self.assertFalse(any(it.title.startswith("Old work") for it in items))   # older than ten years
        self.assertTrue(any(it.title.startswith("Old work") for it in axes.draw_sample(g, Src(), 30, years=0)))
        self.assertEqual([it.title for it in items], [it.title for it in axes.draw_sample(g, Src(), 3)])   # same draw
        saved = Gatekeeper.fulltext
        Gatekeeper.fulltext = lambda self, node, item=None: ("full text " * 400, "full text", "arXiv HTML")
        try:
            done, missing = axes.read_items(items, Config(), Scripted(), None, "random", 3)
        finally:
            Gatekeeper.fulltext = saved
        self.assertEqual((len(done), missing), (3, 0))
        self.assertTrue(all(n["sample"] == "random" and n["gates"]["basis"] == "full text" for n in done))


class TowardLineTest(unittest.TestCase):
    """Step 2's scoring: the weights fitted so that the papers you have not rated come close to y = x, your scores a
    hard constraint."""
    def test_the_solver_finds_the_constrained_minimum(self):
        # min (z0 - 1)^2 + (z1 - 2)^2 with z0 + z1 <= 2, z >= 0: the answer is (0.5, 1.5)
        H, g = [[2.0, 0.0], [0.0, 2.0]], [-2.0, -4.0]
        G, h = [[1.0, 0.0], [0.0, 1.0], [-1.0, -1.0]], [0.0, 0.0, -2.0]
        z = axes.qp(H, g, G, h, [0.0, 0.0])
        self.assertAlmostEqual(z[0], 0.5, places=6)
        self.assertAlmostEqual(z[1], 1.5, places=6)
        z = axes.qp(H, g, G, h, [0.2, 0.2], iters=0)                  # stopped early: still a point that meets them
        self.assertTrue(axes._meets(z, G, h))

    def test_the_solver_agrees_with_a_slow_exact_method(self):
        # random problems shaped like the real one, several constraints tight at the start (rated papers missed by more
        # than the tolerance in step 1): the active set must reach the same minimum as Hildreth's dual method
        import random
        rnd = random.Random(7)

        def hildreth(H, g, G, h):
            n = len(g)
            Hi = [axes._solve(H, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]   # columns of H^-1
            Hinv = [[Hi[j][i] for j in range(n)] for i in range(n)]
            GHi = [[sum(G[a][k] * Hinv[k][i] for k in range(n)) for i in range(n)] for a in range(len(G))]
            P = [[sum(GHi[a][k] * G[b][k] for k in range(n)) for b in range(len(G))] for a in range(len(G))]
            d = [h[a] + sum(GHi[a][k] * g[k] for k in range(n)) for a in range(len(G))]
            lam = [0.0] * len(G)
            for _ in range(20000):
                for a in range(len(G)):
                    if P[a][a] > 0:
                        lam[a] = max(0.0, lam[a] + (d[a] - sum(P[a][b] * lam[b] for b in range(len(G)))) / P[a][a])
            v = [sum(G[a][k] * lam[a] for a in range(len(G))) - g[k] for k in range(n)]
            return [sum(Hinv[i][k] * v[k] for k in range(n)) for i in range(n)]
        for _ in range(4):
            k = 4
            Xr = [[rnd.choice([0, .2, .4, .6, .8, 1]) for _ in range(k)] for _ in range(7)]
            yr = [round(min(1, max(0, sum(x) / k + rnd.uniform(-.25, .25))), 2) for x in Xr]
            w0, b0 = axes.fit_scale(Xr, yr)
            tol = axes.tolerances(Xr, yr, w0, b0)
            Xc = [[rnd.choice([0, .2, .4, .6, .8, 1]) for _ in range(k)] for _ in range(15)]
            tc = [rnd.uniform(0, .5) for _ in Xc]
            n = k + 1
            mu = axes.RIDGE * sum((x[j] - sum(r[j] for r in Xc) / 15) ** 2 for x in Xc for j in range(k)) / k
            H = [[2 * sum((x + [1])[i] * (x + [1])[j] for x in Xc) + (2 * (mu if i < k else mu * 1e-4) if i == j else 0)
                  for j in range(n)] for i in range(n)]
            zc = list(w0) + [b0]
            g = [-2 * sum(t * (x + [1])[i] for x, t in zip(Xc, tc)) - 2 * (mu if i < k else mu * 1e-4) * zc[i] for i in range(n)]
            G, h = axes.constraints(Xr, yr, tol, k, zc)
            ref = hildreth(H, g, G, h)
            z = axes.qp(H, g, G, h, zc)
            val = lambda z: 0.5 * axes._dot(z, [axes._dot(row, z) for row in H]) + axes._dot(g, z)  # noqa: E731
            self.assertAlmostEqual(val(z), val(ref), places=5)
            self.assertTrue(axes._meets(z, G, h, 1e-6))

    def test_every_pair_you_ordered_is_held(self):
        # papers 0.6 apart: in order at the start they stay in order; the wrong way round they may not get worse
        Xr, yr = [[0.8, 0.2], [0.2, 0.8]], [0.9, 0.3]
        G, h = axes.constraints(Xr, yr, [1.0, 1.0], 2, [0.6, 0.2, 0.0])
        same = lambda row: all(abs(a - b) < 1e-9 for a, b in zip(row, [0.6, -0.6, 0.0]))  # noqa: E731
        self.assertTrue(any(same(row) and abs(hh - axes.ORDER_EPS) < 1e-12 for row, hh in zip(G, h)))
        G, h = axes.constraints(Xr, yr, [1.0, 1.0], 2, [0.2, 0.6, 0.0])   # step 1 had them the wrong way round
        self.assertTrue(any(same(row) and abs(hh - (-0.24)) < 1e-9 for row, hh in zip(G, h)))

    def test_the_order_is_step_1s_whatever_the_new_levels(self):
        # a field change makes the equal line put the pair the wrong way round; step 1 had it right: it must stay right
        Xr, yr = [[0.8, 0.2], [0.2, 0.8]], [0.9, 0.3]
        start = [0.2, 0.6, 0.0]                                       # the line on the new levels: the wrong way round
        G, h = axes.constraints(Xr, yr, [1.0, 1.0], 2, start, ref=[0.75, 0.35])   # step 1's scores: in order
        same = lambda row: all(abs(a - b) < 1e-9 for a, b in zip(row, [0.6, -0.6, 0.0]))  # noqa: E731
        self.assertTrue(any(same(row) and abs(hh - axes.ORDER_EPS) < 1e-12 for row, hh in zip(G, h)))

    def test_a_score_past_the_end_costs_nothing_more(self):
        # two papers the field barely cites sit far below 0 once the others are fitted: past 0 they are drawn at 0
        Xr, yr = [[0.2, 0.2], [0.8, 0.8]], [0.2, 0.8]
        Xc = [[0.0, 0.0], [0.0, 0.1]] + [[0.5, v] for v in (0.2, 0.4, 0.6, 0.8, 1.0)]
        tc = [0.0, 0.0] + [0.1, 0.3, 0.5, 0.7, 0.9]
        w0, b0 = axes.fit_scale(Xr, yr)
        tol = [1.0, 1.0]
        w, b = axes.fit_weights(Xr, yr, tol, Xc, tc, [1.0] * 7, (w0, b0), [(w0, b0)])
        drawn = lambda w, b: sum((axes.predict(x, w, b) - t) ** 2 for x, t in zip(Xc, tc))  # noqa: E731
        k, n = 2, 3
        H = [[2 * sum((x + [1])[i] * (x + [1])[j] for x in Xc) for j in range(n)] for i in range(n)]
        for i in range(n):
            H[i][i] += 1e-9
        g = [-2 * sum(t * (x + [1])[i] for x, t in zip(Xc, tc)) for i in range(n)]
        G, h = axes.constraints(Xr, yr, tol, k, list(w0) + [b0])
        raw = axes.qp(H, g, G, h, list(w0) + [b0])                     # the fit on raw scores, for comparison
        self.assertLessEqual(drawn(w, b), drawn(raw[:2], raw[2]) + 1e-9)

    def test_the_solver_does_not_stall_at_a_vertex(self):
        # a synthetic problem on which an earlier version stopped at the start: constraints met at a single point
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qp_stall.json"), encoding="utf-8") as f:
            d = json.load(f)
        Xr, yr, Xc, tc, wc = d["Xr"], d["yr"], d["Xc"], d["tc"], d["wc"]
        k, n = len(Xr[0]), len(Xr[0]) + 1
        w0, b0 = axes.fit_scale(Xr, yr)
        tol = axes.tolerances(Xr, yr, w0, b0)
        tot = sum(wc)
        mk = [sum(a * x[j] for a, x in zip(wc, Xc)) / tot for j in range(k)]
        mu = axes.RIDGE * sum(a * (x[j] - mk[j]) ** 2 for a, x in zip(wc, Xc) for j in range(k)) / k
        pull = [mu if j < k else mu * 1e-4 for j in range(n)]
        rows, zc = [list(x) + [1.0] for x in Xc], list(w0) + [b0]
        H = [[2 * sum(a * r[i] * r[j] for a, r in zip(wc, rows)) + (2 * pull[i] if i == j else 0) for j in range(n)] for i in range(n)]
        g = [-2 * sum(a * t * r[i] for a, r, t in zip(wc, rows, tc)) - 2 * pull[i] * zc[i] for i in range(n)]
        G, h = axes.constraints(Xr, yr, tol, k, zc)
        z = axes.qp(H, g, G, h, zc)
        val = 0.5 * axes._dot(z, [axes._dot(r, z) for r in H]) + axes._dot(g, z)
        self.assertLess(val, d["reference"] + 1e-5)
        self.assertTrue(axes._meets(z, G, h, 1e-7))

    def test_the_scale_at_its_edges(self):
        from tastecal.taste import attention as A

        def rows(vals, rel=1.0):
            return [{"id": str(i), "m": {"cumulative": v, "scale": "log", "rel": rel}} for i, v in enumerate(vals)]
        sc = A.scale(rows([0, 0, 0, 0, 0, 2, 5]), "cumulative", top=19000.0)
        self.assertEqual(sc["median"], 2.0)                           # most not cited yet: the least-cited cited paper
        self.assertLess(A.place(0.0, sc), 0.5)                        # no citation stays below the middle
        self.assertEqual(A.scale(rows([3, 3, 3, 3]), "cumulative", top=19000.0)["median"], 3.0)   # ties: no division by 0
        self.assertEqual(A.scale(rows([10, 20, 30, 40]), "cumulative", top=5.0)["top"], 40.0)   # a landmark below the middle is ignored
        pos = A.position(rows([0, 3, 30], rel=0.1), "cumulative", {"0": .5, "1": .5, "2": .5}, top=19000.0)
        self.assertGreater(pos["0"]["hi"], pos["0"]["x"])             # a paper with no citation yet still has a bar

    def test_free_weights_reach_the_line(self):
        # attention follows the second level only; your two papers do not tell the levels apart, so nothing holds the
        # weights back: the papers land on y = x
        Xr, yr = [[0.2, 0.2], [0.8, 0.8]], [0.2, 0.8]
        Xc = [[0.5, v] for v in (0.0, 0.25, 0.5, 0.75, 1.0)]
        tc = [0.2 + 0.6 * x[1] for x in Xc]
        w0, b0 = axes.fit_scale(Xr, yr)
        tol = axes.tolerances(Xr, yr, w0, b0)
        w, b = axes.fit_weights(Xr, yr, tol, Xc, tc, [1.0] * 5, (w0, b0), [(w0, b0)])
        self.assertLess(max(abs(axes.predict(x, w, b) - t) for x, t in zip(Xc, tc)), 0.03)
        self.assertAlmostEqual(w[1], 0.6, places=2)                    # the level the field follows
        self.assertAlmostEqual(w[0], w0[0], places=2)                  # one nothing decides stays where step 1 left it
        self.assertTrue(all(abs(axes.predict(x, w, b) - y) <= t for x, y, t in zip(Xr, yr, tol)))

    def test_your_scores_hold_against_the_field(self):
        # the field wants every paper at 0.1, your scores want 0.2 to 0.9 on the same levels: they stay within 0.1
        Xr = [[0.2], [0.4], [0.6], [0.8], [1.0]]
        yr = [0.2, 0.4, 0.55, 0.7, 0.9]
        Xc = [[0.3], [0.5], [0.7], [0.9]]
        w0, b0 = axes.fit_scale(Xr, yr)
        tol = axes.tolerances(Xr, yr, w0, b0)
        w, b = axes.fit_weights(Xr, yr, tol, Xc, [0.1] * 4, [1.0] * 4, (w0, b0), [(w0, b0)])
        for x, y, t in zip(Xr, yr, tol):
            self.assertLessEqual(abs(axes.predict(x, w, b) - y), t + 1e-6)
        self.assertLess(sum(axes.predict(x, w, b) for x in Xc), sum(axes.predict(x, w0, b0) for x in Xc))   # but lower
        self.assertEqual(axes.order_errors(yr, [axes.predict(x, w, b) for x in Xr]), [])

    def test_your_paper_drawn_at_random_is_not_compared(self):
        dup = node("n1", "Paper n1 Title Words")                     # your rated n1, drawn again under another id
        dup["id"], dup["sample"], dup["citations"] = "random-1", "random", 500
        res = axes.run(FieldScripted(), field_graph(), RATED, sample=[dup])
        self.assertNotIn("random-1", [r["id"] for r in res["map"]])

    def test_by_rank_the_chart_shows_what_was_fitted(self):
        g = field_graph()
        for n in g["nodes"]:
            n.pop("citations", None)                                  # no counts: the run's own percentile, by rank
        seen = {}
        orig = axes.field_phase

        def spy(*a, **k):
            r = orig(*a, **k)
            seen.update(r.get("targets") or {})
            return r
        axes.field_phase = spy
        try:
            res = axes.run(FieldScripted(), g, RATED)
        finally:
            axes.field_phase = orig
        self.assertEqual(res["attention_source"], "neighbourhood of this run")
        pos = res["views"]["cumulative"]["pos"]
        self.assertTrue(seen)
        self.assertTrue(all(pos[i]["x"] == t for i, t in seen.items()))   # drawn where the fit aimed it
        self.assertNotIn("cumulative", res["attention_anchor"])         # no top end to name

    def test_three_clauses_at_the_slope_cap(self):
        # 2/3 rounds to 0.6667: three of them sum to 2.0001, a hair above the cap; the start must still count
        Xr, yr = [[0.4, 0.4, 0.4], [0.5, 0.5, 0.5], [0.6, 0.6, 0.6]], [0.1, 0.5, 0.95]
        w0, b0 = axes.fit_scale(Xr, yr)
        self.assertGreater(sum(w0), axes.MAX_SLOPE)
        tol = axes.tolerances(Xr, yr, w0, b0)
        self.assertIsNotNone(axes.fit_weights(Xr, yr, tol, [[0.5, 0.2, 0.8]] * 3, [0.3] * 3, [1.0] * 3, (w0, b0), [(w0, b0)]))

    def test_a_start_is_searched_for_when_none_given_works(self):
        # step 1's line (both clauses alike) misses both papers by 0.3; giving all the weight to the first clause meets them
        Xr, yr = [[1.0, 0.0], [0.0, 1.0]], [0.8, 0.2]
        res = axes.fit_weights(Xr, yr, [0.1, 0.1], [[0.5, 0.5]], [0.5], [1.0], ([0.3, 0.3], 0.2), [([0.3, 0.3], 0.2)])
        self.assertIsNotNone(res)
        w, b = res
        self.assertTrue(all(abs(axes.predict(x, w, b) - y) <= 0.1 + 1e-6 for x, y in zip(Xr, yr)))

    def test_no_start_that_meets_your_scores(self):
        Xr, yr = [[0.5], [0.5]], [0.1, 0.9]                            # the same levels, scores 0.8 apart
        self.assertIsNone(axes.fit_weights(Xr, yr, [0.1, 0.1], [[0.5]], [0.5], [1.0], ([1.0], 0.0), [([1.0], 0.0)]))

    def test_attention_is_anchored_at_attention_is_all_you_need(self):
        import math
        from tastecal.taste import attention as A
        g = field_graph()
        raw = {"cited_by": 200000, "by_year": {}, "pub": "2017-06-12"}
        res = axes.run(FieldScripted(), g, RATED, anchor=raw)
        self.assertEqual(res["attention_anchor"]["cumulative"], A.ANCHOR_TITLE)
        months = A.months_since("2017-06", res["as_of"])
        top = 200000 / (months / 12)
        sc = res["attention_scale"]["cumulative"]
        self.assertAlmostEqual(sc["top"], top, places=1)              # the landmark is the top end
        self.assertEqual(sc["top_title"], A.ANCHOR_TITLE)
        r = next(r for r in res["map"] if r["id"] == "a4")
        pos = res["views"]["cumulative"]["pos"]["a4"]["x"]
        self.assertAlmostEqual(pos, round(A.place(r["m"]["cumulative"], A.scale([{"m": m["m"]} for m in res["map"]],
                                                                                "cumulative", top=top)), 3), places=3)
        self.assertLess(pos, 0.99)                                     # the map's most cited paper is below the landmark
        xs = sorted(p["x"] for p in res["views"]["cumulative"]["pos"].values())
        self.assertAlmostEqual(xs[len(xs) // 2], 0.5, delta=0.05)      # the typical paper in the middle
        self.assertNotIn("m1", res["views"]["cumulative"]["pos"])       # no citation count: no attention, not fitted


class RunTest(unittest.TestCase):
    def test_whole_run(self):
        llm = Scripted()
        rated = RATED + [{"ref": "Iota Open Urban Simulator", "score": 0.4, "comment": "a tool, not an idea"}]
        res = axes.run(llm, graph(), rated)
        self.assertEqual(len(res["rated"]), 8)                          # the rated tool is not used
        self.assertNotIn("Appeal", [d["name"] for d in res["start"]])   # "the reader likes it" is refused
        self.assertAlmostEqual(sum(d["share"] for d in res["weights"]), 1.0, places=2)
        self.assertTrue(all(0 <= r["s"] <= 1 for r in res["rated"]))
        self.assertTrue(any(r.get("recheck") for r in res["map"]))     # both ends re-measured next to a rated paper
        self.assertGreater(next(d["w"] for d in res["weights"] if d["name"] == H), 0.1)
        order = [r["id"] for r in res["map"]]
        self.assertEqual((order[0], order[-1]), ("m1", "m4"))
        self.assertEqual(res["map"][0]["class"], "best")
        self.assertEqual(res["map"][-1]["class"], "off")
        self.assertEqual([(o["id"], o["yours"]) for o in res["others"]], [("t1", 0.4)])
        for task, prompt in llm.prompts:
            if task == "fit_score":
                self.assertNotIn("Iota", prompt)                        # the tool is never scored
                self.assertNotIn("reason for", prompt)                  # measuring never sees your reasons
        html = page(res, "zh-CN")
        self.assertIn("审美校准", html)
        self.assertNotIn("品味", html)
        self.assertIn("<svg", html)
        self.assertIn(H, html)
        one = html.split('class="att"')[1].split("</svg>")[0]
        self.assertEqual(one.count('<g class="pt'), len(res["map"]))    # each predicted paper drawn once on a chart
        for r in res["map"]:
            self.assertIn(f'data-id="{r["id"]}"', one)                  # and can be picked out
        for tab in ("overview", "papers", "views", "clauses", "process"):
            self.assertIn(f'id="panel-{tab}"', html)                    # the report is in tabs
        self.assertNotIn("我被误导的", html)                            # your scores are never judged
        self.assertIn("领域关注度", html)
        self.assertIn("cumulative", res["views"])                       # the run's own percentile when nothing is looked up
        self.assertIn("skipped", res["field"])                          # four papers are too few to fit to the field
        self.assertIn('class="anc', html.split('class="att"', 1)[1])        # your rated papers on y = x, as a reference
        self.assertTrue(all("threads" in r and "role" in r for r in res["map"]))

    def test_your_scores_are_reproduced_and_old_papers_left_out(self):
        g = graph()
        g["meta"]["generated_at"] = "2026-10-19 09:00"
        next(n for n in g["nodes"] if n["id"] == "m2")["date"] = "2009-03"
        res = axes.run(Scripted(), g, RATED)
        self.assertLessEqual(res["max_err"], axes.FIT_TOL)               # the clauses reproduce your scores
        self.assertTrue(all("loo" in r and not r["side"] for r in res["rated"]))   # never judged, only reproduced
        self.assertNotIn("m2", [r["id"] for r in res["map"]])            # older than ten years: not compared
        self.assertEqual([o["id"] for o in res["older"]], ["m2"])
        self.assertEqual(res["years"], axes.YEARS)
        self.assertIn("m2", [r["id"] for r in axes.run(Scripted(), g, RATED, years=0)["map"]])
        self.assertTrue(axes.recent({"date": ""}, "2026-10-19"))         # a paper without a date is kept

    def test_every_clause_counts_the_same_and_one_can_be_taken_out(self):
        saved = axes.FIT_TOL
        axes.FIT_TOL = 0.01                                         # keep the loop going past the first change
        try:
            res = axes.run(Scripted(), graph(), RATED)
        finally:
            axes.FIT_TOL = saved
        kept = [h["change"] for h in res["history"] if h.get("accepted")]
        self.assertTrue(any(c.startswith("remove") for c in kept))     # a clause the reader ignores is taken out
        self.assertNotIn(V, [d["name"] for d in res["indicators"]])
        self.assertEqual(len({w["share"] for w in res["weights"]}), 1)   # no weights to fit: every clause counts the same
        r = res["rated"][0]                                          # your papers are read twice and the reads averaged
        self.assertEqual(set(r["x1"]), set(r["x2"]))
        self.assertTrue(all(r["x"][n] == round((r["x1"][n] + r["x2"][n]) / 2, 3) for n in r["x1"]))
        self.assertLess(res["mae"], 0.03)

    def test_concept_works_are_not_scored(self):
        llm = Scripted()
        llm.concept = ["m3"]
        res = axes.run(llm, graph(), RATED)
        self.assertNotIn("m3", [r["id"] for r in res["map"]])
        self.assertIn(("m3", "concept"), [(o["id"], o["type"]) for o in res["others"]])
        self.assertIn("fit_types", llm.tasks)
        html = page(res, "zh")
        self.assertIn("概念", html)

    def test_needs_three_rated_papers(self):
        self.assertIn("error", axes.run(Scripted(), graph(), RATED[:2]))

    def test_cli(self):
        from tastecal import cli
        d = tempfile.mkdtemp()
        gp = os.path.join(d, "graph.json")
        with open(gp, "w", encoding="utf-8") as f:
            json.dump(graph(), f)
        rp = os.path.join(d, "ratings.txt")
        with open(rp, "w", encoding="utf-8") as f:
            f.write("\n".join(f"{r['ref']} | {r['score']} | {r['comment']}" for r in RATED))
        import tastecal.core.llm as L
        saved = L.make_llm
        L.make_llm = lambda cfg, http=None: Scripted()
        try:
            self.assertEqual(cli.main(["fit", gp, "--rated", rp, "--max", "2", "--cache-dir", d, "--no-attention", "--random-share", "0"]), 0)
        finally:
            L.make_llm = saved
        with open(os.path.join(d, "taste_fit.json"), encoding="utf-8") as f:
            res = json.load(f)
        self.assertEqual(len(res["map"]), 2)
        hp = os.path.join(d, "taste_fit.html")
        self.assertTrue(os.path.exists(hp))
        os.remove(hp)
        L.make_llm = lambda cfg, http=None: self.fail("--redraw calls no model")
        try:
            self.assertEqual(cli.main(["fit", gp, "--redraw"]), 0)
        finally:
            L.make_llm = saved
        with open(hp, encoding="utf-8") as f:
            self.assertIn("<svg", f.read())                         # two predicted papers: too few to rank, no second chart


if __name__ == "__main__":
    unittest.main()
