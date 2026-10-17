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
        self.assertIn("Trace the problems behind a paper", self.get("/"))
        st = json.loads(self.get("/api/state"))
        self.assertIn("models", st["providers"])
        self.assertTrue(any(p["name"] == "practitioner" for p in st["profiles"]))
        self.assertEqual([r["id"] for r in st["runs"]], ["demo"])
        self.assertIn("demo", self.get("/examples/demo/report.html"))

    def test_run_writes_taste_and_lists_the_report(self):
        code, res = self.post("/api/runs", {"seed": "Attention Is All You Need", "provider": "openai", "key": "sk-test",
                                            "budget": 20, "language": "zh-CN", "taste_name": "Mine Test",
                                            "taste": "I like simple ideas.",
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
        self.assertEqual(row["facts"]["treasures"], 2)
        self.assertEqual(runs[0]["id"], rid)                       # newest run first, examples last
        folder = os.path.join(self.base, "runs", rid)
        name, text, _ = load_profile(os.path.join(folder, "taste.md"))
        self.assertEqual(name, "Mine Test")
        self.assertIn("## Papers I liked\n- ResNet (my score 0.90): simple and general", text)
        self.assertIn("## Papers I disliked", text)
        with open(os.path.join(self.base, "taste.json")) as f:
            store = json.load(f)
        self.assertEqual(store["default"], "mine-test")
        self.assertEqual(store["profiles"]["mine-test"]["taste"], "I like simple ideas.")
        self.assertEqual(store["profiles"]["mine-test"]["papers"][0], {"ref": "ResNet", "score": 0.9, "comment": "simple and general"})
        st = json.loads(self.get("/api/state"))
        mine = next(p for p in st["profiles"] if p["name"] == "mine-test")
        self.assertTrue(mine["default"])
        with open(os.path.join(folder, "request.json")) as f:
            req = json.load(f)
        self.assertNotIn("key", req)                               # keys are never written
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
        code, res = self.post("/api/profiles", {"name": "My Driving", "taste": "Plain ideas.",
                                                "papers": [{"ref": "ResNet", "score": 0.9, "comment": "simple"},
                                                           {"ref": "Hype paper", "score": 0.1, "comment": "decoration"}]})
        self.assertEqual(code, 200, res)
        mine = next(p for p in res["profiles"] if p["name"] == "my-driving")
        self.assertEqual(mine["text"], "Plain ideas.")
        self.assertEqual([(p["ref"], p["score"]) for p in mine["papers"]], [("ResNet", 0.9), ("Hype paper", 0.1)])
        prac = next(p for p in res["profiles"] if p["name"] == "practitioner")
        self.assertTrue(prac["papers"] and all(p["score"] == 0.8 for p in prac["papers"]))
        self.assertNotIn("## Papers I liked", prac["text"])
        code, res = self.post("/api/runs", {"seed": "x", "provider": "openai", "key": "k", "budget": 10, "effort": "xhigh"})
        req = json.load(open(os.path.join(self.base, "runs", res["id"], "request.json")))
        self.assertEqual(req["effort"], "xhigh")
        from tastecal.app.serve import Runner
        cmd = Runner.default_command(dict(req, model="claude-opus-5-5"), "out", "taste.md")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "xhigh")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-opus-5-5")

    def test_helpers(self):
        self.assertEqual(clean_request({"seed": " a  b ", "provider": "anthropic", "budget": "40"})["seed"], "a b")
        with self.assertRaises(ValueError):
            clean_request({"seed": "a", "provider": "anthropic", "budget": 500})
        self.assertIn("Papers I noted", build_profile("", "", [{"ref": "X", "score": None, "comment": ""}]))
        self.assertEqual(stage(["12:00 tastecal.gates: reading A", "12:01 tastecal.gates: reading B"]), "Reading papers · 2 read")
        self.assertEqual(stage(["12:00 deepanalyze.gates: reading A"]), "Reading papers · 1 read")  # older logs


if __name__ == "__main__":
    unittest.main()
