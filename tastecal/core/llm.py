"""Pluggable LLM backends (Anthropic Messages API, any OpenAI-compatible
chat endpoint) with a disk cache and robust JSON extraction."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Any, List, Optional

from tastecal.core.config import Config, from_env
from tastecal.core.http import Http, HttpError

log = logging.getLogger("tastecal.llm")


class LLMError(RuntimeError):
    pass


class LLM:
    """Base class. Subclasses implement `_complete(system, prompt, max_tokens)`."""

    name = "base"
    clock = time.time       # replaced in tests
    sleeper = time.sleep

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = os.path.join(cache_dir, "llm") if cache_dir else None
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
        self.system_note = ""          # appended to every system prompt: output language and plain-language rules
        self.calls = 0
        self.cache_hits = 0
        self.input_chars = 0
        self.output_chars = 0
        self.effort = ""               # the effort asked for; "" = the model's own default
        self.effort_used = ""          # the effort the service reported, when it reports one
        self.used = {}                 # model id the service says answered -> live calls
        self.cost_usd = 0.0            # cost the service reported (claude -p reports one even on a subscription)
        self.billed_to = ""            # who pays, when the service says (Claude Code does)
        self.last: dict = {}           # the last call's raw result event, for `tastecal doctor`
        self.waits_for_limits = False  # subscription tools set this: wait out the plan's usage limit, then go on
        self.max_wait = 0.0            # seconds a run may spend waiting for limits to reset, in all
        self.limit_waited = 0.0

    # ------------------------------------------------------------------------
    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:  # pragma: no cover
        raise NotImplementedError

    def _key(self, system: str, prompt: str) -> str:
        # The effort is part of the key, so a run at another effort does not reuse these answers.
        # Without an effort the key is unchanged, so older caches still work.
        name = self.name + (f"|effort={self.effort}" if self.effort else "")
        return hashlib.sha256(f"{name}\n{system}\n---\n{prompt}".encode("utf-8")).hexdigest()[:40]

    def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        if self.system_note:
            system = system + "\n\n" + self.system_note
        key = self._key(system, prompt)
        path = os.path.join(self.cache_dir, key + ".txt") if self.cache_dir else None
        if path and os.path.exists(path):
            self.cache_hits += 1
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        self.calls += 1
        self.input_chars += len(system) + len(prompt)
        out = self._retrying(system, prompt, max_tokens)
        self.output_chars += len(out)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
        return out

    # A dropped connection or a computer that slept mid-call is worth waiting out; a run is hours of work.
    TRANSIENT = re.compile(r"went to sleep|network|connection|ECONN|ETIMEDOUT|EAI_AGAIN|ENOTFOUND|socket|offline|"
                           r"overloaded|\b50[0234]\b|\b529\b|timed out|timeout|temporar|try again|fetch failed|"
                           r"incomplete|internal server error|error_during_execution|no message \(subtype|"
                           r"interrupted|aborted|empty response", re.I)
    FINAL = re.compile(r"usage limit|limit reached|limit will reset|credit balance|quota|billing|not logged in|"
                       r"not signed in|log ?in|unauthori[sz]ed|invalid api key|\b401\b|\b402\b|\b403\b|cannot use the model|"
                       r"费用|额度|余额|does not support this model|or newer is required|claude update", re.I)
    # Your plan's usage limit (claude-cli, codex-cli). Not a fault: the run waits for the reset and goes on.
    LIMIT = re.compile(r"usage limit|limit reached|hit your (usage |session |weekly )?limit|limit will reset|"
                       r"resets? (at|on|in)\b|resets \d|try again (in|at|after)\b|weekly limit|session limit|"
                       r"5-hour limit|five-hour|quota|out of (usage|messages)|rate.?limit|too many requests|\b429\b", re.I)
    # Never waited out: a missing sign-in, or money (an API key or a gateway out of credit).
    AUTH = re.compile(r"not logged in|not signed in|log ?in required|please (run )?/?login|run `?codex login|"
                      r"unauthori[sz]ed|invalid api key|\b401\b|\b403\b|cannot use the model|is billing|"
                      r"does not support this model|or newer is required", re.I)
    PAY = re.compile(r"\b402\b|credit balance|insufficient_quota|费用|余额", re.I)
    SOFT = re.compile(r"rate.?limit|too many requests|\b429\b", re.I)
    HARD = re.compile(r"usage limit|hit your|weekly|session limit|5-hour|five-hour|resets?\b|quota|out of", re.I)
    WAITS = (30, 60, 120, 240, 300)
    LIMIT_POLL = 30 * 60          # no reset time in the message: look again in 30 minutes (5 for a bare rate limit)

    def plan_limit(self, msg: str) -> bool:
        """True when `msg` says the plan's usage limit was reached, and this backend waits such limits out."""
        return bool(self.waits_for_limits and self.LIMIT.search(msg) and not self.AUTH.search(msg)
                    and not self.PAY.search(msg))

    def _retrying(self, system: str, prompt: str, max_tokens: int) -> str:
        attempt = 0
        while True:
            try:
                return self._complete(system, prompt, max_tokens)
            except LLMError as e:
                msg = str(e)
                if self.plan_limit(msg):
                    self._wait_for_reset(msg)
                    continue
                if attempt == len(self.WAITS) or self.FINAL.search(msg) or not self.TRANSIENT.search(msg):
                    raise
                wait = self.WAITS[attempt]
                attempt += 1
                log.warning("model call failed (%s); trying again in %d s", " ".join(msg.split())[:160], wait)
                self.sleeper(wait)

    def _wait_for_reset(self, msg: str) -> None:
        """Sleep until the plan's limit resets: the time the message gives (plus a minute), else a fixed pause.
        It naps a minute at a time against the wall clock, so a Mac that slept still wakes up on time.
        Raises LLMError once the run would wait longer than max_wait in all."""
        now = self.clock()
        until = reset_time(msg, now)
        if until:
            until += 60
        else:
            soft = self.SOFT.search(msg) and not self.HARD.search(msg)
            until = now + (5 * 60 if soft else self.LIMIT_POLL)
        until = max(until, now + 60)
        if self.limit_waited + (until - now) > self.max_wait:
            raise LLMError(f"Your plan's usage limit was reached, and this run may not wait that long "
                           f"(at most {self.max_wait / 3600:.0f} h in all). Everything so far is saved: resume it "
                           f"after the reset. The service said: {' '.join(msg.split())[:200]}")
        log.warning("plan usage limit reached; waiting until %s for it to reset, then continuing. Nothing is lost, "
                    "and you can also stop now and resume later. (%s)",
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(until)), " ".join(msg.split())[:160])
        start = self.clock()
        while True:
            left = until - self.clock()
            if left <= 0:
                break
            self.sleeper(min(60.0, left))
        took = max(0.0, self.clock() - start)
        self.limit_waited += took
        log.info("waited %.0f min for the usage limit to reset; trying again", took / 60)

    def json(self, system: str, prompt: str, max_tokens: int = 4096) -> Any:
        """Ask for JSON; on a parse failure, ask once more with the error."""
        text = self.complete(system, prompt, max_tokens)
        try:
            return extract_json(text)
        except ValueError as e:
            log.warning("JSON parse failed (%s); asking the model to repair it", e)
            repair = (prompt + "\n\nYour previous answer could not be parsed as JSON (" + str(e)
                      + "). Reply again with ONLY the JSON value, no prose, no code fences.")
            return extract_json(self.complete(system, repair, max_tokens))

    def usage(self) -> str:
        cost = f", about ${self.cost_usd:,.2f} at API prices" if self.cost_usd else ""
        return (f"{self.calls} live calls, {self.cache_hits} cache hits, "
                f"~{self.input_chars // 4:,} input tokens, ~{self.output_chars // 4:,} output tokens{cost}")

    # ------------------------------------------------------------------------
    def _saw(self, model: Any, effort: Any = None) -> None:
        """Record which model actually answered. Logs it the first time, so the run log says
        e.g. `model in use: claude-opus-5-5 · effort xhigh` rather than only the alias that was asked for."""
        model = str(model or "").strip()
        if effort:
            self.effort_used = str(effort).strip()
        if not model:
            return
        first = model not in self.used
        self.used[model] = self.used.get(model, 0) + 1
        if first:
            log.info("model in use: %s · effort %s", model, self.effort_label())

    def effort_label(self) -> str:
        return self.effort_used or self.effort or "default"

    def model_used(self) -> str:
        """The model that answered most calls, or "" when none was reported (e.g. everything came from the cache)."""
        return max(self.used, key=self.used.get) if self.used else ""

    def describe(self) -> str:
        """`provider:model · effort x` with the model the service reported, for the log and the report."""
        used = self.model_used()
        head = f"{self.name.split(':')[0]}:{used}" if used else self.name
        return f"{head} · effort {self.effort_label()}"


_UNIT = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_SPAN = r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b"


def reset_time(text: str, now: Optional[float] = None) -> Optional[float]:
    """When a usage limit resets, as a Unix time, read from the service's message; None when it does not say.
    Understands an epoch after a bar ("...limit reached|1760000000"), a delay ("try again in 2 hours 13 minutes",
    "resets in 45m") and a clock time with or without a date ("resets 3pm", "resets at 15:00",
    "resets Oct 20, 9am (Asia/Singapore)"). A clock time without a date that has passed means tomorrow."""
    import datetime as dt
    now = time.time() if now is None else now
    t = " ".join(str(text or "").split())
    m = re.search(r"\|\s*(\d{10})\b", t) or re.search(r"\bresets?\D{0,12}?(\d{10})\b", t, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(?:in|after)\s+((?:" + _SPAN + r"[\s,]*(?:and\s+)?)+)", t, re.I)
    if m and re.search(r"try again|reset|available|wait|limit", t, re.I):
        secs = sum(int(n) * _UNIT[u[0].lower()] for n, u in re.findall(_SPAN, m.group(1), re.I))
        if secs:
            return now + secs
    m = re.search(r"\b(?:resets?|try again|available)\s+(?:at\s+|on\s+)?"
                  r"(?:(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?"
                  r"(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>[ap]\.?m\.?)?(?![\w:])", t, re.I)
    if not m or not (m.group("ap") or m.group("mi")):
        return None
    h, mi = int(m.group("h")), int(m.group("mi") or 0)
    ap = (m.group("ap") or "").lower()[:1]
    if ap and not 1 <= h <= 12:
        return None
    h = (h % 12) + (12 if ap == "p" else 0) if ap else h
    if h > 23 or mi > 59:
        return None
    tz = None
    z = re.search(r"\(([A-Za-z]+(?:/[A-Za-z0-9_+\-]+)+|UTC|GMT)\)", t)
    if z:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(z.group(1))
        except Exception:          # no tz database: read it as local time
            tz = None
    base = dt.datetime.fromtimestamp(now, tz) if tz else dt.datetime.fromtimestamp(now)
    mon = (m.group("mon") or "")[:3].lower()
    try:
        if mon in _MONTHS and m.group("day"):
            when = base.replace(month=_MONTHS[mon], day=int(m.group("day")), hour=h, minute=mi, second=0, microsecond=0)
            if when.timestamp() < now - 86400:
                when = when.replace(year=when.year + 1)
        else:
            when = base.replace(hour=h, minute=mi, second=0, microsecond=0)
            if when.timestamp() <= now - 60:
                when += dt.timedelta(days=1)
    except ValueError:
        return None
    return when.timestamp()


def allow_key() -> bool:
    """TASTECAL_ALLOW_KEY=1 lets Claude Code or Codex bill an API key or gateway instead of your plan.
    (TASTECAL_CLAUDE_KEEP_KEY is the older name; the DEEPANALYZE_* names still work.)"""
    return any(from_env(k) not in ("", "0") for k in ("ALLOW_KEY", "CLAUDE_KEEP_KEY"))


def codex_auth(exe: str, env: Optional[dict] = None) -> str:
    """How Codex is signed in, from `codex login status`: "chatgpt", "apikey", "none", or "" when it cannot tell."""
    try:
        p = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = f"{p.stdout}\n{p.stderr}".lower()
    if re.search(r"not logged in|not signed in|no credentials|login required", text):
        return "none"
    if re.search(r"api[ _-]?key", text):
        return "apikey"
    if "chatgpt" in text:
        return "chatgpt"
    return ""


SETUP_HELP = ("Sign in with your subscription, no API key needed:\n"
              "  Claude (Pro, Max, Team, Enterprise): install Claude Code, run `claude`, type /login and choose "
              "\"Claude account with subscription\".\n"
              "  ChatGPT (any plan): npm install -g @openai/codex, run `codex login` and choose Sign in with ChatGPT.\n"
              "To use an API key on purpose instead, pass --provider anthropic or --provider openai.")


def detect_provider() -> str:
    """The tool to use when none is given: Claude Code if it is installed, else Codex. Both run on the plan you
    are signed in to. An API key is never picked on its own; ask for one with --provider anthropic or openai."""
    if shutil.which(os.environ.get("CLAUDE_BIN", "claude")):
        return "claude-cli"
    if shutil.which(os.environ.get("CODEX_BIN", "codex")):
        return "codex-cli"
    raise LLMError("Neither Claude Code (`claude`) nor Codex (`codex`) was found.\n" + SETUP_HELP)


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON value found")
    start = min(starts)
    opener = t[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except json.JSONDecodeError as e:
                    raise ValueError(str(e))
    raise ValueError("unterminated JSON value")


class AnthropicLLM(LLM):
    name = "anthropic"

    def __init__(self, cfg: Config, http: Http):
        super().__init__(cfg.cache_dir)
        if not cfg.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set. Export it, or use --provider openai.")
        self.cfg, self.http = cfg, http
        self.model = cfg.resolved_model()
        self.url = cfg.resolved_base_url() + "/v1/messages"
        self.name = f"anthropic:{self.model}"
        self.effort = cfg.effort or ""

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": self.cfg.temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.cfg.effort:
            body["output_config"] = {"effort": self.cfg.effort}
        headers = {"x-api-key": self.cfg.anthropic_api_key, "anthropic-version": "2023-06-01"}
        try:
            data = self.http.post_json(self.url, body, headers)
        except HttpError as e:
            raise LLMError(f"Anthropic call failed: {e}")
        self._saw(data.get("model"))
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "".join(parts)


class OpenAICompatLLM(LLM):
    name = "openai"

    def __init__(self, cfg: Config, http: Http):
        super().__init__(cfg.cache_dir)
        if not cfg.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set (use any key your endpoint accepts).")
        self.cfg, self.http = cfg, http
        self.model = cfg.resolved_model()
        self.url = cfg.resolved_base_url() + "/chat/completions"
        self.name = f"openai:{self.url}:{self.model}"
        if re.match(r"(gpt-[5-9]|o\d)", self.model):
            self.effort = {"max": "high", "xhigh": "high"}.get(cfg.effort, cfg.effort or "")
        elif cfg.effort:
            self.effort = "n/a"          # older chat models have no effort setting

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if re.match(r"(gpt-[5-9]|o\d)", self.model):     # reasoning models: no temperature, a different token limit
            body["max_completion_tokens"] = max(max_tokens, 16000)
            if self.cfg.effort:
                body["reasoning_effort"] = {"max": "high", "xhigh": "high"}.get(self.cfg.effort, self.cfg.effort)
        else:
            body.update(temperature=self.cfg.temperature, max_tokens=max_tokens)
        headers = {"Authorization": f"Bearer {self.cfg.openai_api_key}"}
        try:
            data = self.http.post_json(self.url, body, headers)
        except HttpError as e:
            raise LLMError(f"OpenAI-compatible call failed: {e}")
        self._saw(data.get("model"))
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected response shape: {str(data)[:300]}") from e


class ClaudeCLILLM(LLM):
    """Uses the Claude Code command line (`claude -p`) with whatever account it is
    logged in to, so a Claude subscription can drive the pipeline without an API key."""

    name = "claude-cli"
    # Every built-in tool a Claude Code version may offer. Newer versions add tools; one the model can still reach uses
    # up the single turn a call is allowed and the call fails with error_max_turns. `--tools ""` (where supported)
    # turns them all off; this list is the fallback for versions without it. Unknown names are ignored.
    NO_TOOLS = ("Agent Task Bash BashOutput KillShell Edit MultiEdit Write Read Glob Grep LS NotebookEdit NotebookRead "
                "WebFetch WebSearch TodoWrite TaskCreate TaskUpdate TaskList TaskGet TaskStop TaskOutput Skill "
                "SlashCommand ToolSearch Monitor EnterPlanMode ExitPlanMode ListMcpResourcesTool ReadMcpResourceTool "
                "mcp__claude-in-chrome")
    TOOL_NUDGE = ("\n\nReply with the answer text only, in the format asked for above. Do not call any tool: none is "
                  "needed and none will run.")

    def __init__(self, cfg: Config, http: Optional[Http] = None):
        super().__init__(cfg.cache_dir)
        self.bin = shutil.which(os.environ.get("CLAUDE_BIN", "claude"))
        if not self.bin:
            raise LLMError("The `claude` command (Claude Code) is not on your PATH. Install Claude Code, "
                           "run `claude` once to log in, then retry.")
        self.model = cfg.model           # resolved by make_llm: "" = Claude Code's own default
        self.effort = cfg.effort
        self.name = f"claude-cli:{self.model or 'default'}"
        self.lean = from_env("CLAUDE_PLAIN", "") == ""
        # Newer options that shut every tool off (--tools "", --no-chrome: the Chrome integration's tools are not
        # covered by --strict-mcp-config) and keep no session files. Each is dropped on its own if this Claude Code
        # does not know it.
        self.extra = {"--tools": ["--tools", ""], "--no-chrome": ["--no-chrome"],
                      "--no-session-persistence": ["--no-session-persistence"]}
        self.billed_to = ""
        self.last: dict = {}
        self.waits_for_limits = cfg.wait_for_limits
        self.max_wait = cfg.max_wait_hours * 3600

    # Billing source as Claude Code reports it in its start-up event ("apiKeySource").
    PLAN = ("none", "", None)
    # Set in the shell, these make Claude Code charge an API key or another service instead of your plan.
    NOT_PLAN_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")

    @staticmethod
    def allow_key() -> bool:
        """See the module's allow_key()."""
        return allow_key()

    def _env(self) -> dict:
        """The environment for claude -p, without the variables that bill someone other than your plan."""
        env = dict(os.environ)
        if self.allow_key():
            return env
        dropped = [k for k in self.NOT_PLAN_ENV if k in env and env.pop(k) is not None]
        if dropped and not getattr(self, "_told_env", False):
            self._told_env = True
            log.info("left %s out of the Claude Code calls so they use your plan "
                     "(set TASTECAL_ALLOW_KEY=1 to keep them)", ", ".join(dropped))
        return env

    def _command(self, system: str, lean: bool) -> List[str]:
        if lean:
            # stream-json + --verbose adds a start-up event that names the model and who is billed.
            # --system-prompt replaces Claude Code's own (long, coding-agent) system prompt, so each call
            # sends far fewer tokens; --strict-mcp-config skips starting MCP servers.
            cmd = [self.bin, "-p", "--output-format", "stream-json", "--verbose", "--max-turns", "1",
                   "--system-prompt", system, "--strict-mcp-config", "--disallowedTools", self.NO_TOOLS]
            for args in self.extra.values():
                cmd += args
        else:   # the plain form every Claude Code version accepts
            cmd = [self.bin, "-p", "--output-format", "json", "--max-turns", "1",
                   "--append-system-prompt", system, "--disallowedTools", self.NO_TOOLS]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    def _run(self, system: str, prompt: str):
        """One `claude -p` call: (process, stderr in one line). Falls back to older command forms when needed."""
        import tempfile
        if not getattr(self, "workdir", None):
            # An empty folder: no project CLAUDE.md or settings get pulled into every call.
            self.workdir = tempfile.mkdtemp(prefix="tastecal-claude-")
        unknown = r"unknown option|unexpected argument|unrecognized|error: option|invalid option"
        while True:
            lean = self.lean
            try:
                proc = subprocess.run(self._command(system, lean), input=prompt, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace",
                                      timeout=900, cwd=self.workdir, env=self._env())
            except subprocess.TimeoutExpired:
                raise LLMError("claude -p timed out after 15 minutes")
            err = " ".join((proc.stderr or "").split())
            if lean and proc.returncode != 0 and re.search(unknown, err, re.I):
                named = [flag for flag in self.extra if flag in err]
                if named:
                    for flag in named:     # this Claude Code lacks the option: the disallowed list still applies
                        del self.extra[flag]
                    log.info("this Claude Code does not know %s; going on without it", ", ".join(named))
                    continue
                self.lean = False          # an older Claude Code: use the plain form from now on
                log.info("this Claude Code does not support the leaner call options; using the plain form")
                continue
            return proc, err

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        # A model that reaches for a tool anyway uses up its one turn (error_max_turns). Ask again at once, saying
        # plainly that no tool will run; waiting would not help.
        for nudge in range(3):
            proc, err = self._run(system, prompt + (self.TOOL_NUDGE if nudge else ""))
            _, res = self._events(proc.stdout)
            if res and res.get("is_error") and res.get("subtype") == "error_max_turns" and nudge < 2:
                log.info("the model tried to use a tool instead of answering; asking again for the answer only")
                continue
            break
        if proc.returncode != 0 and not proc.stdout.strip():
            raise LLMError(f"claude -p failed ({proc.returncode}): {err[:400]}")
        init, result = self._events(proc.stdout)
        if init:
            self._billing(init)
        if result is None:
            return proc.stdout  # plain-text output; extract_json will cope
        if result.get("is_error"):
            text = self._error_text(result, err)
            self._keep_failure(result, proc)
            if result.get("subtype") == "error_max_turns":
                raise LLMError("claude -p kept trying to use a tool instead of answering, three times in a row "
                               f"(error_max_turns). Run `claude update`, then resume. Claude Code said: {text[:200]}")
            if re.search(r"does not support this model|or newer is required", text, re.I):
                raise LLMError(f"This Claude Code is too old for the model {self.model or '(default)'}. Run `claude update` "
                               f"in Terminal, then start again. Claude Code said: {text[:300]}")
            raise LLMError(f"claude -p reported an error: {text[:400]}")
        self._note(result)
        if not self.used and init.get("model"):
            self._saw(init.get("model"))
        return result.get("result") or ""

    @staticmethod
    def _error_text(result: dict, stderr: str = "") -> str:
        """A readable message for a failed `claude -p` result. Its "result" is often missing (null), so the
        subtype, any error list and stderr are used too; without them the message used to be just "None"."""
        parts = []
        body = result.get("result")
        if isinstance(body, str) and body.strip():
            parts.append(body.strip())
        for k in ("error", "errors", "message"):
            v = result.get(k)
            if v:
                parts.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)[:400])
        sub = str(result.get("subtype") or "")
        if sub and sub != "success":
            parts.append(f"(subtype {sub})")
        if stderr:
            parts.append(f"stderr: {stderr[:300]}")
        if not parts:
            parts.append("no message (subtype unknown)")
        return " ".join(parts)

    def _keep_failure(self, result: dict, proc) -> None:
        """Save the raw failed result next to the cache (llm/failures/), so the cause can be looked up later."""
        if not getattr(self, "cache_dir", None):
            return
        try:
            folder = os.path.join(self.cache_dir, "failures")
            os.makedirs(folder, exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}.json"
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                json.dump({"result": result, "returncode": proc.returncode, "stderr": (proc.stderr or "")[-4000:],
                           "stdout_tail": (proc.stdout or "")[-4000:]}, f, ensure_ascii=False, indent=1)
        except (OSError, TypeError, ValueError):
            pass

    @staticmethod
    def _events(out: str):
        """(start-up event, result event) from `json` (one object or a list) or `stream-json` (one per line)."""
        text = (out or "").strip()
        try:
            data = json.loads(text)
            events = data if isinstance(data, list) else [data]
        except ValueError:
            events = []
            for line in text.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
        init, result = {}, None
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                init = ev
            elif ev.get("type") == "result" or ("result" in ev and "is_error" in ev):
                result = ev
        return init, result

    def _billing(self, init: dict) -> None:
        if "apiKeySource" not in init:
            return
        src = init.get("apiKeySource")
        if not self.billed_to:
            self.billed_to = "your Claude plan (the account Claude Code is signed in to)" if src in self.PLAN \
                else f"an API key ({src}), not your Claude plan"
            log.info("Claude Code is billing %s", self.billed_to)
        if src not in self.PLAN and not self.allow_key():
            # Stop at the first call rather than spend credits for hours. "billing" and "login" make this final.
            raise LLMError(f"Claude Code is billing {self.billed_to}. To use your plan, open `claude`, type /login "
                           "and choose \"Claude account with subscription\". To allow it anyway, set "
                           "TASTECAL_ALLOW_KEY=1.")

    def _note(self, data: dict) -> None:
        """claude -p's JSON says which model ids answered (modelUsage) and what the call cost at API prices."""
        self.last = data
        try:
            self.cost_usd += float(data.get("total_cost_usd") or 0)
        except (TypeError, ValueError):
            pass
        usage = data.get("modelUsage")
        if isinstance(usage, dict) and usage:
            def weight(k):
                v = usage.get(k) if isinstance(usage.get(k), dict) else {}
                return (v.get("outputTokens") or 0, v.get("costUSD") or 0)
            self._saw(max(usage, key=weight))


class CodexCLILLM(LLM):
    """Uses the Codex command line (`codex exec`) with whatever account it is logged in to, so a ChatGPT
    subscription can drive the pipeline without an API key. Run `codex login` once and choose
    "Sign in with ChatGPT". Each call runs in an empty folder, read-only, and leaves no session behind."""

    name = "codex-cli"
    RULE = ("Answer the task below directly in your reply. Do not run commands, read files or edit anything; "
            "everything you need is in this message.")

    def __init__(self, cfg: Config, http: Optional[Http] = None):
        super().__init__(cfg.cache_dir)
        self.bin = shutil.which(os.environ.get("CODEX_BIN", "codex"))
        if not self.bin:
            raise LLMError("The `codex` command (Codex CLI) is not on your PATH. Install it "
                           "(npm install -g @openai/codex), run `codex login` and sign in with ChatGPT, then retry.")
        self.model = cfg.model           # resolved by make_llm: "" = Codex's own default
        self.effort = {"max": "xhigh"}.get(cfg.effort, cfg.effort)
        self.name = f"codex-cli:{self.model or 'default'}"
        self.billed_to = ""
        self.checked = False
        self.refusal = ""
        self.waits_for_limits = cfg.wait_for_limits
        self.max_wait = cfg.max_wait_hours * 3600

    # Set in the shell, these can make Codex charge an API key or another service instead of your ChatGPT plan.
    NOT_PLAN_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY")

    def _env(self) -> dict:
        env = dict(os.environ)
        if allow_key():
            return env
        dropped = [k for k in self.NOT_PLAN_ENV if k in env and env.pop(k) is not None]
        if dropped and not getattr(self, "_told_env", False):
            self._told_env = True
            log.info("left %s out of the Codex calls so they use your ChatGPT plan "
                     "(set TASTECAL_ALLOW_KEY=1 to keep them)", ", ".join(dropped))
        return env

    def _check_plan(self) -> None:
        """Before the first call, ask Codex how it is signed in. Stop unless it is ChatGPT (your plan). A refusal is
        repeated on every later call, so a step that skips a failed call cannot go on billing an API key."""
        if not self.checked:
            self.checked = True
            mode = codex_auth(self.bin, self._env())
            if mode in ("chatgpt", "apikey"):
                self.billed_to = ("your ChatGPT plan (the account Codex is signed in to)" if mode == "chatgpt"
                                  else "an API key, not your ChatGPT plan")
                log.info("Codex is billing %s", self.billed_to)
            if mode == "none":
                self.refusal = "Codex is not signed in to ChatGPT. Sign in from the page, or run `codex login`."
            elif mode == "apikey" and not allow_key():
                self.refusal = ("Codex is billing an API key, not your ChatGPT plan. Run `codex logout`, then `codex login` "
                                "and choose Sign in with ChatGPT. To allow it anyway, set TASTECAL_ALLOW_KEY=1.")
        if self.refusal:
            raise LLMError(self.refusal)

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        import tempfile
        self._check_plan()
        text = f"{system}\n\n{self.RULE}\n\n{prompt}"
        optional = ["--sandbox", "read-only", "--ephemeral"]
        for attempt in range(2):
            with tempfile.TemporaryDirectory(prefix="tastecal-codex-") as work:
                out = os.path.join(work, "answer.txt")
                cmd = [self.bin, "exec", "--skip-git-repo-check"] + optional + ["-o", out]
                if self.model:
                    cmd += ["-m", self.model]
                if self.effort:
                    cmd += ["-c", f'model_reasoning_effort="{self.effort}"']
                cmd.append("-")
                try:
                    proc = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                          timeout=900, cwd=work,
                                          env=self._env())
                except subprocess.TimeoutExpired:
                    raise LLMError("codex exec timed out after 15 minutes")
                answer = ""
                if os.path.exists(out):
                    with open(out, "r", encoding="utf-8", errors="replace") as f:
                        answer = f.read()
            if answer.strip():
                head = (proc.stderr or "") + "\n" + (proc.stdout or "")
                m = re.search(r"^\s*model:\s*(\S+)", head, re.M)
                e = re.search(r"^\s*reasoning effort:\s*(\S+)", head, re.M)
                self._saw(m.group(1) if m else (self.model or "codex default"), e.group(1) if e else None)
                return answer
            err = " ".join((proc.stderr or proc.stdout or "").split())
            if attempt == 0 and re.search(r"unexpected argument|unrecognized|unknown (option|argument)", err, re.I):
                optional = []          # an older Codex without --ephemeral: retry with the bare minimum
                continue
            break
        if re.search(r"not logged in|not signed in|login required|please (run )?.?codex login|unauthori[sz]ed|\b401\b", err, re.I):
            raise LLMError(f"Codex is not signed in to ChatGPT. Sign in from the page, or run `codex login`. Codex said: {err[-300:]}")
        if re.search(r"model", err, re.I) and re.search(r"not (found|supported|available)|does not exist|unknown", err, re.I):
            raise LLMError(f"Codex cannot use the model {self.model or '(default)'} with this account. Pick another version. "
                           f"Codex said: {err[-300:]}")
        raise LLMError(f"codex exec failed (exit {proc.returncode}). Codex said: {err[-400:] or 'nothing'}")


def make_llm(cfg: Config, http: Http) -> LLM:
    if cfg.provider in ("", "auto"):
        cfg.provider = detect_provider()
        log.info("no provider given: using %s, which runs on the plan you are signed in to",
                 "Claude Code" if cfg.provider == "claude-cli" else "Codex (ChatGPT)")
    from tastecal.core.config import resolve_choices
    resolve_choices(cfg)
    if cfg.provider == "anthropic":
        return AnthropicLLM(cfg, http)
    if cfg.provider == "openai":
        return OpenAICompatLLM(cfg, http)
    if cfg.provider == "claude-cli":
        return ClaudeCLILLM(cfg, http)
    if cfg.provider == "codex-cli":
        return CodexCLILLM(cfg, http)
    raise LLMError(f"Unknown provider {cfg.provider!r}; use auto, claude-cli, codex-cli, anthropic or openai")
