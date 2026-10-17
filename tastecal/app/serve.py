"""A small local web page for making reports: `python -m tastecal serve`.

It only starts `python -m tastecal run ...` in the background with the options you pick, and lists
the reports in ./runs (and ./examples) so you can open them. Nothing else: the language model writes
the report, and no code is changed.

  Seed            a title, arXiv link, DOI or Semantic Scholar id
  Model           Claude (API key or Claude Code login) or GPT (API key or ChatGPT login through Codex CLI),
                  and its version
  Max papers      the --budget of the run
  Taste           free text, plus papers you rated (title or link, a 0-1 score, a comment). Saved as the
                  run's taste profile (runs/<id>/taste.md); with a name it is also kept in ./taste.json, and the
                  default profile there fills the page in automatically next time
  Reports         every run with its status, its log, and a link to open the report

The server listens on 127.0.0.1 only. API keys typed into the page are passed to the run's process
and never written to disk. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.html")
PROVIDERS = ("anthropic", "openai", "claude-cli", "codex-cli")
LANGS = ("en", "zh-CN")
MODELS = {   # suggestions only (value, label); any model id the account supports can be typed
    "anthropic": [["claude-opus-5-5", "Opus 5.5 · recommended"], ["claude-sonnet-5-5", "Sonnet 5.5 · faster"],
                  ["claude-haiku-5-5", "Haiku 5.5 · fastest"], ["claude-fable-5-1", "Fable 5.1 · hardest reasoning"]],
    "claude-cli": [["claude-opus-5-5", "Opus 5.5 · recommended"], ["claude-sonnet-5-5", "Sonnet 5.5 · faster"],
                   ["claude-haiku-5-5", "Haiku 5.5 · fastest"], ["claude-fable-5-1", "Fable 5.1 · if your plan has it"]],
    "openai": [["gpt-6-astra", "GPT-6 Astra · most capable"], ["gpt-6.1-sol", "GPT-6.1 Sol"], ["gpt-6-luna", "GPT-6 Luna · fastest"]],
    "codex-cli": [["gpt-6-astra", "GPT-6 Astra · most capable"], ["gpt-6.1-sol", "GPT-6.1 Sol"], ["gpt-6-luna", "GPT-6 Luna · fastest"]],
}
EFFORTS = ("low", "medium", "high", "xhigh", "max", "default")
API_VERSION = 6          # bump when the page needs a new endpoint; the page warns when the server is older
GROUPS = ("runs", "examples")


def slug(text: str, n: int = 40) -> str:
    import unicodedata
    s = re.sub(r"https?://", "", unicodedata.normalize("NFKC", text or "")).lower()
    s = re.sub(r"[^a-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "-", s).strip("-")
    return (s[:n].strip("-") or "report")


from tastecal.taste.profiles import build_profile  # noqa: E402  (kept importable from here)


def clean_request(body: dict) -> dict:
    """Validate the form. Raises ValueError with a message for the page."""
    seed = " ".join(str(body.get("seed") or "").split())
    if not seed:
        raise ValueError("Give a seed paper: a title, link, DOI or id.")
    provider = body.get("provider")
    if provider not in PROVIDERS:
        raise ValueError("Pick Claude or GPT.")
    try:
        budget = int(body.get("budget") or 30)
    except (TypeError, ValueError):
        raise ValueError("Max papers must be a number.")
    if not 5 <= budget <= 100:
        raise ValueError("Max papers must be between 5 and 100.")
    lang = body.get("language") if body.get("language") in LANGS else "en"
    papers = []
    for p in body.get("papers") or []:
        if not isinstance(p, dict) or not str(p.get("ref") or "").strip():
            continue
        s = p.get("score")
        try:
            s = None if s in (None, "") else max(0.0, min(1.0, float(s)))
        except (TypeError, ValueError):
            s = None
        papers.append({"ref": str(p["ref"]).strip()[:400], "score": s, "comment": str(p.get("comment") or "").strip()[:800]})
    from tastecal.core.config import DEFAULT_EFFORT, DEFAULT_MODEL, PLANS
    # Record what the run will really use (not ""), so Resume asks for the same model and effort later.
    effort = body.get("effort") if body.get("effort") in EFFORTS else DEFAULT_EFFORT
    model = str(body.get("model") or "").strip()[:80] or DEFAULT_MODEL.get(provider, "")
    plan = body.get("plan") if body.get("plan") in PLANS else ""
    scope = " ".join(str(body.get("scope") or "").split())[:200]
    return {"seed": seed[:500], "scope": scope, "provider": provider, "plan": plan, "model": model, "effort": effort,
            "budget": budget, "language": lang, "taste_name": str(body.get("taste_name") or "").strip()[:60],
            "taste": str(body.get("taste") or "").strip()[:8000], "papers": papers[:40]}


class Runner:
    """Starts runs as child processes and reads their state back from the run folders."""

    def __init__(self, base: str = ".", runs_dir: str = "runs", command=None, resume_command=None):
        self.base = os.path.abspath(base)
        self.runs_dir = os.path.join(self.base, runs_dir)
        self.procs: Dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.command = command or self.default_command
        self.resume_command = resume_command or self.default_resume_command
        os.makedirs(self.runs_dir, exist_ok=True)

    # -- starting ---------------------------------------------------------------------------
    @staticmethod
    def default_command(req: dict, out: str, taste_path: str) -> List[str]:
        cmd = [sys.executable, "-m", "tastecal", "run", req["seed"], "--budget", str(req["budget"]),
               "--provider", req["provider"], "--out", out, "--language", req["language"], "--taste", taste_path]
        if req["model"]:
            cmd += ["--model", req["model"]]
        if req.get("effort"):
            cmd += ["--effort", req["effort"]]
        if req.get("scope"):
            cmd += ["--scope", req["scope"]]
        return cmd

    def new_id(self, seed: str) -> str:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        rid, k = f"{slug(seed)}-{stamp}", 2
        while os.path.exists(os.path.join(self.runs_dir, rid)):
            rid, k = f"{slug(seed)}-{stamp}-{k}", k + 1
        return rid

    def start(self, req: dict, key: str = "") -> str:
        rid = self.new_id(req["seed"])
        out = os.path.join(self.runs_dir, rid)
        os.makedirs(out)
        taste_path = os.path.join(out, "taste.md")
        with open(taste_path, "w", encoding="utf-8") as f:
            f.write(build_profile(req["taste_name"], req["taste"], req["papers"]))
        if req["taste_name"]:
            from tastecal.taste.profiles import put_profile
            put_profile(req["taste_name"], req["taste"], req["papers"], self.base)
        _write_json(os.path.join(out, "request.json"), dict(req, created=dt.datetime.now().isoformat(timespec="seconds")))
        env = dict(os.environ, TASTECAL_SERVED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env.pop("TASTECAL_PLAN", None)        # the page sends its own settings; a shell default must not change them
        env.pop("DEEPANALYZE_PLAN", None)
        if key and req["provider"] in ("anthropic", "openai"):
            env["ANTHROPIC_API_KEY" if req["provider"] == "anthropic" else "OPENAI_API_KEY"] = key
        log = open(os.path.join(out, "console.log"), "w", encoding="utf-8")
        # Own session (Windows: own process group and hidden console): Ctrl+C on the server, or closing its
        # terminal, does not end the analysis.
        proc = subprocess.Popen(awake(self.command(req, out, taste_path)), cwd=self.base, env=env, stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=(os.name == "posix"), creationflags=own_group())
        _write_json(os.path.join(out, "status.json"), {"state": "running", "pid": proc.pid,
                                                      "started": dt.datetime.now().isoformat(timespec="seconds")})
        with self.lock:
            self.procs[rid] = proc
        threading.Thread(target=self._wait, args=(rid, proc, log), daemon=True).start()
        return rid

    def resume(self, rid: str, key: str = "") -> Optional[bool]:
        """Continue a stopped or failed run in its own folder. None: no such run; False: it is still running."""
        out = self.folder("runs", rid)
        req = _read_json(os.path.join(out, "request.json")) if out else None
        if not req or not req.get("seed"):
            return None
        with self.lock:
            if rid in self.procs:
                return False
        if self.running_elsewhere(rid):
            return False
        env = dict(os.environ, TASTECAL_SERVED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env.pop("TASTECAL_PLAN", None)        # the page sends its own settings; a shell default must not change them
        env.pop("DEEPANALYZE_PLAN", None)
        if key and req.get("provider") in ("anthropic", "openai"):
            env["ANTHROPIC_API_KEY" if req["provider"] == "anthropic" else "OPENAI_API_KEY"] = key
        log = open(os.path.join(out, "console.log"), "a", encoding="utf-8")
        log.write(f"\n{dt.datetime.now():%H:%M:%S} tastecal: ---- resumed ----\n")
        log.flush()
        proc = subprocess.Popen(awake(self.resume_command(out)), cwd=self.base, env=env, stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=(os.name == "posix"), creationflags=own_group())
        st = _read_json(os.path.join(out, "status.json")) or {}
        _write_json(os.path.join(out, "status.json"), {"state": "running", "pid": proc.pid,
                                                      "started": st.get("started") or req.get("created") or "",
                                                      "resumed": dt.datetime.now().isoformat(timespec="seconds")})
        with self.lock:
            self.procs[rid] = proc
        threading.Thread(target=self._wait, args=(rid, proc, log), daemon=True).start()
        return True

    def taste_name(self, group: str, rid: str) -> str:
        """The taste profile a report was made with (its request.json), or "" when unknown."""
        folder = self.folder(group, rid) if rid else None
        req = _read_json(os.path.join(folder, "request.json")) if folder else None
        return str((req or {}).get("taste_name") or "")

    @staticmethod
    def default_resume_command(out: str) -> List[str]:
        return [sys.executable, "-m", "tastecal", "resume", out]

    def _wait(self, rid: str, proc: subprocess.Popen, log) -> None:
        code = proc.wait()
        log.close()
        path = os.path.join(self.runs_dir, rid, "status.json")
        st = _read_json(path) or {}
        if st.get("state") != "stopped":
            st["state"] = "done" if code == 0 and os.path.exists(os.path.join(self.runs_dir, rid, "report.html")) else "failed"
        st.update(returncode=code, finished=dt.datetime.now().isoformat(timespec="seconds"))
        _write_json(path, st)
        with self.lock:
            self.procs.pop(rid, None)

    def delete(self, rid: str) -> Optional[bool]:
        """Remove a finished report's folder from runs/. None when there is no such report; False while it runs."""
        folder = self.folder("runs", rid)
        if not folder:
            return None
        with self.lock:
            if rid in self.procs:
                return False
        if self.running_elsewhere(rid):
            return False
        shutil.rmtree(folder)
        return True

    def stop(self, rid: str) -> bool:
        with self.lock:
            proc = self.procs.get(rid)
        path = os.path.join(self.runs_dir, rid, "status.json")
        st = _read_json(path) or {}
        if not proc:
            # Started by an earlier server: stop it by its process id.
            pid = st.get("pid")
            if st.get("state") != "running" or not run_alive(pid):
                return False
            _write_json(path, dict(st, state="stopped", finished=dt.datetime.now().isoformat(timespec="seconds")))
            _terminate(int(pid))
            return True
        _write_json(path, dict(st, state="stopped"))
        _terminate(proc.pid)          # with the model calls it started, on every system
        return True

    def running_elsewhere(self, rid: str) -> bool:
        st = _read_json(os.path.join(self.runs_dir, rid, "status.json")) or {}
        return st.get("state") == "running" and run_alive(st.get("pid"))

    # -- reading ----------------------------------------------------------------------------
    def folder(self, group: str, rid: str) -> Optional[str]:
        if group not in GROUPS or not re.fullmatch(r"[A-Za-z0-9._\-\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", rid or ""):
            return None
        root = self.runs_dir if group == "runs" else os.path.join(self.base, "examples")
        path = os.path.realpath(os.path.join(root, rid))
        if not path.startswith(os.path.realpath(root) + os.sep) or not os.path.isdir(path):
            return None
        return path

    def list(self) -> List[dict]:
        rows = []
        for group in GROUPS:
            root = self.runs_dir if group == "runs" else os.path.join(self.base, "examples")
            if not os.path.isdir(root):
                continue
            for rid in os.listdir(root):
                path = os.path.join(root, rid)
                if os.path.isdir(path) and (os.path.exists(os.path.join(path, "request.json"))
                                            or os.path.exists(os.path.join(path, "graph.json"))):
                    rows.append(self.describe(group, rid, path))
        rows.sort(key=lambda r: (r["group"] != "runs", r["state"] != "running", r.get("created") or ""), reverse=False)
        running = [r for r in rows if r["state"] == "running"]
        rest = sorted([r for r in rows if r["state"] != "running" and r["group"] == "runs"],
                      key=lambda r: r.get("created") or "", reverse=True)
        examples = [r for r in rows if r["group"] == "examples"]
        return running + rest + examples

    def describe(self, group: str, rid: str, path: str) -> dict:
        req = _read_json(os.path.join(path, "request.json")) or {}
        st = _read_json(os.path.join(path, "status.json")) or {}
        has_report = os.path.exists(os.path.join(path, "report.html"))
        state = st.get("state") or ("done" if has_report else "failed")
        if state == "running" and rid not in self.procs and not run_alive(st.get("pid")):
            state = "done" if has_report else "stopped"      # it ended while no server was watching
        row = {"group": group, "id": rid, "seed": req.get("seed") or "", "provider": req.get("provider") or "",
               "model": req.get("model") or "", "budget": req.get("budget"), "language": req.get("language") or "",
               "taste_name": req.get("taste_name") or "", "created": req.get("created") or st.get("started") or "",
               "finished": st.get("finished") or "", "state": state, "has_report": has_report, "title": "", "facts": {}}
        g = _read_json(os.path.join(path, "graph.json"))
        if isinstance(g, dict):
            meta = g.get("meta") or {}
            seed = next((n for n in g.get("nodes") or [] if n.get("id") == meta.get("seed")), {})
            row["title"] = seed.get("title") or ""
            row["short"] = seed.get("short") or ""
            row["language"] = row["language"] or meta.get("language") or "en"
            row["facts"] = {"works": len(g.get("nodes") or []), "threads": len(g.get("threads") or []),
                            "folded": (g.get("gates") or {}).get("folded"), "treasures": ((g.get("gates") or {}).get("counts") or {}).get("treasure")}
            if not row["seed"]:
                row["seed"] = meta.get("seed_ref") or ""
            if not row["model"] and len(str(meta.get("model") or "")) <= 32:
                row["model"] = meta.get("model") or ""
            row["created"] = row["created"] or str(meta.get("generated_at") or "")
        row["created"] = row["created"] or _mtime(path)
        if state == "failed":
            last = [ln for ln in tail(os.path.join(path, "console.log"), 30) if ln.strip()]
            row["reason"] = re.sub(r"^\d\d:\d\d:\d\d \S+: ", "", last[-1])[:240] if last else ""
        if state == "running":
            row["stage"] = stage(tail(os.path.join(path, "console.log"), 400))
        row["model_used"], row["effort_used"] = model_in_use(path, g if isinstance(g, dict) else None)
        row["billed_to"] = billed_to(path)
        if req:
            row["request"] = {k: req.get(k) for k in ("seed", "scope", "provider", "plan", "model", "effort", "budget", "language",
                                                      "taste_name", "taste", "papers")}
            row["effort"] = req.get("effort") or ""
        return row


def own_group() -> int:
    """Windows: start a run in its own process group with its own hidden console, so Ctrl+C in the server's
    window (or closing that window) does not reach it. Elsewhere start_new_session does the same; 0 here."""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def awake(cmd: List[str]) -> List[str]:
    """On a Mac, keep the computer from idle-sleeping while a run works (a sleeping Mac drops model calls)."""
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        return ["caffeinate", "-i"] + cmd
    return cmd


def _windows_pid_alive(pid: int) -> bool:
    """Windows: is the process still running? Asked through the Win32 API, because os.kill(pid, 0) on Windows does not
    test a process: it TERMINATES it (exit code 0)."""
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return k32.GetLastError() == 5                 # access denied: it exists, it is just not ours to open
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def _windows_image(pid: int) -> str:
    """Windows: the program name of a process ("python.exe"), "" when unknown."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.match(r'\s*"([^"]+)"', out or "")
    return m.group(1).lower() if m else ""


def run_alive(pid) -> bool:
    """True when `pid` is a live tastecal run (checked by its command line, so a reused pid does not count)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        if not _windows_pid_alive(pid):
            return False
        image = _windows_image(pid)
        return not image or "python" in image          # a run is a Python process; a reused pid usually is not
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True          # no ps: trust the pid
    return "tastecal" in out or "deepanalyze" in out   # older runs too


def _terminate(pid: int) -> None:
    """End a run and the model calls it started (they share its process group; on Windows, its process tree)."""
    import signal
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def billed_to(path: str) -> str:
    """'plan' or 'api key' from the run log's `Claude Code is billing` / `Codex is billing` line; "" when not reported."""
    try:
        with open(os.path.join(path, "console.log"), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Claude Code is billing " in line or "Codex is billing " in line:
                    return "api key" if ("not your" in line or "API key" in line) else "plan"
    except OSError:
        pass
    return ""


def model_in_use(path: str, graph: Optional[dict] = None) -> Tuple[str, str]:
    """(model id, effort) the service reported for this run: from the run log's `model in use:` line,
    else from the finished report. ("", "") when nothing was reported yet."""
    log_path = os.path.join(path, "console.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.search(r"model in use: (\S+) · effort (\S+)", line)
                if m:
                    return m.group(1), m.group(2)
    except OSError:
        pass
    meta = (graph or {}).get("meta") or {}
    m = re.match(r"[^:\s]+:(\S+) · effort (\S+)$", str(meta.get("model") or ""))
    return (m.group(1), m.group(2)) if m else ("", "")


def stage(lines: List[str]) -> str:
    """A short progress label from the run's log."""
    last = next((ln for ln in reversed(lines) if ln.strip()), "")
    m = re.search(r"usage limit reached; waiting until (\d{4}-\d\d-\d\d) (\d\d:\d\d)", last)
    if m:
        day = "" if m.group(1) == dt.date.today().isoformat() else m.group(1)[5:] + " "
        return f"Waiting for your plan's usage limit to reset · until {day}{m.group(2)}"
    text = "\n".join(lines)
    if "plain language" in text:
        return "Polishing the text"
    if re.search(r"adversarial review|audit:", text):
        return "Auditing contribution"
    reads = len(re.findall(r"(?:tastecal|deepanalyze)\.gates: reading ", text))
    if reads:
        return f"Reading papers · {reads} read"
    if re.search(r"synth|threads|outlook", text, re.I) and "round" in text:
        last = re.findall(r"round (\d+)", text)
        return "Writing the synthesis" if not last else f"Growing the map · round {last[-1]}"
    last = re.findall(r"round (\d+)", text)
    if last:
        return f"Growing the map · round {last[-1]}"
    if "seed:" in text:
        return "Reading the seed"
    return "Starting"


def tail(path: str, n: int = 60) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


def _mtime(path: str) -> str:
    return dt.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def codex_bin() -> Optional[str]:
    return shutil.which(os.environ.get("CODEX_BIN", "codex"))


def codex_signed_in() -> Optional[bool]:
    """True or False from `codex login status`; None when it cannot tell."""
    exe = codex_bin()
    if not exe:
        return False
    try:
        p = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = f"{p.stdout}\n{p.stderr}".lower()
    if re.search(r"not logged in|not signed in|authenticated:\s*no|no credentials|login required", text):
        return False
    if p.returncode == 0 and re.search(r"logged in|signed in|authenticated:\s*yes|chatgpt|api key", text):
        return True
    if p.returncode != 0 and "unrecognized" not in text and "unexpected" not in text:
        return False
    return os.path.exists(os.path.join(os.path.expanduser("~"), ".codex", "auth.json")) or None


class CodexLogin:
    """Runs `codex login` in the background. It opens the browser for ChatGPT sign-in; any URL it prints is kept
    so the page can show it as a link in case the browser does not open."""

    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.output: List[str] = []

    def start(self) -> dict:
        exe = codex_bin()
        if not exe:
            return {"error": "The codex command was not found. Install it with: npm install -g @openai/codex"}
        if self.proc and self.proc.poll() is None:
            return {"started": True, "url": self.url()}
        self.output = []
        self.proc = subprocess.Popen([exe, "login"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        return {"started": True}

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.output.append(line.rstrip())
            del self.output[:-40]

    def url(self) -> str:
        for line in reversed(self.output):
            m = re.search(r"https://\S+", line)
            if m:
                return m.group(0)
        return ""

    def state(self) -> dict:
        running = bool(self.proc and self.proc.poll() is None)
        return {"running": running, "url": self.url(), "signed_in": codex_signed_in(),
                "last": self.output[-1] if self.output else ""}


def providers_state() -> dict:
    from tastecal.core.config import PLANS
    from tastecal.core.llm import codex_auth
    claude = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    codex = codex_bin()
    mode = codex_auth(codex) if codex else ""
    signed = (mode in ("chatgpt", "apikey")) if mode else (codex_signed_in() if codex else False)
    return {"codex-cli": {"available": bool(codex), "signed_in": signed, "auth": mode},
            "plans": [{"key": k, **v} for k, v in PLANS.items()],
            "s2_key": bool(os.environ.get("S2_API_KEY")),
            "anthropic": {"key": bool(os.environ.get("ANTHROPIC_API_KEY"))},
            "openai": {"key": bool(os.environ.get("OPENAI_API_KEY")), "base_url": os.environ.get("OPENAI_BASE_URL", "")},
            "claude-cli": {"available": bool(claude)},
            "models": MODELS}


PAPER_HEADS = {"## papers i liked": 0.8, "## papers i disliked": 0.2, "## papers i noted": None}
PAPER_LINE = re.compile(r"^-\s+(?P<ref>.+?)(?:\s+\(my score (?P<score>[0-9.]+)\))?(?::\s+(?P<why>.*))?$")


def split_profile(body: str):
    """(taste text, sample papers) from a profile body. Papers come from its "Papers I liked/disliked/noted"
    sections; patterns written in brackets ("(a pattern, not a paper) ...") stay in the text."""
    keep, papers, section = [], [], None
    for line in body.splitlines():
        low = line.strip().lower()
        if low.startswith("## "):
            section = low if low in PAPER_HEADS else None
            if section is None:
                keep.append(line)
            continue
        if low.startswith("scores are my own rating"):
            continue
        if section is not None:
            m = PAPER_LINE.match(line.strip())
            if m and not m.group("ref").startswith("("):
                score = float(m.group("score")) if m.group("score") else PAPER_HEADS[section]
                papers.append({"ref": m.group("ref").strip(), "score": score, "comment": (m.group("why") or "").strip()})
            elif line.strip():
                keep.append(line)                     # a pattern line or prose: keep it as taste text
            continue
        keep.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip(), papers


def profiles_state(base: str = ".") -> List[dict]:
    """Your profiles from taste.json first (and any older profiles/*.md), then the presets."""
    from tastecal.taste.profiles import list_profiles, load_profile, load_store
    store = load_store(base)
    out = [{"name": k, "title": v.get("title") or k, "kind": "yours", "text": v.get("taste") or "",
            "papers": [p for p in v.get("papers") or [] if isinstance(p, dict) and p.get("ref")],
            "default": k == store.get("default")}
           for k, v in store.get("profiles", {}).items() if isinstance(v, dict)]
    seen = {p["name"] for p in out}
    for name, path, kind in list_profiles(os.path.join(base, "profiles")):
        if name in seen:
            continue
        try:
            title, text, _ = load_profile(path)
        except OSError:
            continue
        body = re.sub(r"^#\s+.*\n+", "", text, count=1)
        taste, papers = split_profile(body)
        out.append({"name": name, "title": title, "kind": kind, "text": taste, "papers": papers, "default": False})
    return out


# ----------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    runner: Runner = None  # set by make_server
    login: "CodexLogin" = None
    server_version = "tastecal"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _local_only(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def do_GET(self):
        if not self._local_only():
            return self._send(HTTPStatus.FORBIDDEN, b"local only", "text/plain")
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            # The page as it was when this server started, so page and server always match.
            return self._send(200, self.page, "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json({"api": API_VERSION, "providers": providers_state(),
                               "profiles": profiles_state(self.runner.base), "runs": self.runner.list()})
        if path == "/api/runs":
            return self._json(self.runner.list())
        if path == "/api/codex/status":
            return self._json(self.login.state())
        if path == "/api/taste/ratings":
            # Your ratings, for the rating buttons in a report opened from this page.
            from urllib.parse import parse_qs
            from tastecal.taste.profiles import load_store, rated_profile
            q = parse_qs(urlparse(self.path).query)
            key = rated_profile(self.runner.taste_name((q.get("group") or ["runs"])[0], (q.get("run") or [""])[0]),
                                self.runner.base)
            prof = load_store(self.runner.base)["profiles"].get(key) or {}
            return self._json({"profile": key, "title": prof.get("title") or key,
                               "papers": [p for p in prof.get("papers") or [] if isinstance(p, dict)]})
        m = re.fullmatch(r"/api/(runs|examples)/([^/]+)/log", path)
        if m:
            folder = self.runner.folder(m.group(1), m.group(2))
            if not folder:
                return self._json({"error": "no such report"}, 404)
            lines = tail(os.path.join(folder, "console.log"), 80) or tail(os.path.join(folder, "run.log"), 80)
            return self._json({"lines": lines})
        m = re.fullmatch(r"/(runs|examples)/([^/]+)/(report\.html|graph\.json|taste\.md)", path)
        if m:
            folder = self.runner.folder(m.group(1), m.group(2))
            f = os.path.join(folder, m.group(3)) if folder else ""
            if not f or not os.path.exists(f):
                return self._send(404, b"not found", "text/plain")
            ctype = {"html": "text/html", "json": "application/json", "md": "text/markdown"}[f.rsplit(".", 1)[1]]
            with open(f, "rb") as fh:
                return self._send(200, fh.read(), ctype + "; charset=utf-8")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._local_only() or "1" not in (self.headers.get("X-TasteCal"), self.headers.get("X-DeepAnalyze")):
            return self._json({"error": "forbidden"}, 403)
        path = unquote(urlparse(self.path).path)      # report ids may be Chinese, sent percent-encoded
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        if path == "/api/runs":
            try:
                req = clean_request(body)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            st = providers_state()
            from tastecal.core.config import clean_secret
            key = clean_secret(body.get("key"))
            if req["provider"] in ("anthropic", "openai") and not (key or st[req["provider"]]["key"]):
                name = "ANTHROPIC_API_KEY" if req["provider"] == "anthropic" else "OPENAI_API_KEY"
                return self._json({"error": f"No API key. Paste one, or set {name} before starting the server."}, 400)
            if req["provider"] == "claude-cli" and not st["claude-cli"]["available"]:
                return self._json({"error": "The claude command was not found. Install Claude Code, or set CLAUDE_BIN."}, 400)
            if req["provider"] == "codex-cli" and not st["codex-cli"]["available"]:
                return self._json({"error": "The codex command was not found. Install it with: npm install -g @openai/codex, "
                                            "then sign in."}, 400)
            if req["provider"] == "codex-cli" and st["codex-cli"]["signed_in"] is False:
                return self._json({"error": "You are not signed in to ChatGPT yet. Click Sign in with ChatGPT first.",
                                   "need_login": True}, 400)
            rid = self.runner.start(req, key)
            return self._json({"id": rid})
        m = re.fullmatch(r"/api/runs/([^/]+)/resume", path)
        if m:
            from tastecal.core.config import clean_secret
            ok = self.runner.resume(m.group(1), clean_secret(body.get("key")))
            if ok is None:
                return self._json({"error": "This report has no saved settings to resume from."}, 404)
            return self._json({"resumed": True} if ok else {"error": "It is still running."}, 200 if ok else 409)
        m = re.fullmatch(r"/api/runs/([^/]+)/stop", path)
        if m:
            return self._json({"stopped": self.runner.stop(m.group(1))})
        m = re.fullmatch(r"/api/runs/([^/]+)/delete", path)
        if m:
            ok = self.runner.delete(m.group(1))
            if ok is None:
                return self._json({"error": "No such report."}, 404)
            return self._json({"deleted": True} if ok else {"error": "Stop the report before deleting it."}, 200 if ok else 409)
        if path == "/api/profiles":
            name = " ".join(str(body.get("name") or "").split())[:60]
            if not name:
                return self._json({"error": "Give the template a name."}, 400)
            from tastecal.taste.profiles import put_profile
            req = clean_request({"seed": "x", "provider": "anthropic", "papers": body.get("papers") or []})
            key = put_profile(name, str(body.get("taste") or "")[:8000], req["papers"], self.runner.base,
                              make_default=bool(body.get("default")))
            return self._json({"saved": key, "profiles": profiles_state(self.runner.base)})
        if path == "/api/taste/rate":
            from tastecal.taste.profiles import rate_paper
            ref = " ".join(str(body.get("ref") or "").split())[:400]
            if not ref:
                return self._json({"error": "Which paper?"}, 400)
            score = body.get("score")
            try:
                score = None if score in (None, "") else float(score)
            except (TypeError, ValueError):
                return self._json({"error": "A score from 0 to 1."}, 400)
            res = rate_paper(ref, score, str(body.get("comment") or "").strip()[:400],
                             self.runner.taste_name(str(body.get("group") or "runs"), str(body.get("run") or "")),
                             self.runner.base)
            return self._json({k: res[k] for k in ("profile", "title", "rated")})
        if path == "/api/codex/login":
            res = self.login.start()
            return self._json(res, 400 if res.get("error") else 200)
        return self._json({"error": "not found"}, 404)


def make_server(host: str = "127.0.0.1", port: int = 8765, base: str = ".", command=None,
                resume_command=None) -> ThreadingHTTPServer:
    with open(APP, "rb") as f:
        page = f.read()
    handler = type("BoundHandler", (Handler,), {"runner": Runner(base, command=command, resume_command=resume_command),
                                                "login": CodexLogin(), "page": page})
    last = None
    for p in range(port, port + 20) if port else [0]:
        try:
            return ThreadingHTTPServer((host, p), handler)
        except OSError as e:
            last = e
    raise last


def serve(host: str = "127.0.0.1", port: int = 8765, base: str = ".", open_browser: bool = True) -> int:
    srv = make_server(host, port, base)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"tastecal is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        runner = getattr(srv.RequestHandlerClass, "runner", None)
        busy = [r for r in runner.list() if r.get("group") == "runs" and r.get("state") == "running"] if runner else []
        print("\nStopped." + (f" {len(busy)} analysis(es) keep running in the background and show up here next time."
                               if busy else ""))
    finally:
        srv.server_close()
    return 0
