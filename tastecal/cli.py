"""Command line.

  python -m tastecal run "arXiv:2106.09685" --budget 30
  python -m tastecal assess runs/lora/graph.json
  python -m tastecal gates runs/lora/graph.json --taste taste.md
  python -m tastecal render runs/lora/graph.json
  python -m tastecal lint runs/lora/graph.json          # plain-language check, no LLM
  python -m tastecal profiles                           # taste profiles you can pass to --taste
  python -m tastecal serve                              # a local web page to start runs and open reports
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from tastecal import __version__
from tastecal.core.config import PLANS, Config, from_env

HERE = os.path.dirname(os.path.abspath(__file__))
S2_KEY_URL = "https://www.semanticscholar.org/product/api#api-key-form"
PROVIDERS = ["auto", "claude-cli", "codex-cli", "anthropic", "openai"]
PROVIDER_DEFAULT = from_env("PROVIDER") or "auto"
EFFORTS = ["low", "medium", "high", "xhigh", "max", "default"]
EFFORT_HELP = "how hard the model thinks (default: high; 'default' = the model's own setting)"
PROVIDER_HELP = ("auto (default): your subscription, through Claude Code if it is installed, else Codex. "
                 "claude-cli: your Claude plan through Claude Code. codex-cli: your ChatGPT plan through Codex. "
                 "anthropic / openai: an API key, only if you ask for it")


def folder_slug(seed: str, n: int = 40) -> str:
    """The default run folder for a seed. Plain letters and digits as before; Chinese, Japanese and Korean are kept,
    so a seed given as a Chinese title gets its own folder instead of runs/item."""
    import re
    import unicodedata
    from tastecal.core.model import slugify
    s = unicodedata.normalize("NFKC", seed or "").lower()
    s = re.sub(r"https?://", "", s)
    wide = re.sub(r"[^a-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "-", s).strip("-")[:n].strip("-")
    return wide if re.search(r"[^a-z0-9-]", wide) else slugify(unicodedata.normalize("NFKC", seed or ""), max_len=n)


def resolve_plan(a: argparse.Namespace) -> dict:
    """Fill the tool, model and size from --plan (or $TASTECAL_PLAN) wherever you did not set them yourself."""
    from tastecal.core.config import plan_settings
    name = getattr(a, "plan", None) or ""
    preset = plan_settings(name) if name else {}
    if preset:
        if a.provider in (None, "", "auto"):
            a.provider = preset["provider"]
        if not a.model and preset.get("model") and a.provider == preset["provider"]:
            a.model = preset["model"]
        if a.budget is None:
            a.budget = preset["budget"]
    if a.budget is None:
        a.budget = 30
    return preset


def _setup_logging(verbose: bool, logfile: str = "") -> None:
    handlers = [logging.StreamHandler(sys.stderr)]
    if logfile:
        os.makedirs(os.path.dirname(os.path.abspath(logfile)), exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S",
                        handlers=handlers, force=True)


def cmd_run(a: argparse.Namespace) -> int:
    from tastecal.lineage.grow import Grower
    from tastecal.core.http import Http
    from tastecal.core.llm import LLMError, make_llm
    from tastecal.core.model import slugify
    from tastecal.report.render import write_report
    from tastecal.core.schema import validate
    from tastecal.sources.openalex import OpenAlex
    from tastecal.sources.semantic_scholar import SemanticScholar
    from tastecal.sources.web import WebSearch
    from tastecal.lineage.synthesize import synthesize
    from tastecal.taste.profiles import default_spec, load_profile
    from tastecal.report import polish as style

    try:
        preset = resolve_plan(a)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    cfg = Config(budget=a.budget, max_rounds=a.rounds, expand_per_round=a.expand_per_round,
                 max_back_hops=a.max_back, max_forward_hops=a.max_forward, max_blogs=a.max_blogs,
                 use_openalex=not a.no_openalex, use_web=not a.no_web, provider=a.provider,
                 model=a.model or "", base_url=a.base_url or "", cache_dir=a.cache_dir, verbose=a.verbose,
                 popularity_weight=a.popularity_weight, assess=a.assess, assess_max=a.assess_max,
                 scope=" ".join((a.scope or "").split()),
                 review=not a.no_review, gates=a.gates, gates_max=a.gates_max,
                 taste_path=a.taste or default_spec(), papers_dir=a.papers_dir, language=a.language,
                 polish=not a.no_polish, outlook=not a.no_outlook, effort=a.effort or "",
                 wait_for_limits=not a.no_wait, refresh=getattr(a, "refresh", False))
    out = a.out or os.path.join("runs", folder_slug(a.seed))
    os.makedirs(out, exist_ok=True)
    _setup_logging(a.verbose, os.path.join(out, "run.log"))
    if getattr(a, "also_log", ""):
        h = logging.FileHandler(a.also_log, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(h)
    log = logging.getLogger("tastecal")
    if preset:
        log.info("plan preset %s: %s, %s, up to %d papers", preset["label"], cfg.provider, cfg.model or "the tool's default model",
                 cfg.budget)
    if not cfg.s2_api_key:
        log.warning("No S2_API_KEY: without a Semantic Scholar key most searches are refused (HTTP 429), so the map finds "
                    "far fewer papers. The key is free: %s . Set it (export S2_API_KEY=...) and start again.", S2_KEY_URL)

    http = Http(cfg.cache_dir, min_interval=0.0 if cfg.s2_api_key else 1.1, fresh_days=cfg.fresh_days,
                meta_days=cfg.meta_days, refresh=cfg.refresh)
    gaps_file = os.path.join(out, "gaps.json")
    if a.resume:
        n_gaps = http.load_gaps(gaps_file)
        if not n_gaps and not os.path.exists(gaps_file):      # a run from before gaps files: read its log
            n_gaps = http.gaps_from_log(os.path.join(out, "run.log"))
        if n_gaps:
            log.info("resume: %d downloads the earlier attempt did not get (HTTP 429, network) are tried again live",
                     n_gaps)
    else:
        http.gaps_path = gaps_file
        http._save_gaps()            # a fresh run starts with no gaps
    try:
        llm = make_llm(cfg, http)
    except LLMError as e:
        log.error("%s", e)
        return 2
    llm.system_note = style.system_note(cfg.language)
    try:
        taste_name, taste_text, _ = load_profile(cfg.taste_path)
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    s2 = SemanticScholar(http, cfg.s2_api_key, cfg.max_citations_scan, cfg.popularity_weight)
    oa = OpenAlex(http, cfg.openalex_mailto) if cfg.use_openalex else None
    web = WebSearch(http, cfg.tavily_api_key, cfg.brave_api_key)
    if cfg.use_web and not web.available:
        log.info("No TAVILY_API_KEY or BRAVE_API_KEY: skipping blog search")

    log.info("tastecal %s · model %s · effort %s · budget %d", __version__, llm.name, llm.effort_label(), cfg.budget)
    if a.resume:
        # Same settings, same downloads, same answers: the growth replays from the caches without asking
        # the model again, then the run goes on live from where it stopped.
        http.replay = True
        log.info("resuming: answers and downloads from the earlier attempt are reused; only new work is sent to the model")
    grower = Grower(cfg, s2, llm, openalex=oa, web=web).run(a.seed)
    if a.resume:
        http.replay = False
        log.info("resume: map rebuilt from saved work (%d answers reused, %d new model calls so far)",
                 llm.cache_hits, llm.calls)
    log.info("grown to %d items, %d links, %d problems", len(grower.nodes), len(grower.edges),
             len(grower.ledger.problems))
    graph = synthesize(grower, llm, a.seed)
    graph["meta"]["sources"] = ["Semantic Scholar"] + (["OpenAlex"] if oa else []) + (["web search"] if web.available and cfg.use_web else [])
    graph["meta"]["language"] = cfg.language
    if cfg.outlook:
        from tastecal.lineage.outlook import build as build_outlook
        build_outlook(graph, llm)
    # One careful read per paper, shared by the gates and the audit.
    readings, keeper = {}, None
    items = {n.item.id: n.item for n in grower.nodes.values()}
    if cfg.gates:
        from tastecal.judge.gates import Gatekeeper
        keeper = Gatekeeper(cfg, llm, http, profile=taste_text, profile_name=taste_name)
        readings = keeper.read(graph, items)
    if cfg.assess:
        from tastecal.judge.audit import Auditor, audit, targets_from_grower
        targets, pool = targets_from_grower(grower, graph)
        log.info("audit: %d map items and %d runners-up", len(targets), len(pool))
        from tastecal.taste.profiles import rated_papers
        audit(graph, targets, Auditor(cfg, s2, llm, http, openalex=oa, reader=keeper.gate if keeper else None),
              pool, readings, anchors=rated_papers(taste_text), reference=grower.attention_reference())
    if keeper is not None:
        from tastecal.judge.gates import summary
        keeper.run(graph, items, raw=readings)
        if taste_text:      # how well the taste profile predicts your own ratings (needs papers you rated)
            from tastecal.taste.calibration import taste_check
            from tastecal.core.model import norm_title
            anchors = ((graph.get("audit") or {}).get("calibration") or {}).get("anchors") or []
            check = taste_check(taste_text, s2, llm, evidence={norm_title(r["title"]): r["evidence"] for r in anchors
                                                               if r.get("title") and r.get("evidence")})
            if check:
                graph["gates"]["taste_check"] = check
        for line in summary(graph):
            log.info("%s", line)
    if cfg.polish:
        stats = style.polish(graph, llm, cfg.language)
        log.info("plain language: %d texts flagged, %d rewritten, %d still flagged",
                 stats["flagged"], stats["rewritten"], stats["still_flagged"])
    from tastecal.judge.quality import note_coverage
    note_coverage(graph, cfg.gates_max, cfg.assess_max)   # after polish: it lists names on purpose
    graph["meta"]["model"] = llm.describe()       # the model id the service reported, not only the alias asked for
    graph["meta"]["usage"] = llm.usage()
    errs = validate(graph)
    for e in errs:
        log.warning("schema: %s", e)
    gpath = os.path.join(out, "graph.json")
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    rpath = write_report(graph, os.path.join(out, "report.html"))
    log.info("LLM: %s", llm.describe())
    log.info("LLM usage: %s", llm.usage())
    if http.gaps or http.filled or http.stale_used:
        log.info("downloads: %d gaps filled, %d still missing (listed in %s; `resume` tries them again), "
                 "%d old cached copies used after a failed refresh", http.filled, len(http.gaps), gaps_file,
                 http.stale_used)
    print(f"\nWrote {gpath}\nWrote {rpath}")
    return 0


def cmd_assess(a: argparse.Namespace) -> int:
    """Audit an existing graph.json: re-find each work, gather evidence, score blind, review flagged."""
    from tastecal.judge.audit import Auditor, audit
    from tastecal.core.http import Http
    from tastecal.core.llm import LLMError, make_llm
    from tastecal.report.render import write_report
    from tastecal.core.schema import validate
    from tastecal.sources.semantic_scholar import SemanticScholar

    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    out = os.path.dirname(os.path.abspath(a.out or a.graph))
    _setup_logging(a.verbose, os.path.join(out, "assess.log"))
    log = logging.getLogger("tastecal")
    cfg = Config(provider=a.provider, model=a.model or "", base_url=a.base_url or "", cache_dir=a.cache_dir,
                 assess=True, assess_max=a.assess_max, review=not a.no_review, verbose=a.verbose, effort=a.effort or "")
    http = Http(cfg.cache_dir, min_interval=0.0 if cfg.s2_api_key else 1.1)
    try:
        llm = make_llm(cfg, http)
    except LLMError as e:
        log.error("%s", e)
        return 2
    s2 = SemanticScholar(http, cfg.s2_api_key, cfg.max_citations_scan)

    def target(row: dict):
        try:
            item = s2.resolve(row.get("url") or row["title"])
        except Exception as e:  # not found: skip it
            log.warning("could not find %s: %s", row.get("short") or row.get("title"), e)
            return None
        item.id = row["id"]
        return {"item": item, "card": row.get("card") or {}, "short": row.get("short", ""),
                "near": row.get("near", ""), "reason": row.get("reason", "")}

    targets = [t for t in (target(n) for n in graph["nodes"] if n.get("kind", "paper") == "paper") if t]
    pool = [t for t in (target(n) for n in graph.get("pool", [])) if t] if graph.get("pool") else None
    if a.assess_max:      # a limit: the seed and the most connected papers, not simply the oldest
        from tastecal.judge.quality import pick_for_reading
        keep = {n["id"] for n in pick_for_reading([n for n in graph["nodes"] if n.get("kind", "paper") == "paper"],
                                                  (graph.get("meta") or {}).get("seed"), graph.get("edges", []), a.assess_max)}
        targets = [t for t in targets if t["item"].id in keep]
    from tastecal.taste.profiles import load_profile, rated_papers
    try:
        profile = load_profile(a.taste)[1] if a.taste else ((graph.get("gates") or {}).get("taste_profile") or "")
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    audit(graph, targets, Auditor(cfg, s2, llm, http), pool, anchors=rated_papers(profile))
    from tastecal.judge.quality import note_coverage
    note_coverage(graph, 0, a.assess_max, only=("audit",))
    for e in validate(graph):
        log.warning("schema: %s", e)
    gpath = a.out or a.graph
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    rpath = write_report(graph, os.path.join(os.path.dirname(os.path.abspath(gpath)), "report.html"))
    log.info("LLM usage: %s", llm.usage())
    print(f"\nWrote {gpath}\nWrote {rpath}")
    return 0


def cmd_gates(a: argparse.Namespace) -> int:
    """Gate an existing graph.json: claim vs delivery, reason, robustness, field reaction, then fold and re-render.
    With --raw, the gate answers come from a file instead of an LLM (no key needed)."""
    from tastecal.judge.gates import GateThresholds, Gatekeeper, apply_gates, load_raw, summary
    from tastecal.report.render import write_report
    from tastecal.core.schema import validate

    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    out = os.path.dirname(os.path.abspath(a.out or a.graph))
    _setup_logging(a.verbose, os.path.join(out, "gates.log"))
    log = logging.getLogger("tastecal")
    th = GateThresholds(attractive=a.attractive)
    from tastecal.taste.profiles import load_profile
    try:
        taste_name, taste_text, _ = load_profile(a.taste or "")
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    if a.raw:
        raw = load_raw(a.raw)
        taste = {k: v["taste"] for k, v in raw.items() if isinstance(v.get("taste"), dict)}
        apply_gates(graph, raw, taste, a.today, th, taste_name)
    else:
        from tastecal.core.http import Http
        from tastecal.core.llm import LLMError, make_llm
        cfg = Config(provider=a.provider, model=a.model or "", base_url=a.base_url or "", cache_dir=a.cache_dir,
                     gates=True, gates_max=a.gates_max, taste_path=a.taste or "", verbose=a.verbose,
                     papers_dir=a.papers_dir, effort=a.effort or "")
        http = Http(cfg.cache_dir, min_interval=1.1)
        try:
            llm = make_llm(cfg, http)
        except LLMError as e:
            log.error("%s", e)
            return 2
        from tastecal.report import polish as style
        llm.system_note = style.system_note((graph.get("meta") or {}).get("language", "en"))
        Gatekeeper(cfg, llm, http, today=a.today, th=th, profile=taste_text, profile_name=taste_name).run(graph)
        from tastecal.judge.quality import note_coverage
        note_coverage(graph, a.gates_max, 0, only=("gates",))
        log.info("LLM usage: %s", llm.usage())
    for line in summary(graph):
        log.info("%s", line)
    for e in validate(graph):
        log.warning("schema: %s", e)
    gpath = a.out or a.graph
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    graph["gates"]["view"] = a.folded
    rpath = write_report(graph, os.path.join(os.path.dirname(os.path.abspath(gpath)), "report.html"))
    print(f"\nWrote {gpath}\nWrote {rpath}")
    return 0


def cmd_render(a: argparse.Namespace) -> int:
    from tastecal.report.render import write_report
    from tastecal.core.schema import validate
    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    errs = validate(graph)
    for e in errs:
        print("schema:", e, file=sys.stderr)
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.graph)), "report.html")
    if graph.get("gates"):
        graph["gates"]["view"] = a.folded
    write_report(graph, out, fragment=a.fragment)
    print(f"Wrote {out}" + (f" ({len(errs)} schema warnings)" if errs else ""))
    return 0


def cmd_lint(a: argparse.Namespace) -> int:
    """Plain-language check of a graph's text. No LLM."""
    from tastecal.report import polish as style
    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    rows = style.lint_graph(graph)
    rep = style.report(graph)
    for r in rows[: a.max]:
        print(f"- {r['path']}: " + " | ".join(r["issues"]))
    print(f"\n{rep['flagged']} of {rep['texts']} texts break the plain-language rules. By section: {rep['by_section']}")
    return 0


def cmd_polish(a: argparse.Namespace) -> int:
    """Rewrite the flagged texts in plain language (LLM), and optionally add the outlook."""
    from tastecal.report import polish as style
    from tastecal.core.http import Http
    from tastecal.core.llm import LLMError, make_llm
    from tastecal.report.render import write_report
    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    _setup_logging(a.verbose)
    lang = (graph.get("meta") or {}).get("language", "en")
    cfg = Config(provider=a.provider, model=a.model or "", base_url=a.base_url or "", cache_dir=a.cache_dir,
                 effort=a.effort or "")
    try:
        llm = make_llm(cfg, Http(cfg.cache_dir))
    except LLMError as e:
        print(e, file=sys.stderr)
        return 2
    llm.system_note = style.system_note(lang)
    if a.outlook:
        from tastecal.lineage.outlook import build as build_outlook
        build_outlook(graph, llm, a.today)
    stats = style.polish(graph, llm, lang)
    print(f"{stats['flagged']} flagged, {stats['rewritten']} rewritten, {stats['still_flagged']} still flagged")
    gpath = a.out or a.graph
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    write_report(graph, os.path.join(os.path.dirname(os.path.abspath(gpath)), "report.html"))
    print(f"Wrote {gpath}")
    return 0


def cmd_profiles(a: argparse.Namespace) -> int:
    from tastecal.taste.profiles import list_profiles, load_profile
    for name, path, kind in list_profiles():
        title = load_profile(path)[0]
        print(f"{name:14} {kind:7} {title}  ({path})")
    print("\nPass one with --taste <name>, or give a path. Your own go in ./profiles/.")
    return 0


def cmd_resume(a: argparse.Namespace) -> int:
    """Continue a run folder made by `serve` (it has request.json) with exactly the same settings."""
    import datetime as dt
    folder = a.folder.rstrip("/")
    try:
        with open(os.path.join(folder, "request.json"), "r", encoding="utf-8") as f:
            req = json.load(f)
    except (OSError, ValueError):
        print(f"No request.json in {folder}. Re-run the original `run` command with --resume and the same --out.")
        return 2
    argv = ["run", req["seed"], "--budget", str(req.get("budget") or 30), "--provider", req.get("provider") or "auto",
            "--out", folder, "--language", req.get("language") or "en", "--resume"]
    taste = os.path.join(folder, "taste.md")
    if os.path.isfile(taste):
        argv += ["--taste", taste]
    # Exactly what the first attempt used, so its saved answers match. An empty value in an older request.json
    # meant the tool's own model or effort, which is "default" now that empty means Opus 5.5 / Astra at high effort.
    argv += ["--model", req.get("model") or "default", "--effort", req.get("effort") or "default"]
    if req.get("scope"):
        argv += ["--scope", req["scope"]]
    status = os.path.join(folder, "status.json")
    served = bool(from_env("SERVED"))

    def put(**kw):
        try:
            with open(status, "r", encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        st.update(kw)
        with open(status, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)

    now = lambda: dt.datetime.now().isoformat(timespec="seconds")
    if not served:      # started by hand: keep the page's view of this run up to date
        put(state="running", pid=os.getpid(), resumed=now(), returncode=None, finished=None)
        argv += ["--also-log", os.path.join(folder, "console.log")]
    code = 1
    try:
        code = main(argv)
        return code
    finally:
        if not served:
            done = code == 0 and os.path.exists(os.path.join(folder, "report.html"))
            put(state="done" if done else "failed", returncode=code, finished=now())


BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY")


def cmd_doctor(a: argparse.Namespace) -> int:
    """One tiny live call: which model answers, at what effort, who is billed, and how long a call takes."""
    import subprocess
    import time
    from tastecal.core.http import Http
    from tastecal.core.llm import LLMError, make_llm
    from tastecal.core.llm import detect_provider
    if a.provider in ("", "auto"):
        try:
            a.provider = detect_provider()
        except LLMError as e:
            print(e)
            return 1
        print(f"No provider given: using {a.provider} (your subscription).")
    cfg = Config(provider=a.provider, model=a.model or "", cache_dir=None, effort=a.effort or "")
    print(f"Provider: {a.provider}   asked for model: {a.model or '(default)'}   effort: {a.effort or '(model default)'}")
    from tastecal.sources.fulltext import pdf_reader
    print("PDF reader: " + (pdf_reader() or "none, so papers outside arXiv are read from the abstract. "
                                            "Install one: brew install poppler (or pip install pypdf)"))
    s2 = os.environ.get("S2_API_KEY", "")
    print("Semantic Scholar key: " + (f"set, and {check_s2_key(s2)}" if s2 else
                                      f"not set. Searches will be refused often; a free key: {S2_KEY_URL}"))
    tool = {"claude-cli": "claude", "codex-cli": "codex"}.get(a.provider)
    if tool:
        exe = __import__("shutil").which(os.environ.get(tool.upper() + "_BIN", tool))
        try:
            ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip() if exe else ""
        except (OSError, subprocess.SubprocessError):
            ver = ""
        print(f"{tool}: {exe or 'not found'} {ver}")
    found = [k for k in BILLING_ENV if os.environ.get(k)]
    if found:
        print("Set in this shell (these can change who is billed): " + ", ".join(found))
        if a.provider == "claude-cli" and any(k in found for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                                                     "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                                                                     "CLAUDE_CODE_USE_VERTEX")):
            print("  tastecal leaves these out of its Claude Code calls, so they use your plan "
                  "(set TASTECAL_ALLOW_KEY=1 to keep them).")
    try:
        llm = make_llm(cfg, Http(None))
        t = time.time()
        out = llm.complete("You answer in one word.", "Reply with the single word OK.", 50)
        took = time.time() - t
    except LLMError as e:
        print(f"\nThe test call failed: {e}")
        return 1
    print(f"\nAnswer: {out.strip()[:40]!r}   in {took:.0f} s")
    print(f"Model that answered: {llm.model_used() or '(not reported)'}   effort: {llm.effort_label()}")
    billed = getattr(llm, "billed_to", "")
    if billed:
        print(f"Billed to: {billed}")
    last = getattr(llm, "last", {}) or {}
    u = last.get("usage") or {}
    if u:
        sent = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
        print(f"Tokens for this one-word test: {sent:,} in, {u.get('output_tokens') or 0:,} out"
              + (f"; about ${last.get('total_cost_usd'):.4f} at API prices" if last.get("total_cost_usd") else ""))
        if last.get("duration_ms") and last.get("duration_api_ms") is not None:
            print(f"Time: {last['duration_ms'] / 1000:.0f} s in total, {last['duration_api_ms'] / 1000:.0f} s waiting for the model")
    if a.provider == "codex-cli" and tool and exe:
        try:
            st = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=30)
            print("Codex sign-in: " + " ".join((st.stdout + st.stderr).split())[:200])
        except (OSError, subprocess.SubprocessError):
            pass
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from tastecal.app.serve import serve
    return serve(a.host, a.port, a.dir, open_browser=not a.no_browser)


def _utf8_streams() -> None:
    """Write the console in UTF-8 (unknown characters replaced), whatever the system code page. On a Chinese Windows
    the default is GBK, so a captured console.log read as UTF-8 showed "\ufffd", and characters GBK lacks could end a
    run with UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _utf8_streams()
    p = argparse.ArgumentParser(prog="tastecal", description="Taste-Calibrated Research: map one paper's lineage, judge what each work delivers, calibrated to your taste.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="grow a lineage graph from a seed and render the report")
    r.add_argument("seed", help='arXiv id or URL, DOI, Semantic Scholar id, or a paper title in quotes')
    r.add_argument("--budget", type=int, default=None, help="max items in the graph (default 30, or your --plan's)")
    r.add_argument("--rounds", type=int, default=5, help="max expansion rounds (default 5)")
    r.add_argument("--expand-per-round", type=int, default=4, help="frontier items opened per round (default 4)")
    r.add_argument("--max-back", type=int, default=2, help="hops backward from the seed (default 2)")
    r.add_argument("--max-forward", type=int, default=2, help="hops forward from the seed (default 2)")
    r.add_argument("--max-blogs", type=int, default=5, help="web items allowed (default 5)")
    r.add_argument("--provider", choices=PROVIDERS, default=PROVIDER_DEFAULT, help=PROVIDER_HELP)
    r.add_argument("--plan", choices=sorted(PLANS), default=from_env("PLAN") or None,
                   help="your subscription, which sets the tool, model and number of papers to suit its usage limits "
                        "(your own --provider, --model and --budget win; default: $TASTECAL_PLAN)")
    r.add_argument("--no-wait", action="store_true",
                   help="stop when your plan's usage limit is reached, instead of waiting for the reset and going on")
    r.add_argument("--model", help="model id (default: $TASTECAL_MODEL, else claude-opus-5-5 for Claude and gpt-6-astra "
                                   "for GPT; 'default' = the tool's own choice)")
    r.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    r.add_argument("--also-log", default="", help=argparse.SUPPRESS)
    r.add_argument("--resume", action="store_true",
                   help="continue a run that stopped: give the same seed, settings and --out; saved answers are reused")
    r.add_argument("--base-url", help="OpenAI-compatible base URL, e.g. https://api.deepseek.com/v1")
    r.add_argument("--scope", default="", help='limit the map to a field, e.g. "autonomous driving". Works from other '
                   'fields (a generic diffusion model, a backbone) are listed as borrowed instead of mapped, read or audited')
    r.add_argument("--no-openalex", action="store_true", help="skip OpenAlex (top-cited citers)")
    r.add_argument("--no-web", action="store_true", help="skip blog search")
    r.add_argument("--popularity-weight", type=float, default=0.5,
                   help="how much citation counts sway admission (default 0.5; try 0.1 for a less popularity-driven map)")
    r.add_argument("--assess", action="store_true", default=True, help="audit attention vs contribution (on by default)")
    r.add_argument("--no-assess", dest="assess", action="store_false", help="skip the audit")
    r.add_argument("--assess-max", type=int, default=0, help="works to audit (default 0 = every paper on the map, plus the runners-up)")
    r.add_argument("--no-review", action="store_true", help="skip the adversarial review of flagged works")
    r.add_argument("--gates", action="store_true", default=True, help="run the gates: fold works that do not hold up, list treasures (on by default)")
    r.add_argument("--no-gates", dest="gates", action="store_false", help="skip the gates")
    r.add_argument("--gates-max", type=int, default=0, help="papers to read through the gates (default 0 = every paper on the map)")
    r.add_argument("--taste", help="taste profile: a file path or a profile name such as practitioner (see `profiles`; default: ./taste.md if it exists)")
    r.add_argument("--papers-dir", default="papers", help="folder with your own PDFs or text files of the papers (default ./papers)")
    r.add_argument("--language", default=from_env("LANGUAGE", "en"), help="en or zh-CN: language of the report text (default en)")
    r.add_argument("--no-polish", action="store_true", help="skip the plain-language rewrite of flagged sentences")
    r.add_argument("--no-outlook", action="store_true", help="skip the What's next section")
    r.add_argument("--cache-dir", default=".tastecal_cache")
    r.add_argument("--refresh", action="store_true",
                   help="fetch every search result and citer list again, however recent the cached copy "
                        "(by default they are re-fetched after $TASTECAL_CACHE_DAYS, 14 days)")
    r.add_argument("--out", help="output folder (default runs/<seed>)")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(func=cmd_run)

    s_ = sub.add_parser("assess", help="audit attention vs contribution for an existing graph.json")
    s_.add_argument("graph")
    s_.add_argument("-o", "--out", help="write the audited graph here (default: overwrite the input)")
    s_.add_argument("--assess-max", type=int, default=0, help="works to audit (default 0 = every paper on the map, plus the runners-up)")
    s_.add_argument("--no-review", action="store_true", help="skip the adversarial review of flagged works")
    s_.add_argument("--taste", help="taste profile whose rated papers set 'your scale' (default: the one saved with the gates)")
    s_.add_argument("--provider", choices=PROVIDERS, default=PROVIDER_DEFAULT, help=PROVIDER_HELP)
    s_.add_argument("--model")
    s_.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    s_.add_argument("--base-url")
    s_.add_argument("--cache-dir", default=".tastecal_cache")
    s_.add_argument("-v", "--verbose", action="store_true")
    s_.set_defaults(func=cmd_assess)

    q = sub.add_parser("gates", help="gate an existing graph.json (claim vs delivery, reason, robustness, field reaction)")
    q.add_argument("graph")
    q.add_argument("-o", "--out", help="write the gated graph here (default: overwrite the input)")
    q.add_argument("--raw", help="JSON file of gate answers keyed by node id; skips the LLM")
    q.add_argument("--taste", help="taste profile: a file path or a profile name (see `profiles`)")
    q.add_argument("--papers-dir", default="papers", help="folder with your own PDFs or text files of the papers")
    q.add_argument("--attractive", type=float, default=0.6, help="taste score that counts as attractive (default 0.6)")
    q.add_argument("--gates-max", type=int, default=0, help="papers to read through the gates (default 0 = every paper on the map)")
    q.add_argument("--today", help="YYYY-MM to judge recency against (default: this month)")
    q.add_argument("--folded", choices=["hide", "show"], default="hide", help="whether the report opens with side branches folded (default) or shown")
    q.add_argument("--provider", choices=PROVIDERS, default=PROVIDER_DEFAULT, help=PROVIDER_HELP)
    q.add_argument("--model")
    q.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    q.add_argument("--base-url")
    q.add_argument("--cache-dir", default=".tastecal_cache")
    q.add_argument("-v", "--verbose", action="store_true")
    q.set_defaults(func=cmd_gates)

    d = sub.add_parser("render", help="render a graph.json into report.html")
    d.add_argument("graph")
    d.add_argument("-o", "--out")
    d.add_argument("--fragment", action="store_true", help="body only, no <html>/<head> wrapper")
    d.add_argument("--folded", choices=["hide", "show"], default="hide", help="open with side branches folded (default) or shown")
    d.set_defaults(func=cmd_render)

    li = sub.add_parser("lint", help="check a graph's text against the plain-language rules (no LLM)")
    li.add_argument("graph")
    li.add_argument("--max", type=int, default=40, help="rows to print (default 40)")
    li.set_defaults(func=cmd_lint)

    po = sub.add_parser("polish", help="rewrite flagged sentences in plain language; --outlook also adds What's next")
    po.add_argument("graph")
    po.add_argument("-o", "--out")
    po.add_argument("--outlook", action="store_true", help="also build the What's next section")
    po.add_argument("--today", help="YYYY-MM for the active-now window (default: this month)")
    po.add_argument("--provider", choices=PROVIDERS, default=PROVIDER_DEFAULT, help=PROVIDER_HELP)
    po.add_argument("--model")
    po.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    po.add_argument("--base-url")
    po.add_argument("--cache-dir", default=".tastecal_cache")
    po.add_argument("-v", "--verbose", action="store_true")
    po.set_defaults(func=cmd_polish)

    pr = sub.add_parser("profiles", help="list the taste profiles you can pass to --taste")
    pr.set_defaults(func=cmd_profiles)

    rs = sub.add_parser("resume", help="continue a run that stopped (a folder in runs/), reusing everything it already did")
    rs.add_argument("folder", help="the run's folder, e.g. runs/my-seed-20261015-1548")
    rs.set_defaults(func=cmd_resume)

    dr = sub.add_parser("doctor", help="one tiny live call: which model answers, at what effort, and who is billed")
    dr.add_argument("--provider", choices=PROVIDERS, default=PROVIDER_DEFAULT, help=PROVIDER_HELP)
    dr.add_argument("--model", help="model id or alias, e.g. opus or claude-opus-5-5")
    dr.add_argument("--effort", choices=EFFORTS)
    dr.set_defaults(func=cmd_doctor)

    sv = sub.add_parser("serve", help="open a local web page to start runs and open reports")
    sv.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765; the next free one is used)")
    sv.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    sv.add_argument("--dir", default=".", help="folder that holds runs/, examples/ and profiles/ (default: here)")
    sv.add_argument("--no-browser", action="store_true", help="do not open a browser")
    sv.set_defaults(func=cmd_serve)

    a = p.parse_args(argv)
    tidy_keys()
    return a.func(a)


def tidy_keys() -> None:
    """Keys pasted with curly quotes, full-width characters or stray spaces still work (see config.clean_secret)."""
    from tastecal.core.config import SECRET_ENV, clean_env
    for k in clean_env():
        print(f"Note: {k} had quotes, spaces or full-width characters in it (TextEdit adds curly quotes, for one). "
              "tastecal uses it without them; tidy the line in ~/.zshrc when you can.", file=sys.stderr)
    for k in SECRET_ENV:
        if any(ord(ch) > 127 for ch in os.environ.get(k, "")):
            print(f"Warning: {k} still has characters no key contains (for example Chinese punctuation). Check it.",
                  file=sys.stderr)


def check_s2_key(key: str) -> str:
    """One tiny Semantic Scholar request with the key: 'works', 'rejected (...)', or why it could not tell."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request("https://api.semanticscholar.org/graph/v1/paper/arXiv:1706.03762?fields=title",
                                 headers={"x-api-key": key, "User-Agent": "tastecal doctor"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return "works" if r.status == 200 else f"answered HTTP {r.status}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return f"rejected (HTTP {e.code}). Check that you copied the whole key"
        if e.code == 429:
            return "accepted, but rate-limited just now (HTTP 429); try again in a minute"
        return f"could not tell (HTTP {e.code})"
    except Exception as e:  # offline, proxy, DNS
        return f"could not tell ({type(e).__name__}: {e})"
