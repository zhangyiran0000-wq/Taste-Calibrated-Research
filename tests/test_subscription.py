"""Subscriptions by default: the tool you are signed in to, waiting out usage limits, Codex on the ChatGPT plan only,
and presets per plan."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.cli import resolve_plan  # noqa: E402
from tastecal.core.config import PLANS, Config, plan_settings  # noqa: E402
from tastecal.core.llm import LLM, ClaudeCLILLM, CodexCLILLM, LLMError, detect_provider, make_llm, reset_time  # noqa: E402
from tastecal.app.serve import billed_to, clean_request, providers_state, stage  # noqa: E402


def local(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi).timestamp()


def script(dirname, name, body):
    path = os.path.join(dirname, name)
    with open(path, "w") as f:
        f.write("#!" + sys.executable + "\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class Clock:
    """A fake wall clock: sleeping moves it forward at once."""
    def __init__(self, t):
        self.t = t
        self.slept = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.slept += s


class ResetTimeTest(unittest.TestCase):
    def test_epoch(self):
        self.assertEqual(reset_time("Claude AI usage limit reached|1760000000", 1.0), 1760000000.0)

    def test_delay(self):
        now = 1_000_000.0
        self.assertEqual(reset_time("You've hit your usage limit. Upgrade to Pro or try again in 4 days 3 hours 40 minutes.", now),
                         now + 4 * 86400 + 3 * 3600 + 40 * 60)
        self.assertEqual(reset_time("Session limit reached, resets in 45m", now), now + 45 * 60)

    def test_clock_time(self):
        ten = local(2026, 10, 16, 10)
        self.assertEqual(reset_time("5-hour limit reached ∙ resets 3pm", ten), local(2026, 10, 16, 15))
        self.assertEqual(reset_time("limit reached. Your limit will reset at 15:30", ten), local(2026, 10, 16, 15, 30))
        self.assertEqual(reset_time("Please try again at 3:45 PM.", ten), local(2026, 10, 16, 15, 45))
        # a time already gone today means tomorrow
        self.assertEqual(reset_time("5-hour limit reached ∙ resets 3pm", local(2026, 10, 16, 16)), local(2026, 10, 17, 15))
        self.assertEqual(reset_time("resets 12am", ten), local(2026, 10, 17, 0))

    def test_date(self):
        self.assertEqual(reset_time("Weekly limit reached · resets Oct 20, 9am", local(2026, 10, 16, 10)), local(2026, 10, 20, 9))
        self.assertEqual(reset_time("Weekly limit reached · resets Jan 3 at 9:30 AM", local(2026, 12, 30, 10)), local(2027, 1, 3, 9, 30))

    def test_time_zone(self):
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Singapore")
        except Exception:
            self.skipTest("no time zone database")
        now = dt.datetime(2026, 10, 16, 10, tzinfo=tz).timestamp()
        self.assertEqual(reset_time("You've hit your limit · resets 3pm (Asia/Singapore)", now),
                         dt.datetime(2026, 10, 16, 15, tzinfo=tz).timestamp())

    def test_unknown(self):
        self.assertIsNone(reset_time("usage limit reached"))
        self.assertIsNone(reset_time("resets soon"))
        self.assertIsNone(reset_time("resets Monday"))


class Flaky(LLM):
    """Fails with the given messages first, then answers."""
    name = "flaky"

    def __init__(self, errors, waits=True, max_wait=10 * 86400):
        super().__init__(None)
        self.errors = list(errors)
        self.waits_for_limits = waits
        self.max_wait = max_wait
        self.tries = 0

    def _complete(self, system, prompt, max_tokens):
        self.tries += 1
        if self.errors:
            raise LLMError(self.errors.pop(0))
        return "ok"


T0 = 1_760_000_000.0


class WaitTest(unittest.TestCase):
    def make(self, errors, **kw):
        llm = Flaky(errors, **kw)
        self.clock = Clock(T0)
        llm.clock, llm.sleeper = self.clock.now, self.clock.sleep
        return llm

    def test_waits_until_the_reset(self):
        llm = self.make([f"claude -p reported an error: Claude AI usage limit reached|{int(T0) + 7200}"])
        with self.assertLogs("tastecal.llm", "WARNING") as logs:
            self.assertEqual(llm.complete("S", "P"), "ok")
        self.assertEqual(self.clock.t, T0 + 7200 + 60)       # the reset, plus a minute
        self.assertAlmostEqual(llm.limit_waited, 7260)
        self.assertTrue(any("usage limit reached; waiting until" in m for m in logs.output))
        self.assertEqual(llm.tries, 2)

    def test_no_reset_time_polls(self):
        llm = self.make(["You've hit your usage limit.", "You've hit your usage limit."])
        self.assertEqual(llm.complete("S", "P"), "ok")
        self.assertEqual(self.clock.slept, 2 * 30 * 60)
        llm = self.make(["API Error: 429 Too Many Requests"])
        self.assertEqual(llm.complete("S", "P"), "ok")
        self.assertEqual(self.clock.slept, 5 * 60)

    def test_cap(self):
        llm = self.make(["usage limit reached|%d" % (T0 + 3 * 86400)], max_wait=86400)
        with self.assertRaises(LLMError) as caught:
            llm.complete("S", "P")
        self.assertIn("may not wait", str(caught.exception))
        self.assertEqual(self.clock.slept, 0)

    def test_off(self):
        llm = self.make(["Claude AI usage limit reached|%d" % (T0 + 100)], waits=False)
        with self.assertRaises(LLMError):
            llm.complete("S", "P")
        self.assertEqual(llm.tries, 1)

    def test_sign_in_and_money_are_not_waited_out(self):
        for msg in ("claude -p reported an error: Invalid API key · Please run /login",
                    "claude -p reported an error: API Error: 402 已达到总费用限制 ($282000)",
                    "Claude Code is billing an API key (ANTHROPIC_API_KEY), not your Claude plan. ... usage limit",
                    "This Claude Code is too old for the model claude-opus-5-5. Run `claude update` in Terminal, then start "
                    "again. Claude Code said: API Error: 400 Claude Code 2.1.237 does not support this model; version "
                    "2.1.280 or newer is required. Run 'claude update', or update your install, then try again."):
            llm = self.make([msg])
            with self.assertRaises(LLMError):
                llm.complete("S", "P")
            self.assertEqual((llm.tries, self.clock.slept), (1, 0), msg)


FAKE_CLAUDE = r'''import json, os, sys
sys.stdin.read()
state = os.environ["FAKE_STATE"]
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
print(json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5", "apiKeySource": "none"}))
if n == 0:
    print(json.dumps({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|" + os.environ["FAKE_RESET"]}))
else:
    print(json.dumps({"type": "result", "is_error": False, "result": "OK", "modelUsage": {"claude-sonnet-5-5": {"outputTokens": 1}}}))
'''

FAKE_CODEX = r'''import json, os, sys
args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    print(os.environ.get("FAKE_STATUS", "Logged in using ChatGPT")); sys.exit(0)
sys.stdin.read()
json.dump({"key": os.environ.get("OPENAI_API_KEY")}, open(os.environ["FAKE_LOG"], "w"))
open(args[args.index("-o") + 1], "w").write("OK")
'''


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TASTECAL_ALLOW_KEY", "TASTECAL_CLAUDE_KEEP_KEY", "S2_API_KEY"):
            os.environ.pop(k, None)
        self.dir = tempfile.mkdtemp()
        self.claude = script(self.dir, "claude", FAKE_CLAUDE)
        self.codex = script(self.dir, "codex", FAKE_CODEX)
        os.environ.update(FAKE_STATE=os.path.join(self.dir, "n"), FAKE_LOG=os.path.join(self.dir, "codex.json"))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def sent_key(self):
        with open(os.environ["FAKE_LOG"]) as f:
            return json.load(f)["key"]

    def test_auto_picks_the_subscription_tool(self):
        os.environ["CLAUDE_BIN"], os.environ["CODEX_BIN"] = self.claude, self.codex
        self.assertEqual(detect_provider(), "claude-cli")
        cfg = Config(provider="auto", cache_dir=None)
        self.assertIsInstance(make_llm(cfg, None), ClaudeCLILLM)
        self.assertEqual(cfg.provider, "claude-cli")
        os.environ["CLAUDE_BIN"] = os.path.join(self.dir, "missing")
        self.assertEqual(detect_provider(), "codex-cli")
        os.environ["CODEX_BIN"] = os.path.join(self.dir, "missing")
        with self.assertRaises(LLMError) as caught:
            detect_provider()
        self.assertIn("Claude account with subscription", str(caught.exception))
        self.assertEqual(Config().provider, "auto")

    def test_claude_code_waits_for_the_reset(self):
        os.environ.update(CLAUDE_BIN=self.claude, FAKE_RESET=str(int(time.time()) + 600))
        llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
        clock = Clock(time.time())
        llm.clock, llm.sleeper = clock.now, clock.sleep
        self.assertEqual(llm.complete("S", "P"), "OK")
        self.assertGreaterEqual(clock.slept, 600)
        self.assertIn("Claude plan", llm.billed_to)

    def test_codex_on_the_chatgpt_plan_only(self):
        os.environ.update(CODEX_BIN=self.codex, OPENAI_API_KEY="sk-test")
        llm = make_llm(Config(provider="codex-cli", cache_dir=None), None)
        self.assertIsInstance(llm, CodexCLILLM)
        with self.assertLogs("tastecal.llm", "INFO") as logs:
            self.assertEqual(llm.complete("S", "P"), "OK")
        self.assertIn("ChatGPT plan", llm.billed_to)
        self.assertTrue(any("Codex is billing your ChatGPT plan" in m for m in logs.output))
        self.assertIsNone(self.sent_key())       # the key was left out

        os.environ["FAKE_STATUS"] = "Logged in using an API key - sk-proj-***ABCD"
        llm = make_llm(Config(provider="codex-cli", cache_dir=None), None)
        with self.assertRaises(LLMError) as caught:
            llm.complete("S", "P")
        self.assertIn("not your ChatGPT plan", str(caught.exception))
        with self.assertRaises(LLMError):                 # and again: a step that skipped the error cannot go on
            llm.complete("S", "P2")

        os.environ["TASTECAL_ALLOW_KEY"] = "1"
        llm = make_llm(Config(provider="codex-cli", cache_dir=None), None)
        self.assertEqual(llm.complete("S", "P"), "OK")
        self.assertEqual(self.sent_key(), "sk-test")

        os.environ.pop("TASTECAL_ALLOW_KEY")
        os.environ["FAKE_STATUS"] = "Not logged in"
        llm = make_llm(Config(provider="codex-cli", cache_dir=None), None)
        with self.assertRaises(LLMError) as caught:
            llm.complete("S", "P")
        self.assertIn("codex login", str(caught.exception))

    def test_a_stuck_call_is_ended_with_everything_it_started(self):
        # Claude Code starts a helper that keeps the output pipe open, then hangs: the call must end anyway, its
        # helper with it, and be tried again (on Windows a plain timeout would wait on that pipe forever)
        import subprocess
        from tastecal.core import llm as L
        pidfile = os.path.join(self.dir, "helper.pid")
        stuck = script(self.dir, "claude-stuck", (
            "import subprocess, sys, time\n"
            "if '--version' in sys.argv: print('2.1.0'); sys.exit(0)\n"
            "h = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            f"open({pidfile!r}, 'w').write(str(h.pid))\n"
            "time.sleep(120)\n"))
        t0 = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            L.run_capped([stuck], "prompt", self.dir, dict(os.environ), timeout=1)
        self.assertLess(time.time() - t0, 15)
        with open(pidfile) as f:
            pid = int(f.read())
        time.sleep(0.3)
        state = ""
        try:
            with open(f"/proc/{pid}/status") as f:
                state = next((ln.split()[1] for ln in f if ln.startswith("State:")), "")
        except OSError:
            pass                                                    # gone
        self.assertIn(state, ("", "Z", "X"))                        # the helper was ended too
        ok = L.run_capped([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], "hi", self.dir, dict(os.environ))
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "HI"))
        # through the model class: the timeout is a model-call failure that is tried again, never a hang
        os.environ["CLAUDE_BIN"] = stuck
        saved = L.CALL_TIMEOUT
        L.CALL_TIMEOUT = 1
        try:
            llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
            llm.WAITS = (0,)
            llm.sleeper = lambda s: None
            with self.assertLogs("tastecal.llm", "WARNING") as logs, self.assertRaises(LLMError) as caught:
                llm.complete("S", "P")
            self.assertIn("timed out", str(caught.exception))
            self.assertTrue(any("trying again" in m for m in logs.output))
        finally:
            L.CALL_TIMEOUT = saved

    def test_old_allow_name_still_works(self):
        os.environ["TASTECAL_CLAUDE_KEEP_KEY"] = "1"
        os.environ["ANTHROPIC_API_KEY"] = "sk-x"
        os.environ["CLAUDE_BIN"] = self.claude
        self.assertEqual(make_llm(Config(provider="claude-cli", cache_dir=None), None)._env()["ANTHROPIC_API_KEY"], "sk-x")


class PlanTest(unittest.TestCase):
    def ns(self, **kw):
        base = dict(plan=None, provider="auto", model=None, budget=None)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_preset_fills_what_you_did_not_set(self):
        a = self.ns(plan="claude-pro")
        resolve_plan(a)
        self.assertEqual((a.provider, a.model, a.budget), ("claude-cli", "claude-opus-5-5", 30))
        a = self.ns(plan="claude-max", budget=40, model="claude-haiku-5-5")
        resolve_plan(a)
        self.assertEqual((a.provider, a.model, a.budget), ("claude-cli", "claude-haiku-5-5", 40))
        a = self.ns(plan="chatgpt-plus")
        resolve_plan(a)
        self.assertEqual((a.provider, a.model, a.budget), ("codex-cli", "gpt-6-astra", 25))
        a = self.ns(plan="chatgpt-free")
        resolve_plan(a)
        self.assertEqual((a.provider, a.model, a.budget), ("codex-cli", "default", 10))     # Astra may not be on Free

    def test_your_tool_wins(self):
        a = self.ns(plan="claude-max", provider="codex-cli")
        resolve_plan(a)
        self.assertEqual((a.provider, a.model, a.budget), ("codex-cli", None, 50))   # no Claude model for Codex

    def test_no_plan(self):
        a = self.ns()
        self.assertEqual(resolve_plan(a), {})
        self.assertEqual((a.provider, a.budget), ("auto", 30))
        with self.assertRaises(ValueError):
            plan_settings("claude-ultra")

    def test_every_plan_is_a_subscription(self):
        for key, p in PLANS.items():
            self.assertIn(p["provider"], ("claude-cli", "codex-cli"), key)
            self.assertTrue(10 <= p["budget"] <= 80, key)        # inside the page's slider


class DefaultsTest(unittest.TestCase):
    """Opus 5.5 / GPT-6 Astra at high effort unless you say otherwise; "default" = the tool's own; resume unchanged."""

    def setUp(self):
        self.saved = dict(os.environ)
        for k in ("TASTECAL_MODEL", "TASTECAL_EFFORT"):
            os.environ.pop(k, None)
        self.dir = tempfile.mkdtemp()
        os.environ["CLAUDE_BIN"] = script(self.dir, "claude", FAKE_CLAUDE)
        os.environ["CODEX_BIN"] = script(self.dir, "codex", FAKE_CODEX)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def test_defaults(self):
        llm = make_llm(Config(provider="claude-cli", cache_dir=None), None)
        self.assertEqual((llm.model, llm.effort), ("claude-opus-5-5", "high"))
        self.assertIn("--effort", llm._command("S", True))
        llm = make_llm(Config(provider="codex-cli", cache_dir=None), None)
        self.assertEqual((llm.model, llm.effort), ("gpt-6-astra", "high"))
        cfg = Config(provider="anthropic", cache_dir=None)
        from tastecal.core.config import resolve_choices
        resolve_choices(cfg)
        self.assertEqual((cfg.resolved_model(), cfg.effort), ("claude-opus-5-5", "high"))
        cfg = Config(provider="openai", model="deepseek-chat", cache_dir=None)
        resolve_choices(cfg)
        self.assertEqual(cfg.effort, "")                 # an older chat model gets no effort it cannot take

    def test_tool_default_on_request(self):
        llm = make_llm(Config(provider="claude-cli", model="default", effort="default", cache_dir=None), None)
        self.assertEqual((llm.model, llm.effort), ("", ""))
        self.assertNotIn("--model", llm._command("S", True))
        self.assertNotIn("--effort", llm._command("S", True))

    def test_resume_keeps_the_old_cache_keys(self):
        # EmbodiedEvo ran as model "opus" with no effort; its resume asks for "opus" and "default".
        llm = make_llm(Config(provider="claude-cli", model="opus", effort="default", cache_dir=None), None)

        class Old(LLM):
            name = "claude-cli:opus"
        self.assertEqual(llm._key("s", "p"), Old()._key("s", "p"))

    def test_resolved_once(self):
        cfg = Config(provider="claude-cli", model="default", cache_dir=None)
        make_llm(cfg, None)
        make_llm(cfg, None)
        self.assertEqual(cfg.model, "")                  # a second make_llm does not turn "default" into Opus

    def test_page_records_what_runs(self):
        req = clean_request({"seed": "x", "provider": "claude-cli"})
        self.assertEqual((req["model"], req["effort"]), ("claude-opus-5-5", "high"))
        req = clean_request({"seed": "x", "provider": "codex-cli", "model": "default", "effort": "default"})
        self.assertEqual((req["model"], req["effort"]), ("default", "default"))


class KeyTextTest(unittest.TestCase):
    """Keys pasted with curly quotes (TextEdit), full-width characters (Chinese input) or stray spaces still work."""

    def test_clean_secret(self):
        from tastecal.core.config import clean_secret
        for raw in ("“abc123XYZ”", "‘abc123XYZ’", '"abc123XYZ"', "  abc123XYZ\n", "ａｂｃ１２３ＸＹＺ", "「abc123XYZ」",
                    "abc123\u200bXYZ", "\ufeffabc123XYZ", "abc123XYZ\u3000", "＂abc123XYZ＂"):
            self.assertEqual(clean_secret(raw), "abc123XYZ", repr(raw))
        self.assertEqual(clean_secret("sk-ant-api03-a_b-C"), "sk-ant-api03-a_b-C")
        self.assertEqual(clean_secret(None), "")

    def test_environment_and_config(self):
        from tastecal.core.config import clean_env
        env = {"S2_API_KEY": "“k3y”", "GITHUB_TOKEN": "ok", "HOME": "“left alone”"}
        self.assertEqual(clean_env(env), ["S2_API_KEY"])
        self.assertEqual(env, {"S2_API_KEY": "k3y", "GITHUB_TOKEN": "ok", "HOME": "“left alone”"})
        saved = os.environ.get("S2_API_KEY")
        os.environ["S2_API_KEY"] = "“k3y”"
        try:
            self.assertEqual(Config().s2_api_key, "k3y")
        finally:
            if saved is None:
                os.environ.pop("S2_API_KEY", None)
            else:
                os.environ["S2_API_KEY"] = saved


class PageTest(unittest.TestCase):
    def test_state_and_request(self):
        st = providers_state()
        self.assertEqual({p["key"] for p in st["plans"]}, set(PLANS))
        self.assertIn("s2_key", st)
        self.assertIn("openalex_key", st)                               # the page shows both keys
        self.assertEqual(clean_request({"seed": "x", "provider": "claude-cli", "plan": "claude-pro"})["plan"], "claude-pro")
        self.assertEqual(clean_request({"seed": "x", "provider": "claude-cli", "plan": "nope"})["plan"], "")

    def test_a_key_saved_with_setx_counts_on_windows(self):
        """setx saves a key for windows opened later; one opened before (or a tab of a terminal or editor that was
        already running) does not have it, so it is read from where setx saved it."""
        import types
        from unittest import mock
        from tastecal.core import config
        reg = types.ModuleType("winreg")
        reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE, reg.REG_SZ, reg.REG_EXPAND_SZ = 1, 2, 1, 2
        saved = {(1, "Environment"): {"OPENALEX_API_KEY": (" abc123 ", 1)}}

        class Key:
            def __init__(self, root, path):
                self.values = saved.get((root, path))

            def __enter__(self):
                if self.values is None:
                    raise OSError("no such key")
                return self

            def __exit__(self, *a):
                return False

        def query(k, name):
            if name not in k.values:
                raise OSError("no such value")
            return k.values[name]
        reg.OpenKey, reg.QueryValueEx = Key, query
        env = {k: v for k, v in os.environ.items() if k not in ("OPENALEX_API_KEY", "S2_API_KEY")}
        with mock.patch.dict(sys.modules, {"winreg": reg}), mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(config.os, "name", "nt"):
            self.assertEqual(config.Config().openalex_api_key, "abc123")
            self.assertEqual(config.env_value("S2_API_KEY"), "")
            st = providers_state()
            self.assertEqual((st["openalex_key"], st["s2_key"], st["windows"]), (True, False, True))
            os.environ["OPENALEX_API_KEY"] = "from-this-window"
            self.assertEqual(config.env_value("OPENALEX_API_KEY"), "from-this-window")   # the window's own wins
        with mock.patch.dict(sys.modules, {"winreg": reg}), mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config.env_value("OPENALEX_API_KEY"), "")         # elsewhere only the environment

    def test_waiting_stage(self):
        today = dt.date.today().isoformat()
        lines = ["12:00 tastecal.gates: reading A",
                 f"12:01 tastecal.llm: plan usage limit reached; waiting until {today} 15:01 for it to reset, then continuing."]
        self.assertEqual(stage(lines), "Waiting for your plan's usage limit to reset · until 15:01")
        lines[-1] = lines[-1].replace(today, "2099-01-02")
        self.assertEqual(stage(lines), "Waiting for your plan's usage limit to reset · until 01-02 15:01")
        self.assertEqual(stage(lines + ["15:02 tastecal.gates: reading B"]), "Reading papers · 2 read")

    def test_billed_to(self):
        d = tempfile.mkdtemp()
        for line, want in (("Claude Code is billing your Claude plan (the account Claude Code is signed in to)", "plan"),
                           ("Claude Code is billing an API key (ANTHROPIC_API_KEY), not your Claude plan", "api key"),
                           ("Codex is billing your ChatGPT plan (the account Codex is signed in to)", "plan"),
                           ("Codex is billing an API key, not your ChatGPT plan", "api key")):
            with open(os.path.join(d, "console.log"), "w") as f:
                f.write("10:00 tastecal.llm: " + line + "\n")
            self.assertEqual(billed_to(d), want, line)


if __name__ == "__main__":
    unittest.main()
