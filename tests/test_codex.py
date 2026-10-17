"""The ChatGPT-login backend: `codex exec` is called read-only, in an empty folder, and its last message is the answer."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.core.config import Config  # noqa: E402
from tastecal.core.llm import CodexCLILLM, LLMError, make_llm  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
log = os.environ["FAKE_CODEX_LOG"]
json.dump({"args": args, "cwd": os.getcwd(), "prompt": prompt, "files": os.listdir(".")}, open(log, "w"))
if os.environ.get("FAKE_CODEX_MODE") == "logout":
    sys.stderr.write("Error: not logged in. Run codex login\n"); sys.exit(1)
out = args[args.index("-o") + 1]
open(out, "w").write('{"ok": true}')
print("some progress output")
'''


class CodexTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.bin = os.path.join(self.dir, "codex")
        with open(self.bin, "w") as f:
            f.write(FAKE.replace("#!/usr/bin/env python3", "#!" + sys.executable))
        os.chmod(self.bin, os.stat(self.bin).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.dir, "call.json")
        os.environ.update(CODEX_BIN=self.bin, FAKE_CODEX_LOG=self.log)
        os.environ.pop("FAKE_CODEX_MODE", None)

    def tearDown(self):
        for k in ("CODEX_BIN", "FAKE_CODEX_LOG", "FAKE_CODEX_MODE"):
            os.environ.pop(k, None)

    def test_call(self):
        llm = make_llm(Config(provider="codex-cli", model="gpt-6-astra", cache_dir=None, effort="max"), None)
        self.assertIsInstance(llm, CodexCLILLM)
        llm.system_note = "Write in English."
        self.assertEqual(llm.json("SYSTEM", "TASK: x\nhello"), {"ok": True})
        call = json.load(open(self.log))
        a = call["args"]
        self.assertEqual(a[0], "exec")
        for flag in ("--skip-git-repo-check", "--ephemeral", "-o"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--sandbox") + 1], "read-only")
        self.assertEqual(a[a.index("-m") + 1], "gpt-6-astra")
        self.assertEqual(a[-1], "-")
        self.assertEqual(a[a.index("-c") + 1], 'model_reasoning_effort="xhigh"')      # max maps to Codex's highest
        self.assertTrue(call["prompt"].startswith("SYSTEM"))
        self.assertIn("Do not run commands", call["prompt"])
        self.assertIn("Write in English.", call["prompt"])
        self.assertEqual(call["files"], [])                     # an empty folder, not the user's project

    def test_not_logged_in(self):
        os.environ["FAKE_CODEX_MODE"] = "logout"
        llm = make_llm(Config(provider="codex-cli", cache_dir=None), None)
        with self.assertRaises(LLMError) as e:
            llm.complete("S", "TASK: x")
        self.assertIn("codex login", str(e.exception))

    def test_missing_binary(self):
        os.environ["CODEX_BIN"] = os.path.join(self.dir, "nope")
        with self.assertRaises(LLMError):
            make_llm(Config(provider="codex-cli", cache_dir=None), None)


if __name__ == "__main__":
    unittest.main()
