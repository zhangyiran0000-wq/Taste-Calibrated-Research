"""The local web page: the form starts a run with the right options, and reports are listed and served."""
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

from tastecal.app.serve import build_profile, clean_request, make_server, stage  # noqa: E402
from tastecal.taste.profiles import load_profile  # noqa: E402

FAKE = ("import json,os,sys,time; out=sys.argv[sys.argv.index('--out')+1]; time.sleep(0.3); "
        "print('12:00:00 tastecal.grow: round 1: +3 items'); "
        "json.dump({'meta':{'seed':'s','language':'en'},'nodes':[{'id':'s','title':'Seed Title','short':'Seed'}],"
        "'threads':[],'gates':{'folded':1,'counts':{'treasure':2}}},open(os.path.join(out,'graph.json'),'w')); "
        "open(os.path.join(out,'report.html'),'w').write('<p>report</p>'); "
        "open(os.path.join(out,'argv.json'),'w').write(json.dumps(sys.argv))")


class ServeTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "examples", "demo"))
        with open(os.path.join(self.base, "examples", "demo", "graph.json"), "w") as f:
            json.dump({"meta": {"seed": "d"}, "nodes": [{"id": "d", "title": "Demo", "short": "Demo"}]}, f)
        with open(os.path.join(self.base, "examples", "demo", "report.html"), "w") as f:
            f.write("<p>demo</p>")
        cmd = lambda req, out, taste: [sys.executable, "-c", FAKE, "--out", out, "--taste", taste,
                                       "--provider", req["provider"], "--budget", str(req["budget"])]
        self.srv = make_server(port=0, base=self.base, command=cmd)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as r:
            return r.read().decode("utf-8")

    def post(self, path, body, header=True):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-TasteCal": "1"} if header else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_page_and_state(self):
        page = self.get("/")
        self.assertIn("Trace the problems behind a paper", page)
        for s in ("Must-read papers", "Load a saved taste", "Save this taste", "Attention Is All He Needs",
                  "一个小领域里的应用，看起来还算成功。", "An application in a narrow area"):
            self.assertIn(s, page)                                       # examples in both report languages
        self.assertNotIn("p.default)", page)                             # nothing fills the page by itself
        st = json.loads(self.get("/api/state"))
        self.assertIn("models", st["providers"])
        self.assertEqual(st["profiles"], [])                              # no tastes shipped with the tool
        self.assertNotIn("words", st)                                     # no taste in words: only rated papers
        self.assertNotIn("Describe it in words", page)
        self.assertEqual([r["id"] for r in st["runs"]], ["demo"])
        self.assertIn("demo", self.get("/examples/demo/report.html"))

    def test_run_writes_taste_and_lists_the_report(self):
        code, res = self.post("/api/runs", {"seed": "Attention Is All You Need", "provider": "openai", "key": "sk-test",
                                            "budget": 20, "language": "zh-CN", "taste_name": "Mine Test",
                                            "taste": "I like simple ideas.",       # an older page's words: dropped
                                            "papers": [{"ref": "ResNet", "score": 0.9, "comment": "simple and general"},
                                                       {"ref": "Some paper", "score": 0.1, "comment": "decoration"},
                                                       {"ref": "", "score": 0.5}]})
        self.assertEqual(code, 200, res)
        rid = res["id"]
        for _ in range(50):
            runs = json.loads(self.get("/api/runs"))
            row = next(r for r in runs if r["id"] == rid)
            if row["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["title"], "Seed Title")
        self.assertEqual(row["facts"], {"works": 1, "threads": 0})            # no "to read" count: the notes are not shown
        self.assertEqual(runs[0]["id"], rid)                       # newest run first, examples last
        folder = os.path.join(self.base, "runs", rid)
        name, text, _ = load_profile(os.path.join(folder, "taste.md"))
        self.assertEqual(name, "Mine Test")
        self.assertIn("## Papers I liked\n- ResNet (my score 0.90): simple and general", text)
        self.assertIn("## Papers I disliked", text)
        self.assertNotIn("I like simple ideas.", text)
        # a run never changes taste.json: only "Save this taste" does
        self.assertFalse(os.path.exists(os.path.join(self.base, "taste.json")))
        with open(os.path.join(folder, "request.json")) as f:
            req = json.load(f)
        self.assertNotIn("key", req)                               # keys are never written
        self.assertNotIn("taste", req)
        self.assertIn("report", self.get(f"/runs/{rid}/report.html"))
        self.assertIn("round 1", " ".join(json.loads(self.get(f"/api/runs/{rid}/log"))["lines"]))

    def test_guards(self):
        self.assertEqual(self.post("/api/runs", {"seed": "x", "provider": "openai"}, header=False)[0], 403)
        self.assertEqual(self.post("/api/runs", {"seed": "", "provider": "openai", "key": "k"})[0], 400)
        self.assertEqual(self.post("/api/runs", {"seed": "x", "provider": "other"})[0], 400)
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/runs/../../etc/passwd/report.html")

    def test_delete(self):
        code, res = self.post("/api/runs", {"seed": "To delete", "provider": "openai", "key": "k", "budget": 10})
        rid = res["id"]
        for _ in range(50):
            if next(r for r in json.loads(self.get("/api/runs")) if r["id"] == rid)["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(self.post(f"/api/runs/{rid}/delete", {})[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.base, "runs", rid)))
        self.assertNotIn(rid, [r["id"] for r in json.loads(self.get("/api/runs"))])
        self.assertEqual(self.post("/api/runs/demo/delete", {})[0], 404)          # examples cannot be deleted
        self.assertTrue(os.path.exists(os.path.join(self.base, "examples", "demo")))

    def test_codex_sign_in(self):
        import stat
        fake = os.path.join(self.base, "codex")
        flag = os.path.join(self.base, "signed")
        with open(fake, "w") as f:
            f.write(f"""#!{sys.executable}
import os, sys
if sys.argv[1:] == ["login", "status"]:
    print("Logged in using ChatGPT" if os.path.exists({flag!r}) else "Not logged in"); sys.exit(0 if os.path.exists({flag!r}) else 1)
if sys.argv[1:] == ["login"]:
    print("Starting local login server on http://localhost:1455. If your browser did not open, navigate to this URL: https://auth.openai.com/oauth/authorize?x=1", flush=True)
    open({flag!r}, "w").write("ok")
""")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        os.environ["CODEX_BIN"] = fake
        try:
            st = json.loads(self.get("/api/state"))["providers"]["codex-cli"]
            self.assertEqual(st, {"available": True, "signed_in": False, "auth": "none"})
            code, res = self.post("/api/runs", {"seed": "x", "provider": "codex-cli", "budget": 10})
            self.assertEqual(code, 400)
            self.assertTrue(res.get("need_login"))
            self.assertEqual(self.post("/api/codex/login", {})[0], 200)
            for _ in range(50):
                st = json.loads(self.get("/api/codex/status"))
                if st["signed_in"] and st["url"]:
                    break
                time.sleep(0.1)
            self.assertTrue(st["signed_in"])
            self.assertTrue(st["url"].startswith("https://auth.openai.com/"))
            self.assertEqual(self.post("/api/runs", {"seed": "x", "provider": "codex-cli", "budget": 10})[0], 200)
        finally:
            os.environ.pop("CODEX_BIN", None)

    def test_templates_and_effort(self):
        code, res = self.post("/api/profiles", {"name": "My Driving",
                                                "papers": [{"ref": "ResNet", "score": 0.9, "comment": "simple"},
                                                           {"ref": "Hype paper", "score": 0.1, "comment": "decoration"}]})
        self.assertEqual(code, 200, res)
        mine = next(p for p in res["profiles"] if p["name"] == "my-driving")
        self.assertTrue(mine["saved"])                                   # when it was saved, for the list
        self.assertNotIn("text", mine)
        # one taste per name: the same name again is replaced only when the page confirms it
        code, again = self.post("/api/profiles", {"name": "my driving", "papers": []})
        self.assertEqual((code, again["exists"], again["title"]), (409, True, "My Driving"))
        self.assertEqual(len(json.load(open(os.path.join(self.base, "taste.json")))["profiles"]["my-driving"]["papers"]), 2)
        code, res = self.post("/api/profiles", {"name": "My Driving", "overwrite": True, "taste": "Old page words.",
                                                "papers": [{"ref": "ResNet", "score": 0.8}]})
        mine = next(p for p in res["profiles"] if p["name"] == "my-driving")
        self.assertEqual([(p["ref"], p["score"]) for p in mine["papers"]], [("ResNet", 0.8)])
        self.assertEqual(sorted(json.load(open(os.path.join(self.base, "taste.json")))["profiles"]["my-driving"]),
                         ["papers", "saved", "title"])                    # no words, no principles
        code, res = self.post("/api/runs", {"seed": "x", "provider": "openai", "key": "k", "budget": 10, "effort": "xhigh"})
        req = json.load(open(os.path.join(self.base, "runs", res["id"], "request.json")))
        self.assertEqual(req["effort"], "xhigh")
        from tastecal.app.serve import Runner
        cmd = Runner.default_command(dict(req, model="claude-opus-5-5"), "out", "taste.md")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "xhigh")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-opus-5-5")
        self.assertNotIn("--must", cmd)

    def test_import_a_ratings_file(self):
        import base64
        rows = [{"paper": "Attention is all you need", "score": 0.9, "reason": "founding work"},
                {"paper": "Some benchmark", "score": "0.3", "reason": "narrow"}]
        b64 = lambda raw: "data:application/json;base64," + base64.b64encode(raw).decode()  # noqa: E731
        code, res = self.post("/api/ratings/import", {"name": "ratings.json", "data": b64(json.dumps(rows).encode())})
        self.assertEqual(code, 200, res)
        self.assertEqual(res["papers"], [{"ref": "Attention is all you need", "score": 0.9, "comment": "founding work"},
                                         {"ref": "Some benchmark", "score": 0.3, "comment": "narrow"}])
        code, res = self.post("/api/ratings/import", {"name": "list.txt", "data": b64("ResNet | 0.8 | simple".encode())})
        self.assertEqual((code, res["papers"][0]["ref"], res["papers"][0]["score"]), (200, "ResNet", 0.8))
        self.assertEqual(self.post("/api/ratings/import", {"name": "x.exe", "data": b64(b"x")})[0], 400)
        self.assertEqual(self.post("/api/ratings/import", {"name": "bad.json", "data": b64(b"{nope")})[0], 400)

    def test_a_loaded_taste_is_saved_back_under_its_own_key(self):
        with open(os.path.join(self.base, "taste.json"), "w", encoding="utf-8") as f:
            json.dump({"default": "mine", "profiles": {"mine": {"title": "Mine (draft)", "taste": "My words.", "papers": [],
                       "principles": [{"id": "P1", "sign": "+", "text": "opens a new field", "from": []}]}}}, f)
        # by its title, the same taste is found (not a new "mine-draft"), and replaced only when confirmed
        code, res = self.post("/api/profiles", {"name": "Mine (draft)", "papers": [{"ref": "ResNet", "score": 0.9}]})
        self.assertEqual((code, res["exists"]), (409, True))
        code, res = self.post("/api/profiles", {"name": "Mine (draft)", "key": "mine", "overwrite": True,
                                                "papers": [{"ref": "ResNet", "score": 0.9}]})
        self.assertEqual((code, res["saved"]), (200, "mine"))
        store = json.load(open(os.path.join(self.base, "taste.json")))
        self.assertEqual(sorted(store["profiles"]), ["mine"])
        self.assertNotIn("principles", store["profiles"]["mine"])        # older words and principles are dropped
        self.assertNotIn("taste", store["profiles"]["mine"])
        # a run made with it gets its rated papers, and the report's ratings go back to it
        code, res = self.post("/api/runs", {"seed": "x", "provider": "openai", "key": "k", "budget": 10,
                                            "taste_name": "Mine (draft)", "taste_key": "mine",
                                            "papers": [{"ref": "ResNet", "score": 0.9}]})
        self.assertEqual(code, 200, res)
        with open(os.path.join(self.base, "runs", res["id"], "taste.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("- ResNet (my score 0.90)", md)
        self.assertNotIn("opens a new field", md)
        self.assertEqual(self.srv.RequestHandlerClass.runner.taste_name("runs", res["id"]), "mine")

    def test_ratings_files_in_the_folder_load_directly(self):
        rows = [{"paper": f"Paper {i}", "score": i / 10, "reason": "r"} for i in range(1, 12)]
        with open(os.path.join(self.base, "ratings.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f)
        with open(os.path.join(self.base, "notes.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f)                                         # not a ratings file: not offered
        files = json.loads(self.get("/api/state"))["files"]
        self.assertEqual([(f["file"], f["papers"]) for f in files], [("ratings.json", 11)])
        code, res = self.post("/api/ratings/file", {"file": "ratings.json"})
        self.assertEqual((code, len(res["papers"]), res["papers"][0]), (200, 11, {"ref": "Paper 1", "score": 0.1, "comment": "r"}))
        for bad in ("notes.json", "../ratings.json", "/etc/passwd"):
            self.assertEqual(self.post("/api/ratings/file", {"file": bad})[0], 404, bad)

    def test_the_taste_calibration_follows_a_page_run(self):
        from tastecal import cli
        from tastecal.app.serve import Runner
        req = clean_request({"seed": "x", "provider": "anthropic"})
        self.assertTrue(req["fit"])
        self.assertIn("--fit", Runner.default_command(dict(req, model=""), "out", "taste.md"))
        three = build_profile("Mine", [{"ref": f"P{i}", "score": 0.5, "comment": ""} for i in range(3)])
        two = build_profile("Mine", [{"ref": "P1", "score": 0.5, "comment": ""}, {"ref": "P2", "score": None, "comment": ""},
                                         {"ref": "P3", "score": 0.4, "comment": ""}])
        self.assertEqual(cli.taste_fit_argv("g.json", "taste.md", three), (["fit", "g.json", "--taste", "taste.md"], 3))
        self.assertEqual(cli.taste_fit_argv("g.json", "taste.md", two), (None, 2))     # a paper without a score
        self.assertEqual(cli.taste_fit_argv("g.json", "", three)[0], None)
        self.assertEqual(stage(["08:00 tastecal: plain language: 3 texts", "08:01 tastecal: taste calibration: fitting your taste"]),
                         "Calibrating your taste")
        self.assertEqual(stage(["08:00 tastecal.fit: round 3"]), "Calibrating your taste")    # long after the first line
        # a calibration that fails leaves the lineage report and says how to run it again
        import logging
        from unittest import mock
        calls = []
        with mock.patch.object(cli, "main", lambda argv: calls.append(argv) or 1), \
                self.assertLogs("tastecal", "WARNING") as cm:
            self.assertEqual(cli.taste_fit_after("g.json", "taste.md", three, logging.getLogger("tastecal")), 1)
        self.assertEqual(calls, [["fit", "g.json", "--taste", "taste.md"]])
        self.assertIn("Run it again with: python -m tastecal fit g.json --taste taste.md", "\n".join(cm.output))
        # Resume asks for it again
        folder = os.path.join(self.base, "runs", "r1")
        os.makedirs(folder)
        with open(os.path.join(folder, "request.json"), "w") as f:
            json.dump(dict(req, budget=10), f)
        seen = []
        with mock.patch.object(cli, "main", lambda argv: seen.append(argv) or 0), mock.patch.dict(os.environ, {"TASTECAL_SERVED": "1"}):
            cli.cmd_resume(type("A", (), {"folder": folder})())
        self.assertIn("--fit", seen[0])

    def test_must_read_papers(self):
        req = clean_request({"seed": "x", "provider": "anthropic",
                             "must": ["  Attention Is All You Need ", "attention is all you need", "", "arXiv:1512.03385"]})
        self.assertEqual(req["must"], ["Attention Is All You Need", "arXiv:1512.03385"])     # trimmed, once each
        from tastecal.app.serve import MAX_MUST, Runner
        cmd = Runner.default_command(dict(req, model=""), "out", "taste.md")
        self.assertEqual([cmd[i + 1] for i, a in enumerate(cmd) if a == "--must"], req["must"])
        with self.assertRaises(ValueError):
            clean_request({"seed": "x", "provider": "anthropic", "must": [f"paper {i}" for i in range(MAX_MUST + 1)]})
        code, res = self.post("/api/runs", {"seed": "x", "provider": "openai", "key": "k", "budget": 10, "must": ["A paper"]})
        self.assertEqual(code, 200, res)
        self.assertEqual(json.load(open(os.path.join(self.base, "runs", res["id"], "request.json")))["must"], ["A paper"])

    def test_helpers(self):
        self.assertEqual(clean_request({"seed": " a  b ", "provider": "anthropic", "budget": "40"})["seed"], "a b")
        with self.assertRaises(ValueError):
            clean_request({"seed": "a", "provider": "anthropic", "budget": 500})
        self.assertIn("Papers I noted", build_profile("", [{"ref": "X", "score": None, "comment": ""}]))
        self.assertEqual(stage(["12:00 tastecal.gates: reading A", "12:01 tastecal.gates: reading B"]), "Reading papers · 2 read")
        self.assertEqual(stage(["12:00 deepanalyze.gates: reading A"]), "Reading papers · 1 read")  # older logs


if __name__ == "__main__":
    unittest.main()
