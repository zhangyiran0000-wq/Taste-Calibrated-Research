"""Runs report the model id that actually answered and the effort, not only the alias asked for."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.config import Config  # noqa: E402
from tastecal.core.llm import LLM, LLMError, make_llm  # noqa: E402
from tastecal.app.serve import model_in_use  # noqa: E402

FAKE_CLAUDE = r'''#!PY
import json, sys
sys.stdin.read()
print(json.dumps({"type": "result", "is_error": False, "result": "{\"ok\": 1}", "total_cost_usd": 0.25,
                  "modelUsage": {"claude-haiku-5-5": {"outputTokens": 3, "costUSD": 0.001},
                                 "claude-opus-5-5": {"outputTokens": 900, "costUSD": 0.249}}}))
'''

FAKE_CODEX = r'''#!PY
import sys
args = sys.argv[1:]; sys.stdin.read()
sys.stderr.write("OpenAI Codex\n--------\nworkdir: /tmp/x\nmodel: gpt-6-astra\nprovider: openai\nreasoning effort: xhigh\n--------\n")
open(args[args.index("-o") + 1], "w").write('{"ok": 2}')
'''


FAKE_TOOL_HAPPY = r"""#!PY
import json, sys
args = sys.argv[1:]
if "--tools" in args and "NO_TOOLS_FLAG" in sys.argv[0]:
    sys.stderr.write("error: unknown option '--tools'\n"); sys.exit(1)
prompt = sys.stdin.read()
if "Do not call any tool" in prompt:
    print(json.dumps({"type": "result", "is_error": False, "result": "{\"ok\": 3}"}))
else:
    print(json.dumps({"type": "result", "is_error": True, "subtype": "error_max_turns", "result": None,
                      "errors": ["Reached maximum number of turns (1)"]}))
"""


def fake(dirname, name, body):
    path = os.path.join(dirname, name)
    with open(path, "w") as f:
        f.write(body.replace("#!PY", "#!" + sys.executable))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class ModelUsedTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for k in ("CLAUDE_BIN", "CODEX_BIN"):
            os.environ.pop(k, None)

    def test_claude_cli_reports_the_real_model(self):
        os.environ["CLAUDE_BIN"] = fake(self.dir, "claude", FAKE_CLAUDE)
        llm = make_llm(Config(provider="claude-cli", model="opus", cache_dir=None, effort="xhigh"), None)
        with self.assertLogs("tastecal.llm", "INFO") as logs:
            self.assertEqual(llm.json("S", "P"), {"ok": 1})
            llm.json("S", "P2")
        self.assertEqual(llm.model_used(), "claude-opus-5-5")         # the model that did the work, not the helper
        self.assertEqual(llm.describe(), "claude-cli:claude-opus-5-5 · effort xhigh")
        self.assertEqual(sum("model in use: claude-opus-5-5 · effort xhigh" in m for m in logs.output), 1)   # logged once
        self.assertIn("$0.50 at API prices", llm.usage())

    def test_a_tool_call_is_answered_with_a_nudge_not_a_wait(self):
        os.environ["CLAUDE_BIN"] = fake(self.dir, "claude", FAKE_TOOL_HAPPY)
        llm = make_llm(Config(provider="claude-cli", model="opus", cache_dir=None), None)
        llm.sleeper = lambda s: self.fail("must not wait")
        with self.assertLogs("tastecal.llm", "INFO") as logs:
            self.assertEqual(llm.json("S", "P"), {"ok": 3})
        self.assertTrue(any("tried to use a tool" in m for m in logs.output))

    def test_no_tools_option_falls_back_to_the_list(self):
        os.environ["CLAUDE_BIN"] = fake(self.dir, "claude_NO_TOOLS_FLAG", FAKE_TOOL_HAPPY)
        llm = make_llm(Config(provider="claude-cli", model="opus", cache_dir=None), None)
        self.assertEqual(llm.json("S", "P"), {"ok": 3})
        self.assertNotIn("--tools", llm.extra)
        self.assertIn("--no-chrome", llm.extra)
        self.assertTrue(llm.lean)                                   # the rest of the lean form is kept

    def test_codex_reports_model_and_effort(self):
        os.environ["CODEX_BIN"] = fake(self.dir, "codex", FAKE_CODEX)
        llm = make_llm(Config(provider="codex-cli", model="", cache_dir=None), None)
        self.assertEqual(llm.json("S", "P"), {"ok": 2})
        self.assertEqual(llm.describe(), "codex-cli:gpt-6-astra · effort xhigh")   # Codex's own default effort, as reported

    def test_default_effort_and_cache_key(self):
        class Echo(LLM):
            name = "x:m"

            def _complete(self, system, prompt, max_tokens):
                return "a"
        a, b = Echo(), Echo()
        b.effort = "xhigh"
        self.assertEqual(a.describe(), "x:m · effort default")
        self.assertNotEqual(a._key("s", "p"), b._key("s", "p"))       # another effort never reuses cached answers

    def test_serve_reads_it_from_the_log_or_the_report(self):
        run = os.path.join(self.dir, "run")
        os.makedirs(run)
        self.assertEqual(model_in_use(run), ("", ""))
        with open(os.path.join(run, "console.log"), "w") as f:
            f.write("15:48:31 tastecal: tastecal 0.1.0 · model claude-cli:opus · effort default · budget 30\n"
                    "15:48:40 tastecal.llm: model in use: claude-opus-5-5 · effort default\n")
        self.assertEqual(model_in_use(run), ("claude-opus-5-5", "default"))
        os.remove(os.path.join(run, "console.log"))
        g = {"meta": {"model": "claude-cli:claude-opus-5-5 · effort xhigh"}}
        self.assertEqual(model_in_use(run, g), ("claude-opus-5-5", "xhigh"))


if __name__ == "__main__":
    unittest.main()


class RestartTest(unittest.TestCase):
    """A run keeps going when the page's server restarts, and the new server still shows and stops it."""

    def test_run_from_an_earlier_server(self):
        import subprocess
        import time
        from tastecal.app.serve import Runner, run_alive
        base = tempfile.mkdtemp()
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "tastecal", "run"],
                                start_new_session=True)
        try:
            self.assertTrue(run_alive(proc.pid))
            run = os.path.join(base, "runs", "r1")
            os.makedirs(run)
            with open(os.path.join(run, "request.json"), "w") as f:
                json.dump({"seed": "x", "provider": "claude-cli", "model": "opus", "budget": 30}, f)
            with open(os.path.join(run, "status.json"), "w") as f:
                json.dump({"state": "running", "pid": proc.pid, "started": "2026-10-15T15:48:31"}, f)
            runner = Runner(base)                        # a new server: it did not start this run
            row = next(r for r in runner.list() if r["id"] == "r1")
            self.assertEqual(row["state"], "running")
            self.assertFalse(runner.delete("r1"))      # cannot delete while it runs
            self.assertTrue(runner.stop("r1"))
            for _ in range(50):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            self.assertIsNotNone(proc.poll())
            self.assertFalse(run_alive(proc.pid))
            self.assertEqual(next(r for r in runner.list() if r["id"] == "r1")["state"], "stopped")
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_page_accepts_plain_model_ids(self):
        page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "tastecal", "app", "app.html"), encoding="utf-8").read()
        self.assertIn("Array.isArray(m) ? m : [String(m), String(m)]", page)


FAKE_STREAM = r'''#!PY
import json, os, sys
args = sys.argv[1:]; sys.stdin.read()
if os.environ.get("FAKE_OLD") and "--system-prompt" in args:
    sys.stderr.write("error: unknown option '--system-prompt'\n"); sys.exit(1)
src = os.environ.get("FAKE_SRC", "none")
if "stream-json" in args:
    print(json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5", "apiKeySource": src}))
    print(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5"}}))
print(json.dumps({"type": "result", "is_error": False, "result": "OK", "usage": {"input_tokens": 12, "output_tokens": 1},
                  "modelUsage": {"claude-opus-5-5": {"outputTokens": 1}}}))
'''


class BillingTest(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "TASTECAL_CLAUDE_KEEP_KEY"):
            os.environ.pop(k, None)
        self.dir = tempfile.mkdtemp()
        os.environ["CLAUDE_BIN"] = fake(self.dir, "claude", FAKE_STREAM)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def test_plan(self):
        llm = make_llm(Config(provider="claude-cli", model="opus", cache_dir=None), None)
        with self.assertLogs("tastecal.llm", "INFO") as logs:
            self.assertEqual(llm.complete("S", "P"), "OK")
        self.assertIn("Claude plan", llm.billed_to)
        self.assertTrue(any("Claude Code is billing your Claude plan" in m for m in logs.output))
        self.assertEqual(llm.model_used(), "claude-opus-5-5")

    def test_api_key_stops_the_run(self):
        os.environ["FAKE_SRC"] = "ANTHROPIC_API_KEY"
        llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
        with self.assertRaises(LLMError) as caught:
            llm.complete("S", "P")
        self.assertIn("not your Claude plan", str(caught.exception))
        self.assertIn("ANTHROPIC_API_KEY", llm.billed_to)
        self.assertEqual(llm.calls, 1)              # final: not retried

    def test_api_key_allowed_when_asked(self):
        os.environ["FAKE_SRC"] = "ANTHROPIC_API_KEY"
        os.environ["TASTECAL_CLAUDE_KEEP_KEY"] = "1"
        llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
        self.assertEqual(llm.complete("S", "P"), "OK")
        self.assertIn("not your Claude plan", llm.billed_to)

    def test_keys_left_out_of_claude_code(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        os.environ["ANTHROPIC_BASE_URL"] = "https://gateway.example"
        llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
        env = llm._env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertEqual(env["CLAUDE_BIN"], os.environ["CLAUDE_BIN"])
        os.environ["TASTECAL_CLAUDE_KEEP_KEY"] = "1"
        self.assertEqual(llm._env()["ANTHROPIC_API_KEY"], "sk-test")

    def test_payment_errors_are_final(self):
        self.assertTrue(make_llm(Config(provider="claude-cli", cache_dir=None), None).FINAL.search(
            "API Error: 402 已达到总费用限制 ($282000)"))

    def test_older_claude_code_falls_back(self):
        os.environ["FAKE_OLD"] = "1"
        llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
        self.assertEqual(llm.complete("S", "P"), "OK")
        self.assertFalse(llm.lean)
        self.assertEqual(llm.model_used(), "claude-opus-5-5")
