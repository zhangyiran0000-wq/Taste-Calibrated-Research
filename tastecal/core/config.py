"""Run settings. Every knob has a CLI flag; secrets come from the environment."""
from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field

def from_env(name: str, default: str = "") -> str:
    """$TASTECAL_<name>, else the older $DEEPANALYZE_<name>, else `default`."""
    return os.environ.get("TASTECAL_" + name) or os.environ.get("DEEPANALYZE_" + name) or default


# Keys and e-mail addresses tastecal reads from the environment.
SECRET_ENV = ("S2_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY",
              "GITHUB_TOKEN", "OPENALEX_MAILTO", "UNPAYWALL_EMAIL")
_QUOTES = set("\"'`“”‘’„‟‚‛«»‹›「」『』〝〞＂＇")


def clean_secret(value) -> str:
    """A key or e-mail address as people paste it, made usable. Full-width letters, digits and punctuation become
    plain ones (Unicode NFKC); spaces, invisible characters and quotes are dropped. TextEdit, for one, turns
    "abc" into “abc”, which no service accepts. Keys and addresses never contain any of these characters."""
    v = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(c for c in v if not c.isspace() and c not in _QUOTES and unicodedata.category(c) not in ("Cf", "Cc"))


def clean_env(environ=None) -> list:
    """Clean the keys in the environment in place (see clean_secret). Returns the names that changed."""
    env = os.environ if environ is None else environ
    changed = []
    for k in SECRET_ENV:
        v = env.get(k)
        if v is not None and clean_secret(v) != v:
            env[k] = clean_secret(v)
            changed.append(k)
    return changed


def _env_secret(name: str):
    return lambda: clean_secret(os.environ.get(name, ""))


@dataclass
class Config:
    # --- growth -----------------------------------------------------------
    budget: int = 30                 # max items in the final graph (seed included)
    max_rounds: int = 5              # expansion rounds after the seed
    expand_per_round: int = 4        # frontier items whose citations we open per round
    max_back_hops: int = 2           # how far back (references of references)
    max_forward_hops: int = 2        # how far forward (citers of citers)
    refs_to_classify: int = 25       # backward candidates sent to the LLM per anchor
    citers_to_classify: int = 30     # forward candidates sent to the LLM per anchor
    max_citations_scan: int = 1000   # citing papers scanned for context sentences
    problems_per_round: int = 4      # open problems turned into searches per round
    saturation_rounds: int = 2       # stop after N quiet rounds in a row
    saturation_ratio: float = 0.25   # a round is quiet when it opens at most this many new problems per work added
                                     # (after merging restatements of known problems)
    max_blogs: int = 5               # web items (blogs, reports) allowed in the graph
    use_openalex: bool = True        # top-cited citers via OpenAlex
    use_web: bool = True             # blog search (needs TAVILY_API_KEY or BRAVE_API_KEY)
    scope: str = ""                  # field limit, e.g. "autonomous driving": works from other fields (a generic
                                     # diffusion model, a backbone) are listed as borrowed, not mapped; "" = no limit
    popularity_weight: float = 0.5   # how much citation counts sway which items are admitted and opened;
                                     # lower it (e.g. 0.1) to give little-cited work a fairer chance

    # --- audit (attention vs contribution) ------------------------------------------
    assess: bool = True              # run the audit after synthesis (on by default; --no-assess turns it off)
    assess_max: int = 0              # works assessed, map items first, then the best runners-up; 0 = all of them
    assess_pool: int = 10            # runners-up (proposed but not admitted) added to the audit
    review: bool = True              # adversarial review (advocate, critic, judge) of flagged works
    citing_sample: int = 150         # citers sampled evenly to measure uptake

    # --- gates (claim vs delivery, reason, robustness, field reaction) ---------
    gates: bool = True               # run the gates after synthesis and the audit (on by default; --no-gates turns it off)
    gates_max: int = 0               # papers read; 0 = every paper on the map. With a limit: the seed and the most
                                     # connected works (see quality.pick_for_reading)
    taste_path: str = ""             # taste profile: a file path or a profile name (see taste/profiles.py); only picks treasures.
                                     # run uses ./taste.md if present
    papers_dir: str = "papers"       # your own PDFs or text files, named by id, arXiv id, DOI or title (see sources/fulltext.py)

    # --- writing ------------------------------------------------------------------
    language: str = "en"             # en | zh-CN: language of every text the reader sees
    polish: bool = True              # rewrite sentences that break the plain-language rules (see report/polish.py)
    outlook: bool = True             # what's next: active now, next steps, shared assumptions

    # --- LLM ----------------------------------------------------------------
    provider: str = "auto"           # auto | claude-cli | codex-cli | anthropic | openai. auto = the subscription
                                     # tool you are signed in to (Claude Code, else Codex); API keys only when asked
    model: str = ""
    base_url: str = ""               # for openai-compatible endpoints
    effort: str = ""                 # low | medium | high | xhigh | max; empty = DEFAULT_EFFORT; "default" = the model's own
    temperature: float = 0.2
    max_tokens: int = 4096
    wait_for_limits: bool = True     # claude-cli / codex-cli: at your plan's usage limit, wait for the reset and go on
    max_wait_hours: float = field(default_factory=lambda: float(from_env("MAX_WAIT_HOURS") or 192))

    # --- io -------------------------------------------------------------------
    cache_dir: str = ".tastecal_cache"
    fresh_days: float = field(default_factory=lambda: float(from_env("CACHE_DAYS") or 14))
                                     # search results and citer lists older than this are fetched again
    meta_days: float = 60.0          # paper records (citation counts, abstracts) older than this are fetched again
    refresh: bool = False            # --refresh: fetch every search and citer list again, whatever its age
    out_dir: str = "runs"
    verbose: bool = False

    # --- secrets (environment only) --------------------------------------------
    anthropic_api_key: str = field(default_factory=_env_secret("ANTHROPIC_API_KEY"))
    openai_api_key: str = field(default_factory=_env_secret("OPENAI_API_KEY"))
    s2_api_key: str = field(default_factory=_env_secret("S2_API_KEY"))
    openalex_mailto: str = field(default_factory=_env_secret("OPENALEX_MAILTO"))
    tavily_api_key: str = field(default_factory=_env_secret("TAVILY_API_KEY"))
    brave_api_key: str = field(default_factory=_env_secret("BRAVE_API_KEY"))

    def resolved_model(self) -> str:
        if self.model:
            return self.model
        env = from_env("MODEL")
        if env:
            return env
        if self.provider == "openai":
            return os.environ.get("OPENAI_MODEL", "gpt-6-astra")
        return "claude-opus-5-5"

    def resolved_base_url(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.provider == "openai":
            return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        return os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")


# What a run uses when you do not say: Opus 5.5 with Claude (Claude Code or the API), GPT-6 Astra with GPT (Codex or
# the API), at high effort. "default" as a model or effort means the tool's or the model's own default instead.
DEFAULT_MODEL = {"claude-cli": "claude-opus-5-5", "codex-cli": "gpt-6-astra"}   # the APIs: see Config.resolved_model
DEFAULT_EFFORT = "high"


def resolve_choices(cfg: "Config") -> None:
    """Fill in the model and effort you did not give (once per Config). An empty value takes $TASTECAL_MODEL /
    $TASTECAL_EFFORT, else the defaults above; "default" asks for the tool's or model's own and becomes ""."""
    import re
    if getattr(cfg, "_resolved", False):
        return
    cfg._resolved = True
    m = (cfg.model or "").strip()
    if m == "default":
        m = ""
    elif not m:
        m = from_env("MODEL", "") or DEFAULT_MODEL.get(cfg.provider, "")
    cfg.model = m
    e = (cfg.effort or "").strip()
    if e == "default":
        e = ""
    elif not e:
        e = from_env("EFFORT", "") or DEFAULT_EFFORT
        if cfg.provider == "openai" and not re.match(r"(gpt-[5-9]|o\d)", cfg.resolved_model()):
            e = ""                       # older chat models through an OpenAI-compatible endpoint have no effort
    cfg.effort = e


# Presets for people who run tastecal on their own subscription, with no API key. Each sets the tool, the model
# and the size of a run; a flag you give yourself always wins. Usage limits are per person, shared with the chat apps,
# and reset every five hours and every week, so the smaller plans get smaller runs (and wait more for resets).
PLANS = {
    "claude-pro": {"label": "Claude Pro", "provider": "claude-cli", "model": "claude-opus-5-5", "budget": 30},
    "claude-max": {"label": "Claude Max", "provider": "claude-cli", "model": "claude-opus-5-5", "budget": 50},
    "claude-team": {"label": "Claude Team, Standard seat", "provider": "claude-cli", "model": "claude-opus-5-5", "budget": 30},
    "claude-team-premium": {"label": "Claude Team, Premium seat", "provider": "claude-cli", "model": "claude-opus-5-5", "budget": 50},
    "chatgpt-free": {"label": "ChatGPT Free or Go", "provider": "codex-cli", "model": "default", "budget": 10},
    "chatgpt-plus": {"label": "ChatGPT Plus or Business", "provider": "codex-cli", "model": "gpt-6-astra", "budget": 25},
    "chatgpt-pro": {"label": "ChatGPT Pro", "provider": "codex-cli", "model": "gpt-6-astra", "budget": 50},
}


def plan_settings(name: str) -> dict:
    """The preset for a plan name (see PLANS). Raises ValueError for an unknown name."""
    key = (name or "").strip().lower()
    if key not in PLANS:
        raise ValueError(f"Unknown plan {name!r}. Choose one of: {', '.join(PLANS)}")
    return dict(PLANS[key], name=key)

