"""Resume: downloads replay from the cache, model calls survive a dropped connection, and the page can continue a run."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.http import Http, HttpError  # noqa: E402
from tastecal.core.llm import LLM, LLMError  # noqa: E402
from tastecal.app.serve import awake, make_server, own_group  # noqa: E402


class ReplayTest(unittest.TestCase):
    def test_replays_the_cache_then_goes_live_where_it_stopped(self):
        h = Http(tempfile.mkdtemp(), fresh_days=1)
        h.clock = lambda: 2e9
        h._cache_put("GET https://api.example.org/search?q=1", {"ok": 1})
        h.clock = lambda: 2e9 + 30 * 86400            # a month later: expired, but a replay still uses it
        h.replay = True
        h._send = lambda *a: self.fail("a cached download must not be fetched again")
        self.assertEqual(h.get_json("https://api.example.org/search", {"q": 1}), {"ok": 1})
        self.assertTrue(h.replay)
        h._send = lambda *a: b'{"new": 2}'           # where the earlier attempt stopped: fetched live
        self.assertEqual(h.get_json("https://api.example.org/never-fetched"), {"new": 2})
        self.assertFalse(h.replay)                   # and the run goes on live from here


class OwnGroupTest(unittest.TestCase):
    def test_runs_leave_the_server_console(self):
        if os.name == "nt":
            self.assertTrue(own_group() & 0x200)          # CREATE_NEW_PROCESS_GROUP: Ctrl+C stays with the server
        else:
            self.assertEqual(own_group(), 0)               # start_new_session covers it


class Flaky(LLM):
    name = "flaky:m"
    WAITS = (0, 0, 0)

    def __init__(self, errors):
        super().__init__(None)
        self.errors = list(errors)
        self.tries = 0

    def _complete(self, system, prompt, max_tokens):
        self.tries += 1
        if self.errors:
            raise LLMError(self.errors.pop(0))
        return "fine"


class RetryTest(unittest.TestCase):
    def test_sleep_and_network_are_waited_out(self):
        llm = Flaky(["claude -p reported an error: API Error: Your computer went to sleep mid-response.",
                     "claude -p failed (1): Connection error: ECONNRESET"])
        with self.assertLogs("tastecal.llm", "WARNING"):
            self.assertEqual(llm.complete("s", "p"), "fine")
        self.assertEqual(llm.tries, 3)

    def test_limits_and_login_are_not_retried(self):
        for msg in ("claude -p reported an error: Claude usage limit reached. Your limit will reset at 9pm",
                    "Codex is not signed in to ChatGPT.", "claude -p failed (1): something else entirely"):
            llm = Flaky([msg])
            with self.assertRaises(LLMError):
                llm.complete("s", "p")
            self.assertEqual(llm.tries, 1)

    def test_gives_up_eventually(self):
        llm = Flaky(["network down"] * 10)
        with self.assertLogs("tastecal.llm", "WARNING"), self.assertRaises(LLMError):
            llm.complete("s", "p")
        self.assertEqual(llm.tries, 4)


FAKE_RESUME = ("import json,os,sys,time; out=sys.argv[-1]; time.sleep(0.2); "
               "open(os.path.join(out,'report.html'),'w').write('<p>done</p>'); print('resumed fine')")


class PageResumeTest(unittest.TestCase):
    def test_resume_button(self):
        base = tempfile.mkdtemp()
        run = os.path.join(base, "runs", "r1")
        os.makedirs(run)
        with open(os.path.join(run, "request.json"), "w") as f:
            json.dump({"seed": "x", "provider": "claude-cli", "model": "opus", "budget": 30, "language": "zh-CN"}, f)
        with open(os.path.join(run, "status.json"), "w") as f:
            json.dump({"state": "failed", "pid": 1, "started": "2026-10-15T15:48:31", "returncode": 1}, f)
        with open(os.path.join(run, "console.log"), "w") as f:
            f.write("18:39:02 tastecal: something failed\n")
        srv = make_server(port=0, base=base, resume_command=lambda out: [sys.executable, "-c", FAKE_RESUME, out])
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, body):
            req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-TasteCal": "1"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(post("/api/runs/r1/resume", {})[0], 200)
            for _ in range(50):
                st = json.load(open(os.path.join(run, "status.json")))
                if st.get("state") != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(st["state"], "done")
            self.assertEqual(st["started"], "2026-10-15T15:48:31")        # the original start time is kept
            log = open(os.path.join(run, "console.log")).read()
            self.assertIn("something failed", log)                         # appended, not overwritten
            self.assertIn("---- resumed ----", log)
            self.assertIn("resumed fine", log)
            self.assertEqual(post("/api/runs/nope/resume", {})[0], 404)
        finally:
            srv.shutdown()

    def test_awake_only_on_mac(self):
        cmd = ["python3", "-m", "tastecal", "run"]
        self.assertEqual(awake(cmd)[-4:], cmd)
        if sys.platform != "darwin":
            self.assertEqual(awake(cmd), cmd)


class ResumeCommandTest(unittest.TestCase):
    def test_same_settings(self):
        from tastecal import cli
        run = tempfile.mkdtemp()
        with open(os.path.join(run, "request.json"), "w") as f:
            json.dump({"seed": "EmbodiedEvo", "provider": "claude-cli", "model": "opus", "budget": 80,
                       "language": "zh-CN"}, f)
        open(os.path.join(run, "taste.md"), "w").write("# This report\n")
        seen = {}
        real = cli.main
        cli.main = lambda argv=None: seen.setdefault("argv", argv) and 0
        try:
            os.environ.pop("TASTECAL_SERVED", None)
            cli.cmd_resume(type("A", (), {"folder": run})())
        finally:
            cli.main = real
        a = seen["argv"]
        self.assertEqual(a[:2], ["run", "EmbodiedEvo"])
        for flag, val in (("--budget", "80"), ("--provider", "claude-cli"), ("--model", "opus"),
                          ("--language", "zh-CN"), ("--out", run), ("--taste", os.path.join(run, "taste.md"))):
            self.assertEqual(a[a.index(flag) + 1], val)
        self.assertIn("--resume", a)
        # No effort then means the model's own now too ("default"), not the new default high: the saved answers match.
        self.assertEqual(a[a.index("--effort") + 1], "default")
        st = json.load(open(os.path.join(run, "status.json")))
        self.assertIn(st["state"], ("done", "failed"))


if __name__ == "__main__":
    unittest.main()


class VersionTest(unittest.TestCase):
    def test_page_and_server_agree(self):
        from tastecal.app.serve import API_VERSION, APP
        page = open(APP, encoding="utf-8").read()
        self.assertIn(f"const PAGE_API = {API_VERSION};", page)
        base = tempfile.mkdtemp()
        srv = make_server(port=0, base=base)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}"
            with urllib.request.urlopen(url + "/api/state") as r:
                self.assertEqual(json.loads(r.read())["api"], API_VERSION)
            with urllib.request.urlopen(url + "/") as r:
                self.assertIn(b"PAGE_API", r.read())
        finally:
            srv.shutdown()


class WindowsProcessTest(unittest.TestCase):
    """On Windows os.kill(pid, 0) terminates the process, so the page must never use it to look at a run."""

    def setUp(self):
        from tastecal.app import serve
        self.serve = serve
        self.saved = (serve.os.name, serve._windows_pid_alive, serve._windows_image, serve.os.kill, serve.subprocess.run)
        serve.os.kill = lambda *a: self.fail("os.kill must not be used on Windows")

    def tearDown(self):
        s = self.serve
        s.os.name, s._windows_pid_alive, s._windows_image, s.os.kill, s.subprocess.run = self.saved

    def test_alive_check_does_not_kill(self):
        s = self.serve
        s.os.name = "nt"
        s._windows_pid_alive = lambda pid: True
        s._windows_image = lambda pid: "python.exe"
        self.assertTrue(s.run_alive(1234))
        s._windows_image = lambda pid: "chrome.exe"         # a reused pid
        self.assertFalse(s.run_alive(1234))
        s._windows_pid_alive = lambda pid: False
        self.assertFalse(s.run_alive(1234))

    def test_stop_ends_the_whole_tree(self):
        s = self.serve
        s.os.name = "nt"
        seen = []
        s.subprocess.run = lambda cmd, **kw: seen.append(cmd)
        s._terminate(4321)
        self.assertEqual(seen, [["taskkill", "/PID", "4321", "/T", "/F"]])
