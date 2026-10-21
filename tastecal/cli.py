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
from typing import List, Optional, Tuple

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


SAVED_SETTINGS = ("provider", "model", "effort", "cache_dir", "papers_dir", "language", "use_openalex",
                  "fresh_days", "meta_days", "max_citations_scan", "citing_sample", "popularity_weight")


def save_settings(graph: dict, cfg: Config) -> None:
    """Persist reproducible public settings, never credentials or authenticated endpoint URLs."""
    from urllib.parse import urlsplit
    from tastecal.sources.fulltext import papers_folder
    settings = {key: getattr(cfg, key) for key in SAVED_SETTINGS}
    settings["papers_dir"] = papers_folder(cfg.papers_dir)
    for key in ("cache_dir", "papers_dir"):
        if settings[key]:
            settings[key] = os.path.abspath(settings[key])
    # Empty resolved choices mean the provider's default, not a new environment-based choice on rerun.
    for key in ("model", "effort"):
        settings[key] = settings[key] or "default"
    url = urlsplit(cfg.base_url)
    if cfg.base_url and not (url.username or url.password or url.query or url.fragment):
        settings["base_url"] = cfg.base_url
    graph.setdefault("meta", {})["settings"] = settings


def stage_config(a: argparse.Namespace, graph: dict, **overrides) -> Config:
    saved = (graph.get("meta") or {}).get("settings") or {}
    values = {key: saved[key] for key in (*SAVED_SETTINGS, "base_url") if key in saved}
    provider = getattr(a, "provider", None)
    if provider is not None and provider != saved.get("provider"):
        for key in ("model", "effort", "base_url"):
            values.pop(key, None)
    for key in ("provider", "model", "effort", "base_url", "cache_dir", "papers_dir"):
        value = getattr(a, key, None)
        if value is not None:
            values[key] = value
    values.setdefault("provider", PROVIDER_DEFAULT)
    values.setdefault("language", (graph.get("meta") or {}).get("language", "en"))
    return Config(**dict(values, **overrides))


OPENALEX_KEY_URL = "https://openalex.org/settings/api"


def openalex_limits(http, cfg: Config) -> None:
    """OpenAlex answers HTTP 429 once its daily allowance is spent (without an API key it is a small amount shared by
    everyone on the same network). Ask it with few retries, stop asking once it refuses, and send the key when there
    is one (it is never written to the cache, the log or an error)."""
    http.daily_limited("api.openalex.org", retries=2, secret={"api_key": cfg.openalex_api_key})


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
                 must=tuple(dict.fromkeys(" ".join(m.split()) for m in (a.must or []) if m.strip())),
                 review=False, gates=a.gates, gates_max=a.gates_max,
                 taste_path=a.taste or default_spec(), papers_dir=a.papers_dir, language=a.language,
                 polish=not a.no_polish, outlook=not a.no_outlook, backtest=getattr(a, "backtest", False), effort=a.effort or "",
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

    http = Http(cfg.cache_dir, min_interval=S2_SPACING, fresh_days=cfg.fresh_days,
                meta_days=cfg.meta_days, refresh=cfg.refresh)
    openalex_limits(http, cfg)
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
    save_settings(graph, cfg)
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
        audit(graph, targets, Auditor(cfg, s2, llm, http, openalex=oa, reader=keeper.gate if keeper else None),
              pool, readings, reference=grower.attention_reference())
    if keeper is not None:
        from tastecal.judge.gates import summary
        # No taste score here: the taste calibration (`--fit`, or `fit` afterwards) scores the papers on your clauses.
        keeper.run(graph, items, raw=readings)
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
    _missing_hint(graph, gpath, getattr(a, "papers_dir", None) or "papers")
    if getattr(a, "fit", False):
        taste_fit_after(gpath, cfg.taste_path, taste_text, log)
    return 0


def taste_fit_argv(gpath: str, taste_path: str, taste_text: str) -> Tuple[Optional[List[str]], int]:
    """The taste calibration that follows a run: `fit` on its graph with its taste profile, when the profile has at
    least three papers you rated with a score. Returns (the fit's arguments or None, how many rated papers)."""
    from tastecal.taste.profiles import rated_papers
    n = sum(1 for r in rated_papers(taste_text) if r.get("score") is not None)
    return (["fit", gpath, "--taste", taste_path] if taste_path and n >= 3 else None), n


def taste_fit_after(gpath: str, taste_path: str, taste_text: str, log) -> int:
    """Run the taste calibration on a finished run (run --fit), so its report has both parts. The report with the
    lineage is already written: a calibration that fails leaves it as it is, and says how to run it again."""
    argv, n = taste_fit_argv(gpath, taste_path, taste_text)
    if not argv:
        log.info("taste calibration: skipped, it needs at least 3 papers you rated with a score (%d given)", n)
        return 0
    log.info("taste calibration: fitting your taste to this map with your %d rated papers; the report is written "
             "again with its taste part when it is done", n)
    try:
        code = main(argv)
    except (Exception, SystemExit) as e:  # the lineage report stays as it is
        logging.getLogger("tastecal").error("taste calibration failed: %s", e)
        code = 1
    if code != 0:
        logging.getLogger("tastecal").warning(
            "taste calibration did not finish; the report has the lineage part. Run it again with: python -m tastecal %s",
            " ".join(f'"{x}"' if " " in x else x for x in argv))
    return code


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
    cfg = stage_config(a, graph, assess=True, assess_max=a.assess_max, review=False, verbose=a.verbose)
    http = Http(cfg.cache_dir, min_interval=S2_SPACING,
                fresh_days=cfg.fresh_days, meta_days=cfg.meta_days)
    openalex_limits(http, cfg)
    try:
        llm = make_llm(cfg, http)
    except LLMError as e:
        log.error("%s", e)
        return 2
    from tastecal.judge.gates import Gatekeeper
    from tastecal.sources.openalex import OpenAlex
    from tastecal.report import polish as style
    llm.system_note = style.system_note(cfg.language)
    keeper = Gatekeeper(cfg, llm, http)
    oa = OpenAlex(http, cfg.openalex_mailto) if cfg.use_openalex else None
    s2 = SemanticScholar(http, cfg.s2_api_key, cfg.max_citations_scan, cfg.popularity_weight)

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
    audit(graph, targets, Auditor(cfg, s2, llm, http, openalex=oa, reader=keeper.gate), pool,
          reference=(graph.get("audit") or {}).get("reference_values"))
    save_settings(graph, cfg)
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
    _missing_hint(graph, gpath, getattr(a, "papers_dir", None) or "papers")
    return 0


def cmd_gates(a: argparse.Namespace) -> int:
    """Read an existing graph.json's papers again: claim vs delivery, reason, robustness, field reaction (the notes
    `fit` measures papers on), then re-render. With --raw, the answers come from a file instead of an LLM (no key
    needed). --taste only changes the profile kept with the map for `fit`."""
    from tastecal.judge.gates import GateThresholds, Gatekeeper, apply_gates, load_raw, summary
    from tastecal.report.render import write_report
    from tastecal.core.schema import validate

    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    out = os.path.dirname(os.path.abspath(a.out or a.graph))
    _setup_logging(a.verbose, os.path.join(out, "gates.log"))
    log = logging.getLogger("tastecal")
    previous = graph.get("gates") or {}
    th = GateThresholds(**{k: v for k, v in (previous.get("thresholds") or {}).items()
                         if k in GateThresholds.__dataclass_fields__})
    from tastecal.taste.profiles import load_profile
    try:
        if a.taste is not None:
            taste_name, taste_text, _ = load_profile(a.taste)
        else:
            taste_name, taste_text = previous.get("taste_name", ""), previous.get("taste_profile", "")
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    if a.raw:
        apply_gates(graph, load_raw(a.raw), a.today, th, taste_name)
    else:
        from tastecal.core.http import Http
        from tastecal.core.llm import LLMError, make_llm
        cfg = stage_config(a, graph, gates=True, gates_max=a.gates_max, taste_path=a.taste or "", verbose=a.verbose)
        http = Http(cfg.cache_dir, min_interval=S2_SPACING,
                    fresh_days=cfg.fresh_days, meta_days=cfg.meta_days)
        openalex_limits(http, cfg)
        try:
            llm = make_llm(cfg, http)
        except LLMError as e:
            log.error("%s", e)
            return 2
        from tastecal.report import polish as style
        llm.system_note = style.system_note((graph.get("meta") or {}).get("language", "en"))
        Gatekeeper(cfg, llm, http, today=a.today, th=th, profile=taste_text, profile_name=taste_name).run(graph)
        save_settings(graph, cfg)
        from tastecal.judge.quality import note_coverage
        note_coverage(graph, a.gates_max, 0, only=("gates",))
        log.info("LLM usage: %s", llm.usage())
    for line in summary(graph):
        log.info("%s", line)
    for e in validate(graph):
        log.warning("schema: %s", e)
    graph["gates"]["taste_profile"] = taste_text
    graph["gates"]["taste_name"] = taste_name
    graph["gates"]["view"] = a.folded
    gpath = a.out or a.graph
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    rpath = write_report(graph, os.path.join(os.path.dirname(os.path.abspath(gpath)), "report.html"))
    print(f"\nWrote {gpath}\nWrote {rpath}")
    _missing_hint(graph, gpath, getattr(a, "papers_dir", None) or "papers")
    return 0


def _spread(nodes: list, k: int) -> list:
    """k works spread over the blind contribution score (or the date when there is none): a fair sample for a trial."""
    key = lambda n: (((n.get("assessment") or {}).get("contribution") or {}).get("score") or 0, n.get("date") or "")  # noqa: E731
    ordered = sorted(nodes, key=key)
    if k >= len(ordered):
        return [n["id"] for n in ordered]
    return list(dict.fromkeys(ordered[round(i * (len(ordered) - 1) / max(1, k - 1))]["id"] for i in range(k)))


def cmd_fit(a: argparse.Namespace) -> int:
    """Fit your taste for an existing run: each paper measured on your own indicators, a line fitted to your scores,
    the indicators improved until the line stops improving. Writes taste_fit.json and taste_fit.html next to the
    graph: the rated papers far from your line, and every method paper on the map predicted on it."""
    from tastecal.core.http import Http
    from tastecal.core.llm import LLMError, make_llm
    from tastecal.report import polish as style
    from tastecal.report.axes_view import page
    from tastecal.report.render import write_report
    from tastecal.taste.axes import (draw_sample, is_method, on_topic, read_items, read_rated, read_table, rated_works,
                                     readable, run)
    from tastecal.taste.profiles import load_profile, rated_papers

    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    out = os.path.abspath(a.out) if a.out else os.path.dirname(os.path.abspath(a.graph))
    os.makedirs(out, exist_ok=True)
    if getattr(a, "redraw", False) or getattr(a, "refit", False):
        jpath, hpath = os.path.join(out, "taste_fit.json"), os.path.join(out, "taste_fit.html")
        if not os.path.exists(jpath):
            print(f"No {jpath} yet: run fit without --{'refit' if a.refit else 'redraw'} first.")
            return 2
        with open(jpath, "r", encoding="utf-8") as f:
            res = json.load(f)
        from tastecal.taste.axes import enrich, refit
        if a.refit:                              # step 2's numbers again from the stored levels: no model call
            _setup_logging(a.verbose)
            anchor = None
            kept = ((res.get("attention_scale") or {}).get("cumulative") or {})
            if not a.no_attention and not (kept.get("top") and kept.get("top_title") == "Attention Is All You Need"):
                # a result from before the landmark was kept: its count, from the cache if an earlier run looked it
                # up (one lookup otherwise)
                from tastecal.core.http import Http
                from tastecal.sources.openalex import OpenAlex
                from tastecal.sources.semantic_scholar import SemanticScholar
                from tastecal.taste.attention import ANCHOR_NODE, fetch
                cfg0 = Config()
                http = Http(cfg0.cache_dir, min_interval=S2_SPACING, fresh_days=cfg0.fresh_days, meta_days=cfg0.meta_days)
                openalex_limits(http, cfg0)
                http.fail_fast["api.semanticscholar.org"] = 1          # one count, not worth a long wait
                got = fetch([ANCHOR_NODE], OpenAlex(http, cfg0.openalex_mailto),
                            SemanticScholar(http, cfg0.s2_api_key, cfg0.max_citations_scan, cfg0.popularity_weight))
                anchor = got.get(ANCHOR_NODE["id"]) or None
            res = refit(res, graph, anchor=anchor)
            with open(jpath, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            fld, cf = res.get("field") or {}, res.get("confidence") or {}
            if fld.get("final") and fld.get("equal"):
                print(f"Distance from y = x (root mean square): {fld['equal']['dist']:.2f} with every clause counting the "
                      f"same -> {fld['final']['dist']:.2f} with the weights fitted ({fld.get('papers', 0)} papers).")
            print(f"Trust in the result: ±{cf.get('rms', 0):.2f}. Wrote {jpath}")
        else:
            enrich(res, graph)
        with open(hpath, "w", encoding="utf-8") as f:
            f.write(page(res, (graph.get("meta") or {}).get("language", "en")))
        rpath = write_report(graph, os.path.join(out, "report.html"), taste=res)
        print(f"Wrote {hpath}\nWrote {rpath} (the lineage, then the taste calibration)")
        return 0
    _setup_logging(a.verbose, os.path.join(out, "fit.log"))
    log = logging.getLogger("tastecal")
    try:
        profile = load_profile(a.taste)[1] if a.taste else (graph.get("gates") or {}).get("taste_profile", "")
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2
    rated = rated_papers(profile)
    if a.rated:
        extra = read_table(a.rated)
        names = {r["ref"].lower() for r in extra}
        rated = [r for r in rated if r["ref"].lower() not in names] + extra
        log.info("%d rated papers from %s", len(extra), a.rated)
    if len(rated) < 3:
        log.error("%d rated papers; at least three are needed (better eight or more, with a reason each).", len(rated))
        return 2
    works = [w.strip() for w in a.works.split(",")] if a.works else None
    if a.max and not works:
        rated_nodes = {x["node"] for x in rated_works(graph, rated)[0] if x["node"]}
        works = _spread([n for n in graph.get("nodes", []) if readable(n) and is_method(n) and n["id"] not in rated_nodes],
                        a.max)
    cfg = stage_config(a, graph, verbose=a.verbose)
    try:
        llm = make_llm(cfg, Http(cfg.cache_dir))
    except LLMError as e:
        log.error("%s", e)
        return 2
    language = (graph.get("meta") or {}).get("language", "en")
    llm.system_note = style.system_note(language)
    # rated papers this run never read: find them and read them in full, as the run read its own papers
    extra, unread, sample, attention, anchor = [], [], [], {}, None
    need_rated = any(s_.get("why", "").startswith("no full-text") for s_ in rated_works(graph, rated)[1])
    from tastecal.taste.axes import recent
    as_of = str((graph.get("meta") or {}).get("generated_at") or "")[:10]
    compared = [n for n in graph.get("nodes", []) if readable(n) and is_method(n) and recent(n, as_of, a.years)]
    n_random = max(3, round(a.random_share * len(compared))) if a.random_share > 0 else 0
    if need_rated or n_random or not a.no_attention:
        from tastecal.sources.openalex import OpenAlex
        from tastecal.sources.semantic_scholar import SemanticScholar
        from tastecal.taste.attention import ANCHOR_NODE, ANCHOR_TITLE, fetch
        http = Http(cfg.cache_dir, min_interval=S2_SPACING, fresh_days=cfg.fresh_days, meta_days=cfg.meta_days)
        openalex_limits(http, cfg)
        if not cfg.openalex_api_key and not a.no_attention:
            log.warning("No OPENALEX_API_KEY: without a key OpenAlex allows only a small daily amount, shared by "
                        "everyone on your network; once it is spent, citation counts come from Semantic Scholar and "
                        "the map. A free key: %s . Set it once (Windows: setx OPENALEX_API_KEY \"...\"; macOS, Linux: "
                        "export OPENALEX_API_KEY=...).", OPENALEX_KEY_URL)
        elif not a.no_attention:
            log.info("OpenAlex: using your API key (OPENALEX_API_KEY)")
        s2 = SemanticScholar(http, cfg.s2_api_key, cfg.max_citations_scan, cfg.popularity_weight)
        if need_rated:
            extra, unread = read_rated(rated, cfg, llm, http, s2, graph)
            for u in unread:
                log.warning("rated paper not used: %s (%s)%s", u.get("title") or u["ref"], u["why"],
                            f"; put its PDF in the papers folder as {u['file']}" if u.get("file") else "")
        if n_random and not works:
            log.info("drawing %d papers at random from those citing the map's works (not chosen by citations)", n_random)
            rows_r, skip_r = rated_works(graph, rated, extra)        # your papers, by your name for them and by title
            taken = [r["ref"] for r in rated] + [x.get("title") or "" for x in rows_r + skip_r]
            items = draw_sample(graph, s2, 2 * n_random, exclude=taken, years=a.years)
            items = on_topic(llm, graph, items)             # only those on the map's own problem
            sample, no_text = read_items(items, cfg, llm, http, "random", n_random)
            log.info("%d drawn papers read in full (%d had no full text and are not scored)", len(sample), no_text)
        if not a.no_attention:
            nodes = compared + sample
            # your rated papers too: never for their own place, only to anchor the log scale (the most cited at 1)
            by_id = {n["id"]: n for n in graph.get("nodes", []) + list(extra)}
            for row in rated_works(graph, rated, extra)[0]:
                if row.get("node") and row["node"] in by_id and row["node"] not in {n["id"] for n in nodes}:
                    nodes.append(by_id[row["node"]])
            log.info("looking up how much the field attends to %d papers (OpenAlex, Semantic Scholar)", len(nodes))
            oa = OpenAlex(http, cfg.openalex_mailto)
            attention = fetch(nodes, oa, s2)
            # the top of the attention scale (+3 sigma; no citation is -3 sigma), the same paper in every run
            anchor = fetch([ANCHOR_NODE], oa, s2).get(ANCHOR_NODE["id"]) or None
            if not ((anchor or {}).get("cited_by") or (anchor or {}).get("s2_cites")):
                log.warning("%s could not be looked up; the most cited paper known takes its place", ANCHOR_TITLE)
                anchor = None
    from tastecal.taste.axes import save_clauses, saved_clauses
    start = None if a.fresh else saved_clauses(a.clauses, language)
    res = run(llm, graph, rated, works=works, extra=extra, attention=attention, sample=sample, years=a.years, start=start,
              anchor=anchor)
    res["unread"] = unread
    if res.get("error"):
        log.error("%s. Not used: %s", res["error"], "; ".join(s["ref"] for s in res.get("skipped") or []) or "none")
        return 2
    jpath, hpath = os.path.join(out, "taste_fit.json"), os.path.join(out, "taste_fit.html")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    with open(hpath, "w", encoding="utf-8") as f:
        f.write(page(res, language))
    log.info("LLM usage: %s", llm.usage())
    if a.clauses and not works:                  # a trial on a few works (--max, --works) does not overwrite them
        save_clauses(a.clauses, language, res, os.path.relpath(os.path.abspath(a.graph)))
        log.info("clauses saved to %s, the start of the next fit", a.clauses)
    off = [r["title"] for r in res["rated"] if abs(r["pred"] - r["yours"]) > res.get("fit_tol", 0.1) + 1e-3]
    cf = res.get("confidence") or {}
    if cf:
        print(f"Trust in the result: ±{cf['rms']:.2f} (how far the clauses miss your scores, root mean square; worst "
              f"{cf['worst']:.2f}). The larger, the less to trust; every score bar is widened by it.")
    print(f"{len(res['rated'])} rated papers, {len(res['indicators'])} indicators. Your scores reproduced within "
          f"{res['mae']:.2f} on average (worst {res.get('max_err', 0):.2f}), {res['order_errors']} pairs in the wrong order. "
          f"Changes kept: {sum(1 for h in res['history'] if h.get('accepted'))} of {len(res['history'])}. "
          f"Not yet reproduced: {'; '.join(off) or 'none'}. {len(res['map'])} papers of the last "
          f"{res.get('years') or 'any number of'} years scored, {len(res.get('older') or [])} older ones left out.")
    vw = (res.get("views") or {}).get(res.get("fit_metric") or "cumulative") or {}
    by_id = {r["id"]: r.get("short") or r["title"] for r in res["map"]}
    if vw:
        print(f"High on your line, little attended: {'; '.join(by_id[i] for i in vw.get('gem', [])) or 'none'}. "
              f"Much attended, low on your line: {'; '.join(by_id[i] for i in vw.get('hyped', [])) or 'none'}.")
    fld = res.get("field") or {}
    if fld.get("skipped"):
        print(f"Not fitted to the field: {fld['skipped']}.")
    elif fld.get("final"):
        print(f"Distance from y = x of the papers you have not rated (mean, straight up or down): "
              f"{fld['equal']['dist']:.2f} with every clause counting the same -> {fld['final']['dist']:.2f} with the "
              f"weights fitted ({fld.get('papers', 0)} papers; your scores held within "
              f"{res.get('fit_tol', 0.1):.2f}, or within step 1's miss where that was larger).")
    rpath = write_report(graph, os.path.join(out, "report.html"), taste=res)
    print(f"Wrote {jpath}\nWrote {hpath}\nWrote {rpath} (the lineage, then the taste calibration)")
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


def missing_works(graph: dict, papers_dir: str = "papers") -> List[dict]:
    """Works in a run that were read from an abstract or a summary card only (no verdict, no scores), and your rated
    papers read the same way, each with the file name to give its PDF and whether that file is there now."""
    from tastecal.sources.fulltext import local_file, suggested_name
    rows = []
    for n in graph.get("nodes", []):
        basis = (n.get("gates") or {}).get("basis")
        thin = ((n.get("assessment") or {}).get("flag") == "thin")
        if n.get("kind", "paper") != "paper" or not (thin or (basis and basis != "full text")):
            continue
        rows.append({"id": n["id"], "short": n.get("short") or "", "title": n.get("title") or "", "date": n.get("date") or "",
                     "url": n.get("url") or "", "read_from": basis or "abstract", "rated": False,
                     "file": suggested_name(n), "found": local_file(n, None, papers_dir) or ""})
    cal = ((graph.get("audit") or {}).get("calibration") or {})
    for r in cal.get("anchors") or []:
        if r.get("found") is False or "blind" in r or r.get("on_map"):
            continue
        node = {"id": "", "title": r.get("title") or r.get("ref") or "", "url": r.get("url") or ""}
        rows.append({"id": "", "short": "", "title": node["title"], "date": "", "url": node["url"],
                     "read_from": r.get("basis") or "abstract", "rated": True,
                     "file": suggested_name(node), "found": local_file(node, None, papers_dir) or ""})
    return rows


def _missing_hint(graph: dict, gpath: str, papers_dir: str) -> None:
    try:
        n = len(missing_works(graph, papers_dir))
    except Exception:  # never fail a finished run over a hint
        return
    if n:
        print(f"\n{n} works were read from an abstract only (no verdict, no scores). To list them with the file name "
              f"for each PDF:\n  python -m tastecal missing {gpath}")


def cmd_missing(a: argparse.Namespace) -> int:
    with open(a.graph, "r", encoding="utf-8") as f:
        graph = json.load(f)
    rows = missing_works(graph, a.papers_dir)
    if not rows:
        print("Every work in this run was read from its full text.")
        return 0
    print(f"{len(rows)} works were read from an abstract or a summary only, so they have no verdict and no scores.")
    print(f"Save each PDF in the '{a.papers_dir}' folder under the name shown (the DOI with / as _, or the arXiv id):\n")
    for r in rows:
        mark = "[found]  " if r["found"] else "[missing]"
        name = (r["short"] + ": " if r["short"] and r["short"] != r["title"] else "") + r["title"]
        print(f"{mark} {name}" + (f" ({r['date']})" if r["date"] else "") + ("  (a paper you rated)" if r["rated"] else ""))
        print(f"          file: {r['found'] or os.path.join(a.papers_dir, r['file'])}")
        if r["url"]:
            print(f"          link: {r['url']}")
    run = os.path.dirname(os.path.abspath(a.graph))
    print("\nThen judge and score them (works already read come from the cache):")
    print(f"  python -m tastecal assess {os.path.join(run, 'graph.json')}")
    print(f"  python -m tastecal gates {os.path.join(run, 'graph.json')}")
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
    from tastecal.taste.profiles import list_profiles, load_profile, load_store
    store = load_store()
    rows = [(k, "taste.json" + (" (default)" if k == store.get("default") else ""), (v or {}).get("title") or k)
            for k, v in store.get("profiles", {}).items()]
    rows += [(name, path, load_profile(path)[0]) for name, path, _ in list_profiles()]
    for name, where, title in rows:
        print(f"{name:14} {title}  ({where})")
    if not rows:
        print("No taste profiles yet. Save one from the page (python -m tastecal serve), or write ./taste.md.")
    print("\nPass one with --taste <name>, or give a path.")
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
    for m in req.get("must") or []:
        argv += ["--must", m]
    if req.get("fit"):
        argv += ["--fit"]
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
    s2 = cfg.s2_api_key
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
    r.add_argument("--fit", action="store_true",
                   help="then calibrate your taste on the new map (as `fit` does), when the taste profile has at least "
                        "3 papers you rated, so the report has both parts")
    r.add_argument("--base-url", help="OpenAI-compatible base URL, e.g. https://api.deepseek.com/v1")
    r.add_argument("--scope", default="", help='limit the map to a field, named in a few words. Works from other '
                   'fields (a generic diffusion model, a backbone) are listed as borrowed instead of mapped, read or audited')
    r.add_argument("--must", action="append", default=[], metavar="PAPER",
                   help="a paper you want on the map: a title, link, DOI or id (repeat for more). It is read like the "
                        "seed, opened with it, kept whatever the field limit, and counts towards the budget")
    r.add_argument("--no-openalex", action="store_true", help="skip OpenAlex (top-cited citers)")
    r.add_argument("--no-web", action="store_true", help="skip blog search")
    r.add_argument("--popularity-weight", type=float, default=0.5,
                   help="how much citation counts sway admission (default 0.5; try 0.1 for a less popularity-driven map)")
    r.add_argument("--assess", action="store_true", default=True, help="audit attention vs contribution (on by default)")
    r.add_argument("--no-assess", dest="assess", action="store_false", help="skip the audit")
    r.add_argument("--assess-max", type=int, default=0, help="works to audit (default 0 = every paper on the map, plus the runners-up)")
    r.add_argument("--no-review", action="store_true", help="no longer needed: the adversarial review is off (it only served the audit flags, which the report no longer shows)")
    r.add_argument("--gates", action="store_true", default=True, help="run the gates: read each work and write its reading notes (on by default)")
    r.add_argument("--no-gates", dest="gates", action="store_false", help="skip the gates")
    r.add_argument("--gates-max", type=int, default=0, help="papers to read through the gates (default 0 = every paper on the map)")
    r.add_argument("--taste", help="taste profile: a file path, or the name of a profile in taste.json or ./profiles (see `profiles`; default: the default in taste.json, else ./taste.md if it exists)")
    r.add_argument("--papers-dir", default="papers", help="folder with your own PDFs or text files of the papers (default ./papers)")
    r.add_argument("--language", default=from_env("LANGUAGE", "en"), help="en or zh-CN: language of the report text (default en)")
    r.add_argument("--no-polish", action="store_true", help="skip the plain-language rewrite of flagged sentences")
    r.add_argument("--no-outlook", action="store_true", help="skip the What's next section")
    r.add_argument("--backtest", action="store_true", help="also test the driving forces against later works (kept in graph.json, not shown)")
    r.add_argument("--cache-dir", default=".tastecal_cache")
    r.add_argument("--refresh", action="store_true",
                   help="fetch every search result and citer list again, however recent the cached copy "
                        "(by default they are re-fetched after $TASTECAL_CACHE_DAYS, 14 days)")
    r.add_argument("--out", help="output folder (default runs/<seed>)")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(func=cmd_run)

    s_ = sub.add_parser("assess", help="gather context for an existing graph.json: counts, claims, earlier similar work, how later papers use it")
    s_.add_argument("graph")
    s_.add_argument("-o", "--out", help="write the audited graph here (default: overwrite the input)")
    s_.add_argument("--assess-max", type=int, default=0, help="works to audit (default 0 = every paper on the map, plus the runners-up)")
    s_.add_argument("--no-review", action="store_true", help="no longer needed: the adversarial review is off (it only served the audit flags, which the report no longer shows)")
    s_.add_argument("--provider", choices=PROVIDERS, default=None, help=PROVIDER_HELP)
    s_.add_argument("--model")
    s_.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    s_.add_argument("--base-url")
    s_.add_argument("--cache-dir", default=None, help="reuse the saved cache directory unless overridden")
    s_.add_argument("--papers-dir", default=None, help="reuse the saved papers directory unless overridden")
    s_.add_argument("-v", "--verbose", action="store_true")
    s_.set_defaults(func=cmd_assess)

    q = sub.add_parser("gates", help="gate an existing graph.json (claim vs delivery, reason, robustness, field reaction)")
    q.add_argument("graph")
    q.add_argument("-o", "--out", help="write the gated graph here (default: overwrite the input)")
    q.add_argument("--raw", help="JSON file of gate answers keyed by node id; skips the LLM")
    q.add_argument("--taste", help="taste profile kept with the map for `fit`: a file path or a profile name (see `profiles`)")
    q.add_argument("--papers-dir", default=None, help="reuse the saved papers directory unless overridden")
    q.add_argument("--gates-max", type=int, default=0, help="papers to read through the gates (default 0 = every paper on the map)")
    q.add_argument("--today", help="YYYY-MM to judge recency against (default: this month)")
    q.add_argument("--folded", choices=["hide", "show"], default="hide", help="whether the report opens with side branches folded (default) or shown")
    q.add_argument("--provider", choices=PROVIDERS, default=None, help=PROVIDER_HELP)
    q.add_argument("--model")
    q.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    q.add_argument("--base-url")
    q.add_argument("--cache-dir", default=None, help="reuse the saved cache directory unless overridden")
    q.add_argument("-v", "--verbose", action="store_true")
    q.set_defaults(func=cmd_gates)

    ft = sub.add_parser("fit", help="fit your taste: your indicators, a line fitted to your scores, and the papers far from it")
    ft.add_argument("graph")
    ft.add_argument("-o", "--out", help="folder for taste_fit.json and taste_fit.html (default: next to the graph)")
    ft.add_argument("--taste", help="taste profile with your rated papers (default: the one saved with the run)")
    ft.add_argument("--rated", help="your ratings: .json or .yaml (a list of paper, score, reason), .xlsx or .csv (columns "
                    "paper, score, reason), or a text file with one per line: title or short name | score | reason. Papers "
                    "not on the map are found and read in full.")
    ft.add_argument("--works", help="comma-separated node ids to predict (default: every method paper read in full)")
    ft.add_argument("--max", type=int, default=0, help="predict only this many works, spread over the map (a trial)")
    ft.add_argument("--redraw", action="store_true", help="only draw taste_fit.html again from taste_fit.json (no model calls)")
    ft.add_argument("--refit", action="store_true",
                    help="recompute the attention scale, the weights and the page from taste_fit.json (no model calls, "
                         "no lookups); the clauses and every paper's levels are kept")
    ft.add_argument("--random-share", type=float, default=0.15, help="papers drawn at random from those citing the map's "
                    "works, read in full, as a share of the map's papers compared, so the comparison is not only among "
                    "cited work (0: none; default 0.15)")
    ft.add_argument("--years", type=int, default=10, help="compare only papers of the last N years (your rated papers are "
                    "always kept; 0: any year; default 10)")
    ft.add_argument("--clauses", default="taste_clauses.json", help="where the clauses are kept between fits: each fit "
                    "starts from the clauses the last one ended with (per language) and saves its own (default "
                    "taste_clauses.json; personal, kept out of git)")
    ft.add_argument("--fresh", action="store_true", help="start from the general clauses, not from the saved ones")
    ft.add_argument("--no-attention", action="store_true", help="do not look up citations (OpenAlex, Semantic Scholar); "
                    "use the run's own attention percentile only")
    ft.add_argument("--provider", choices=PROVIDERS, default=None, help=PROVIDER_HELP)
    ft.add_argument("--model")
    ft.add_argument("--effort", choices=EFFORTS, help=EFFORT_HELP)
    ft.add_argument("--base-url")
    ft.add_argument("--cache-dir", default=None, help="reuse the saved cache directory unless overridden")
    ft.add_argument("-v", "--verbose", action="store_true")
    ft.set_defaults(func=cmd_fit)

    d = sub.add_parser("render", help="render a graph.json into report.html")
    d.add_argument("graph")
    d.add_argument("-o", "--out")
    d.add_argument("--fragment", action="store_true", help="body only, no <html>/<head> wrapper")
    d.add_argument("--folded", choices=["hide", "show"], default="hide", help="open with side branches folded (default) or shown")
    d.set_defaults(func=cmd_render)

    mi = sub.add_parser("missing", help="list the works a run could not read in full, with the file name for each PDF")
    mi.add_argument("graph")
    mi.add_argument("--papers-dir", default="papers")
    mi.set_defaults(func=cmd_missing)

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


# Semantic Scholar allows about one request a second per API key (and less without one). Requests are spaced to that
# pace instead of being sent in bursts that come back as HTTP 429 and are retried with growing waits.
S2_SPACING = 1.05


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
