"""Field limit: works from other fields are listed as borrowed tools, not mapped, read or audited."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tastecal.core.config import Config  # noqa: E402
from tastecal.lineage.grow import Grower  # noqa: E402
from tastecal.report.render import render_html  # noqa: E402
from tastecal.core.schema import validate  # noqa: E402
from tastecal.app.serve import Runner, clean_request  # noqa: E402
from tastecal.lineage.synthesize import synthesize  # noqa: E402
from fakes import FakeLLM, FakeSource  # noqa: E402

OUTSIDE = {"Beta Adapters": "general NLP adapters"}       # in this test, Beta is a tool from another field


class ScopedLLM(FakeLLM):
    def t_scope_check(self, p):
        assert "limited to this field: model adaptation" in p
        rows = []
        for i in self._ids(p, "Works:"):
            line = next(ln for ln in p.splitlines() if ln.startswith(f"[{i}]"))
            title = line.split("] ", 1)[1].rsplit(" (", 1)[0]
            rows.append({"id": i, "in_scope": title not in OUTSIDE, "field": OUTSIDE.get(title, "model adaptation")})
        return rows


def grow(scope="", llm=None, budget=8):
    cfg = Config(budget=budget, max_rounds=3, use_openalex=False, use_web=False, cache_dir=tempfile.mkdtemp(), scope=scope)
    llm = llm or ScopedLLM()
    return Grower(cfg, FakeSource(), llm).run("seed"), llm


class ScopeTest(unittest.TestCase):
    def test_outside_work_is_borrowed_not_mapped(self):
        g, llm = grow("model adaptation")
        titles = {n.item.title for n in g.nodes.values()}
        self.assertNotIn("Beta Adapters", titles)
        self.assertIn("Alpha: Small Updates Suffice", titles)              # in the field: still mapped
        self.assertIn("Gamma: Quantized SeedNet", titles)
        rows = g.imports_list()
        self.assertEqual([r["title"] for r in rows], ["Beta Adapters"])
        self.assertEqual(rows[0]["used_by"], [g.seed_id])
        self.assertEqual((rows[0]["direction"], rows[0]["field"]), ("backward", "general NLP adapters"))
        self.assertTrue(any("Stay within this field: model adaptation" in p for t, p in llm.prompts if t == "problem_queries"))
        self.assertNotIn("Beta Adapters", [c.item.title for _, c, _ in g.pool(20)])   # not a runner-up for the audit

    def test_graph_and_report(self):
        g, llm = grow("model adaptation")
        graph = synthesize(g, llm, "seed")
        self.assertEqual(validate(graph), [])
        self.assertEqual(graph["meta"]["scope"], "model adaptation")
        self.assertEqual(graph["imports"][0]["used_by"], [graph["meta"]["seed"]])     # re-keyed with the nodes
        html = render_html(graph)
        self.assertNotIn("Borrowed from other fields", html)        # kept in graph.json, not shown in the report
        graph["meta"]["language"] = "zh-CN"
        self.assertNotIn("借自其他领域", render_html(graph))        # and every Chinese pair still matches

    def test_no_limit_is_unchanged(self):
        g, llm = grow("", llm=FakeLLM())
        self.assertNotIn("scope_check", llm.tasks)
        self.assertIn("Beta Adapters", {n.item.title for n in g.nodes.values()})
        graph = synthesize(g, llm, "seed")
        self.assertNotIn("imports", graph)
        self.assertNotIn("scope", graph["meta"])
        self.assertFalse(any("Stay within" in p for _, p in llm.prompts))

    def test_each_work_is_asked_once(self):
        g, llm = grow("model adaptation")
        asked = [p for t, p in llm.prompts if t == "scope_check"]
        ids = [ln.split("]")[0] for p in asked for ln in p.splitlines() if ln.startswith("[")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_page_and_resume_carry_it(self):
        req = clean_request({"seed": "x", "provider": "claude-cli", "scope": "  autonomous   driving "})
        self.assertEqual(req["scope"], "autonomous driving")
        cmd = Runner.default_command(req, "/tmp/out", "/tmp/taste.md")
        self.assertEqual(cmd[cmd.index("--scope") + 1], "autonomous driving")
        self.assertNotIn("--scope", Runner.default_command(clean_request({"seed": "x", "provider": "claude-cli"}),
                                                           "/tmp/out", "/tmp/taste.md"))

    def test_resume_keeps_the_limit(self):
        import json
        from tastecal import cli
        run = tempfile.mkdtemp()
        with open(os.path.join(run, "request.json"), "w") as f:
            json.dump({"seed": "UniAD", "provider": "claude-cli", "model": "claude-opus-5-5", "effort": "high",
                       "budget": 30, "scope": "autonomous driving"}, f)
        seen, real = {}, cli.main
        cli.main = lambda argv=None: seen.setdefault("argv", argv) and 0
        try:
            os.environ["TASTECAL_SERVED"] = "1"
            cli.cmd_resume(type("A", (), {"folder": run})())
        finally:
            cli.main = real
            os.environ.pop("TASTECAL_SERVED", None)
        a = seen["argv"]
        self.assertEqual(a[a.index("--scope") + 1], "autonomous driving")


if __name__ == "__main__":
    unittest.main()


class HomeFieldLLM(ScopedLLM):
    """No --scope: the seed's field is inferred, and Beta is a tool from another field."""
    def t_home_field(self, p):
        return {"field": "model adaptation"}


class BorrowedToolTest(unittest.TestCase):
    def test_tool_from_another_field_joins_but_does_not_grow(self):
        g, llm = grow("", llm=HomeFieldLLM())
        self.assertEqual(g.home, "model adaptation")
        beta = [n for n in g.nodes.values() if n.item.title == "Beta Adapters"]
        self.assertEqual(len(beta), 1)                       # kept on the map, one hop from the seed
        self.assertTrue(beta[0].borrowed)
        self.assertNotIn(beta[0].item.id, g.expanded)        # never opened
        self.assertFalse(any(beta[0].item.id in p.raised_by for p in g.ledger.problems.values()))
        self.assertTrue(all(not n.borrowed for n in g.nodes.values() if n.item.title != "Beta Adapters"))
        graph = synthesize(g, llm, "seed")
        self.assertEqual(validate(graph), [])
        self.assertTrue(any(n.get("borrowed") for n in graph["nodes"]))
