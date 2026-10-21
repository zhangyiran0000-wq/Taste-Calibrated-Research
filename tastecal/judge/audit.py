"""Audit: how much attention a work got, versus how much it contributed.

The two are measured separately so that one cannot leak into the other.

  attention     citations per year (and, when known, code-repository stars per year), each as a
                percentile. Citations are ranked against every work seen while the map grew (references,
                citers, search hits; often hundreds), not only the mapped works: the map holds the field's
                important works, so ranking within it makes well-cited works look unnoticed.
                Popularity only; says nothing about quality.
  contribution  a score from a BLIND evidence pack: no title, authors, venue, awards or counts,
                and the work's own name replaced by an alias. The pack holds what the work claims
                and how well its own experiments back it, earlier work with the same idea, what
                later papers actually do with it, and later evidence against it.

Quadrants (contribution x attention):  hidden gem? | classic | overhyped? | noise.
Candidates (possible gems, possibly overhyped, safe-to-skip) then get an adversarial review:
an advocate and a critic argue from the same blind pack and a blind judge decides. Only flagged
works are reviewed, which keeps the cost small.

A possible gem must also look unnoticed in absolute terms: not above a citations-per-year ceiling,
not above a total-citation ceiling, and not in the top 10% of its field and year (OpenAlex). The
review of a possible gem adds one non-blind step, an attention check that sees the counts and asks
whether the work really is under-noticed; the flag stays only if both the blind judge and the
attention check agree.

Final flags: hidden-gem, overhyped, skip, fair, too-early. They are candidates for a reader to
check, not verdicts.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import random
import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

from tastecal.prompts import audit as P
from tastecal.core.model import Item, norm_title, title_similarity

log = logging.getLogger("tastecal.audit")

ALIAS = "[THIS WORK]"
ROLES = ("builds_on", "contrasts", "baseline", "uses", "mentions", "not_cited")
SUBSTANTIVE = ("builds_on", "contrasts")
FLAGS = ("hidden-gem", "overhyped", "skip", "fair", "too-early", "thin")
LABELS = {
    "hidden-gem": "Possible hidden gem",
    "overhyped": "Possibly overhyped",
    "skip": "Safe to skip",
    "fair": "Fairly valued",
    "too-early": "Too early to tell",
    "thin": "Too little text to judge",
}
QUADRANTS = ("gem", "classic", "hyped", "noise", "middle", "unknown", "unscored")
TYPES = ("method", "analysis", "benchmark", "dataset", "tool", "survey", "application", "system")
VERDICTS = ("substantial", "modest", "negligible")
ATTENTION = ("under-noticed", "fairly noticed", "well noticed")

METHOD_NOTE = (
    "Attention is citations per year, and code-repository stars per year where known, each as a percentile. "
    "Citations are ranked against every work seen while the map grew, not only the works on the map. A work is only "
    "called a possible hidden gem when it is also unnoticed in absolute terms (below a citations-per-year ceiling and "
    "outside the top 10% of its field and year), and an attention check that sees the counts agrees. Where a citation count is known to be undercounted, stars are used instead; "
    "where neither is reliable the value is a lower bound. Contribution is scored from a blind evidence pack "
    "(no title, authors, venue, awards or counts; the work's name replaced by an alias) on novelty, "
    "significance, evidence and uptake. Works that look like hidden gems, overhyped or safe to skip are "
    "argued over by an advocate and a critic, and a blind judge decides.")
CAVEATS = [
    "These are candidates for a closer look, not verdicts. Read the evidence before citing a flag.",
    "Blinding is partial: a model may still recognise a famous work from its description.",
    "Citation counts are often undercounted, especially for preprints; values marked ≥ are lower bounds.",
    "Contribution is judged from a short evidence pack, so missing evidence can lower a score.",
]


@dataclass
class Thresholds:
    contrib_high: float = 0.6
    contrib_low: float = 0.45
    skip: float = 0.35
    attn_high: float = 0.6
    attn_low: float = 0.4
    too_early_months: int = 18
    gem_max_cites_per_year: float = 100.0   # above this a work is noticed, whatever its rank on the map
    gem_max_cites: int = 500                # ... or above this many citations in all
    ref_min: int = 30                       # works needed in the neighbourhood reference to use it


# ----------------------------------------------------------------------------- attention
def months_between(date: str, today: str) -> int:
    """Whole months from `date` (YYYY or YYYY-MM[-DD]) to `today` (YYYY-MM[-DD])."""
    def ym(s: str):
        m = re.match(r"(\d{4})(?:-(\d{2}))?", s or "")
        if not m:
            return None
        return int(m.group(1)), int(m.group(2) or 6)
    a, b = ym(date), ym(today)
    if not a or not b:
        return 0
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def per_year(value: Optional[float], date: str, today: str) -> Optional[float]:
    if value is None:
        return None
    years = max(0.5, months_between(date, today) / 12.0)
    return float(value) / years


def pct_against(x: float, ref: List[float]) -> float:
    """Share of the reference values below x (ties count half)."""
    if not ref:
        return 0.5
    below = sum(1 for r in ref if r < x)
    ties = sum(1 for r in ref if r == x)
    return (below + 0.5 * ties) / len(ref)


UNDERCOUNT_CUES = ("undercount", "lower bound", "arxiv record only", "arxiv-only", "only the arxiv",
                   "journal record only", "journal version only", "approximate")


def is_lower_bound(pack: dict) -> bool:
    """True when the pack says its citation count is known to be too low (or there is none)."""
    if pack.get("citations") is None:
        return True
    if "citations_lower_bound" in pack:
        return bool(pack["citations_lower_bound"])
    note = (pack.get("citations_note") or "").lower()
    return any(c in note for c in UNDERCOUNT_CUES)


def attention(packs: List[dict], today: str, reference: Optional[List[dict]] = None,
              ref_min: int = 30) -> Dict[str, dict]:
    """Attention percentile per pack id.

    Each signal is ranked against the values of that signal that are trusted (citation counts
    that are not lower bounds; stars from a repository that is not mainly another work's).
    Citations are ranked against `reference` (every work seen while growing: [{"citations", "date"}])
    when it holds at least `ref_min` works, else against the assessed set alone.
    Both signals known and trusted: their mean. Citations undercounted: stars alone. Neither
    trusted: the citation percentile, marked as a lower bound."""
    rows = {}
    for p in packs:
        c = per_year(p.get("citations"), p.get("date", ""), today)
        s = per_year(p.get("stars"), p.get("date", ""), today) if not p.get("stars_shared_with") else None
        rows[p["id"]] = {"citations": p.get("citations"), "citations_per_year": c, "lower_bound": is_lower_bound(p),
                         "stars": p.get("stars"), "stars_per_year": s, "stars_shared_with": p.get("stars_shared_with") or ""}
    c_ref = [r["citations_per_year"] for r in rows.values() if r["citations_per_year"] is not None and not r["lower_bound"]]
    if not c_ref:
        c_ref = [r["citations_per_year"] for r in rows.values() if r["citations_per_year"] is not None]
    ref_used = "assessed"
    near = [per_year(w.get("citations"), w.get("date", ""), today) for w in (reference or [])
            if isinstance(w, dict) and isinstance(w.get("citations"), (int, float))]
    if len(near) >= ref_min:
        c_ref = c_ref + near
        ref_used = f"neighbourhood ({len(near)} works seen while growing)"
    s_ref = [r["stars_per_year"] for r in rows.values() if r["stars_per_year"] is not None]
    out = {}
    for pid, r in rows.items():
        cp = pct_against(r["citations_per_year"], c_ref) if r["citations_per_year"] is not None else None
        sp = pct_against(r["stars_per_year"], s_ref) if r["stars_per_year"] is not None else None
        lb = False
        if cp is not None and not r["lower_bound"] and sp is not None:
            pct, basis = (cp + sp) / 2, "citations+stars"
        elif cp is not None and not r["lower_bound"]:
            pct, basis = cp, "citations"
        elif sp is not None:
            pct, basis = max(sp, cp or 0.0), "stars"
        else:
            pct, basis, lb = (cp or 0.0), "citations", True
        out[pid] = dict(r, pct=round(pct, 3), citations_pct=None if cp is None else round(cp, 3),
                        stars_pct=None if sp is None else round(sp, 3), basis=basis,
                        lower_bound=lb, citations_lower_bound=r["lower_bound"], reference=ref_used)
        for k in ("citations_per_year", "stars_per_year"):
            if out[pid][k] is not None:
                out[pid][k] = round(out[pid][k], 1)
    return out


# ----------------------------------------------------------------------------- blinding
# Labs, companies and venues: prestige is part of what the blind score must not see. The lists are field-neutral;
# add the labs and venues of your own field (separated by "|") with TASTECAL_BLIND_ORGS and TASTECAL_BLIND_VENUES.
def _extra(name: str) -> str:
    raw = os.environ.get(name, "")
    parts = [re.escape(p.strip()) for p in raw.split("|") if p.strip()]
    return ("|" + "|".join(parts)) if parts else ""


ORGS = (r"NVlabs|NVIDIA|Meta|Google|DeepMind|Microsoft|OpenAI|Anthropic|Apple|Amazon|IBM|Intel|Samsung|Sony|Huawei|"
        r"Baidu|ByteDance|Alibaba|Tencent|SenseTime|Shanghai AI Lab(?:oratory)?|Tsinghua|Peking University|Stanford|MIT|"
        r"Berkeley|CMU|Carnegie Mellon|Oxford|Cambridge|ETH Z(?:ü|ue)rich|T(?:ü|ue)bingen|Max Planck|Mila|Vector Institute"
        + _extra("TASTECAL_BLIND_ORGS"))
VENUES = (r"CVPR|ICCV|ECCV|NeurIPS|NIPS|ICLR|ICML|CoRL|ICRA|IROS|IJCAI|AAAI|T-?PAMI|IJCV|RA-?L|WACV|BMVC|"
          r"ACL|EMNLP|NAACL|KDD|SIGGRAPH|TMLR|JMLR|PNAS|TSMC|TNNLS|"
          r"Nature(?: Machine Intelligence| Communications| Human Behaviour)?|Science(?: Robotics)?"
          + _extra("TASTECAL_BLIND_VENUES"))
SCRUB_RULES = [
    (re.compile(r"(https?://)?(www\.)?[\w.-]+\.(org|com|io|net|ai|edu|cn)(/[^\s,;)\]]*)?", re.I), "[link]"),
    (re.compile(r"\b\d{4}\.\d{4,5}(v\d+)?\b"), "[id]"),
    (re.compile(r"\bW\d{6,}\b"), "[record]"),
    (re.compile(r"\bdoi:?\s*10\.\S+", re.I), "[doi]"),
    (re.compile(r"~?\b\d[\d,.]*\s*k?\+?\s*(GitHub\s+)?(stars?|forks?|citations?|cites|citing papers|citers)\b", re.I), "[count]"),
    (re.compile(r"\b(cited by|citation count( of)?|citations?:)\s*~?\d[\d,]*", re.I), "[count]"),
    # Chinese counts, awards and fame words (evidence packs may be written in Chinese)
    (re.compile(r"~?约?\d[\d,.]*\s*[kK千万]?\+?\s*(次)?\s*(引用|被引|星标|颗星|个星|stars?)"), "[count]"),
    (re.compile(r"(被引用?|引用量|引用数|引用次数|星标数?|stars?)\s*[:：约为达]*\s*~?\d[\d,.]*\s*[kK千万]?\s*次?", re.I), "[count]"),
    (re.compile(r"(最佳(学生)?论文(奖|提名)?|杰出论文奖?|口头报告|亮点论文|大会报告)"), "[status]"),
    (re.compile(r"(顶会|顶刊|广受关注|广为引用|高被引|被广泛引用|影响力很大|知名)"), "[fame]"),
    # any clause that names a citation index can carry a bare count ("531 on the OpenAlex record"): drop the clause
    (re.compile(r"[^.;()。；，、（）]*\b(OpenAlex|Google Scholar|Semantic Scholar|Crossref|Scopus|谷歌学术)\b[^.;()。；，、（）]*", re.I), "[count source]"),
    (re.compile(r"\b(Best (Student )?Paper( Award)?( Candidate| Honou?rable Mention)?|Outstanding Paper( Award)?|"
                r"Oral|Highlight|Spotlight|Award)\b"), "[status]"),
    (re.compile(r"\b(" + VENUES + r")(\s*'?\d{2,4})?\b(\s+(Datasets and Benchmarks|Workshop|Track))?"), "[venue]"),
    (re.compile(r"\bOpenReview( id)?:?\s+\S+", re.I), "[id]"),
    (re.compile(r"\b(" + ORGS + r")\b"), "[org]"),
    (re.compile(r"\b[\w.-]+/\[THIS WORK\]"), "[repo]"),
    (re.compile(r"\blandmark (papers|works)\b", re.I), r"major later \1"),
    (re.compile(r"\b(highly|widely|heavily|much|most|well)[- ]cited\b|\bhigh citations?( and \w+)? attention\b|"
                r"\b(famous|well-known|popular|seminal|landmark|award-winning|celebrated|prestigious)\b", re.I), "[fame]"),
]


def names_for(pack: dict) -> List[str]:
    """Strings that would identify the work: its short names, title(s), id slug.
    A pack can set "blind_names" when a nickname is also an ordinary phrase."""
    if pack.get("blind_names"):
        return sorted(pack["blind_names"], key=len, reverse=True)
    out = []
    short = pack.get("short") or ""
    for part in re.split(r"\s*/\s*|\s*[()（）]\s*|\s*[,，]\s*|\s+or\s+|['\"‘’“”]", short):
        part = part.strip()
        if part and part.lower() not in ("paper", "the", "a", "an") and len(part) >= 2:
            out.append(re.sub(r"\s+paper$", "", part))
    title = pack.get("title") or ""
    for part in re.split(r"\s*[(（]\s*|\s*[)）]\s*", title):
        part = re.sub(r"^(arXiv\s+)?v\d+\s+title:\s*", "", part.strip(), flags=re.I)
        if len(part) >= 8:
            out.append(part)
            head = part.split(":")[0].strip()
            if 2 <= len(head) < len(part):
                out.append(head)
    pid = pack.get("id") or ""
    if len(pid) >= 5 and not pid.startswith(("s2:", "oa:")):   # short ids such as "law" are ordinary words
        out.append(pid)
    seen, uniq = set(), []
    for n in sorted(out, key=len, reverse=True):
        if n.lower() not in seen:
            seen.add(n.lower())
            uniq.append(n)
    return uniq


def author_names(pack: dict) -> List[str]:
    """Surnames named in the author line ("Hu et al.", "Chen et al. ... later Jiang et al.", or a list)."""
    a = pack.get("authors") or ""
    if isinstance(a, list):
        return [n.split()[-1] for n in a[:3] if n.split()]
    found = re.findall(r"([A-Z][\w'-]+)\s+(?:et\s+al|&|and\s)", a)
    return list(dict.fromkeys(found or ([a.split()[0]] if a.split() else [])))


def scrub(text: str, names: Iterable[str], authors: Iterable[str] = (), alias: str = ALIAS) -> str:
    if not text:
        return ""
    t = str(text)
    for rx, rep in SCRUB_RULES[:3]:          # links and ids first, before names inside them are touched
        t = rx.sub(rep, t)
    for n in names:
        flags = 0 if len(n) <= 3 else re.I
        # "Name++" (a variant the authors also name) is scrubbed with the name
        t = re.sub(r"(?<![\w-])" + re.escape(n) + r"(?:\+\+)?(?![\w-])", alias, t, flags=flags)
    for a in authors:
        if len(a) >= 2:
            t = re.sub(r"\b" + re.escape(a) + r"(\s+et\s+al\.?|\s*&\s*\w+)?(?=\W|$)", "[authors]", t)
    for rx, rep in SCRUB_RULES[3:]:
        t = rx.sub(rep, t)
    return re.sub(r"(\[(status|venue)\][\s,;]*){2,}", r"\1", t)


def _citer_date(citer: str) -> str:
    m = re.search(r"(\d{4})(-\d{2})?", citer or "")
    return m.group(0) if m else ""


def blind_pack(pack: dict, alias: str = ALIAS) -> str:
    """Render an evidence pack as text with everything that signals fame removed."""
    names, authors = names_for(pack), author_names(pack)

    def s(x) -> str:
        return scrub(x, names, authors, alias)

    card = pack.get("card") or {}
    lines = [f"Work: {alias}", f"Type: {pack.get('type') or 'unknown'}", f"First released: {pack.get('date') or 'unknown'}", "",
             "What it does",
             f"- Starts from: {s(card.get('inherits', ''))}",
             f"- Move: {s(card.get('move', ''))}",
             f"- Key insight: {s(card.get('insight', ''))}"]
    for lv in card.get("leaves") or []:
        lines.append(f"- Leaves open: {s(lv)}")
    lines += ["", "Its main claims, and how well its own experiments support them"]
    for c in pack.get("claims") or []:
        lines.append(f"- [{c.get('support', '?')}] {s(c.get('claim', ''))} | {s(c.get('evidence', ''))}")
    if pack.get("fairness_notes"):
        lines += ["", "Fairness notes (how the comparisons were set up)"]
        lines += [f"- {s(x)}" for x in pack["fairness_notes"]]
    if pack.get("reading_evidence"):
        lines += ["", "Evaluation validity and reading limits (not a verdict)", s(pack["reading_evidence"])]
    lines += ["", "Earlier work with a similar core idea"]
    precs = pack.get("precedents") or []
    if not precs:
        lines.append("- none found")
    for pr in precs:
        cited = {True: "cited by this work", False: "NOT cited by this work"}.get(pr.get("cited_by_target"), "citation unknown")
        lines.append(f"- {s(pr.get('title', ''))} ({pr.get('year') or '?'}): overlap {pr.get('overlap', '?')}; {cited}. {s(pr.get('note', ''))}")
    up = pack.get("uptake") or []
    counts = dict(pack.get("uptake_counts") or {})
    if not counts:
        for u in up:
            counts[u.get("role", "mentions")] = counts.get(u.get("role", "mentions"), 0) + 1
    lines += ["", "What later papers do with it"]
    if pack.get("uptake_basis"):
        lines.append(f"Sample: {s(pack['uptake_basis'])}")
    if counts:
        lines.append("Counts: " + ", ".join(f"{r} {counts[r]}" for r in ROLES if counts.get(r)))
    for k, u in enumerate(up):
        when = _citer_date(u.get("citer", ""))
        sent = s(u.get("sentence", ""))
        lines.append(f"- later paper {k + 1}{' (' + when + ')' if when else ''}: {u.get('role', '?')}" + (f": \"{sent}\"" if sent else ""))
    if pack.get("later_challenges"):
        lines += ["", "Later evidence that limits or contradicts it"]
        lines += [f"- {s(x)}" for x in pack["later_challenges"]]
    if pack.get("notes"):
        lines += ["", f"Other notes: {s(pack['notes'])}"]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- classification
def clamp01(x, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


def clean_contribution(r) -> dict:
    r = r if isinstance(r, dict) else {}
    parts = {k: clamp01(r.get(k)) for k in ("novelty", "significance", "evidence", "uptake")}
    default = 0.3 * parts["novelty"] + 0.3 * parts["significance"] + 0.2 * parts["evidence"] + 0.2 * parts["uptake"]
    return dict(parts, score=round(clamp01(r.get("score"), default), 3),
                type=r.get("type") if r.get("type") in TYPES else "method",
                rationale=str(r.get("rationale") or ""))


def quadrant(contrib: float, attn: float, lower_bound: bool, th: Thresholds) -> str:
    hc, lc = contrib >= th.contrib_high, contrib <= th.contrib_low
    ha, la = attn >= th.attn_high, attn <= th.attn_low
    if ha:
        return "classic" if hc else "hyped" if lc else "middle"
    if la and lower_bound:
        return "unknown"            # looks unnoticed only because the counts are missing
    if la:
        return "gem" if hc else "noise" if lc else "middle"
    return "middle"


def noticed(pack: dict, att: dict, th: Thresholds) -> str:
    """Why a work cannot be an unnoticed gem in absolute terms, or "" when nothing says it is noticed."""
    cpy, cites = att.get("citations_per_year"), pack.get("citations")
    if isinstance(cpy, (int, float)) and cpy >= th.gem_max_cites_per_year:
        return f"{cpy:.0f} citations a year"
    if isinstance(cites, (int, float)) and cites >= th.gem_max_cites:
        return f"{int(cites)} citations"
    fp = pack.get("field_pct")
    if isinstance(fp, (int, float)) and fp >= 0.9:
        return f"top {max(1, round(100 * (1 - fp)))}% of its field and year (OpenAlex)"
    return ""


def candidate(contrib: float, quad: str, months: int, th: Thresholds) -> Optional[str]:
    if months < th.too_early_months:
        return None
    if quad == "gem":
        return "hidden-gem"
    if quad == "hyped":
        return "overhyped"
    if contrib <= th.skip:
        return "skip"
    return None


def final_flag(cand: Optional[str], verdict: Optional[dict], months: int, th: Thresholds, thin: bool = False) -> str:
    if months < th.too_early_months:
        return "too-early"
    if thin:
        return "thin"
    if not cand:
        return "fair"
    v = (verdict or {}).get("verdict")
    if v not in VERDICTS:
        return cand                 # no review: keep the candidate as is
    if cand == "hidden-gem":
        under = (verdict or {}).get("under_noticed")      # the attention check, when it ran
        return "hidden-gem" if v == "substantial" and under is not False else "fair"
    return cand if v in ("negligible", "modest") else "fair"   # overhyped / skip


def why_line(flag: str, contrib: dict, verdict: Optional[dict]) -> str:
    reasons = (verdict or {}).get("reasons") or []
    if reasons:
        return str(reasons[0])
    text = contrib.get("rationale", "")
    return re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""


def is_thin(pack: dict) -> bool:
    """Read from an abstract or a summary card only. Such a work gets no blind score: the pack lacks the claims and
    experiments a score rests on, so any score would say more about the missing text than about the work."""
    return bool(pack.get("basis")) and pack.get("basis") != "full text"


UNSCORED = {"novelty": None, "significance": None, "evidence": None, "uptake": None, "score": None,
            "type": "method", "rationale": "", "unscored": True}


def assess_packs(packs: List[dict], scores: Dict[str, dict], today: str, th: Thresholds,
                 reviews: Optional[Dict[str, dict]] = None, reference: Optional[List[dict]] = None) -> Dict[str, dict]:
    """Combine attention, blind scores and (optional) reviews into one assessment per pack."""
    att = attention(packs, today, reference, th.ref_min)
    reviews = reviews or {}
    out = {}
    for p in packs:
        pid = p["id"]
        thin = is_thin(p)
        con = dict(UNSCORED) if thin else clean_contribution(scores.get(pid))
        a = att[pid]
        months = months_between(p.get("date", ""), today)
        quad = "unscored" if thin else quadrant(con["score"], a["pct"], a["lower_bound"], th)
        cand = None if thin else candidate(con["score"], quad, months, th)
        blocked = noticed(p, a, th) if cand == "hidden-gem" else ""
        if blocked:
            cand = None
        rev = reviews.get(pid) if cand else None
        judged = dict((rev or {}).get("judge") or {})
        if rev and isinstance(rev.get("attention"), dict) and rev["attention"].get("verdict") in ATTENTION:
            judged["under_noticed"] = rev["attention"]["verdict"] == "under-noticed"
        flag = final_flag(cand, judged or None, months, th, thin)
        out[pid] = {
            "attention": a, "contribution": con, "quadrant": quad, "candidate": cand or "",
            "months": months, "review": rev or None, "flag": flag, "label": LABELS[flag],
            "why": why_line(flag, con, (rev or {}).get("judge")),
            **({"gem_blocked": f"Not an unnoticed work: {blocked}."} if blocked else {}),
            "evidence": {k: p.get(k) for k in ("type", "claims", "fairness_notes", "precedents", "uptake",
                                               "reading_evidence", "eval_fit", "coverage", "verified",
                                               "uptake_counts", "uptake_basis", "later_challenges", "notes",
                                               "citations_note") if p.get(k) not in (None, "", [], {})},
        }
    return out


def audit_meta(assessments: Dict[str, dict], today: str, th: Thresholds, extra_caveats: Iterable[str] = ()) -> dict:
    counts = {f: 0 for f in FLAGS}
    for a in assessments.values():
        counts[a["flag"]] += 1
    reviewed = sum(1 for a in assessments.values() if a.get("review"))
    return {"today": today, "thresholds": asdict(th), "assessed": len(assessments), "reviewed": reviewed,
            "counts": counts, "method": METHOD_NOTE, "caveats": CAVEATS + list(extra_caveats),
            "labels": LABELS}


# ----------------------------------------------------------------------------- live pipeline
def attention_facts(pack: dict, att: dict) -> str:
    """The counts behind a work's attention, for the (non-blind) attention check."""
    rows = [f"Title: {pack.get('title', '')}", f"First released: {pack.get('date', '')}",
            f"Venue: {pack.get('venue') or 'unknown'}",
            f"Citations: {pack.get('citations') if pack.get('citations') is not None else 'unknown'}"
            + (" (known to be undercounted)" if att.get("citations_lower_bound") else ""),
            f"Citations per year: {att.get('citations_per_year') if att.get('citations_per_year') is not None else 'unknown'}",
            f"Percentile of citations per year: {att.get('citations_pct')} among {att.get('reference') or 'the assessed works'}"]
    if pack.get("stars") is not None:
        rows.append(f"Code repository stars: {pack['stars']}")
    if pack.get("field_pct") is not None:
        rows.append(f"OpenAlex citation percentile within its field and year: {pack['field_pct']}")
    counts = pack.get("uptake_counts") or {}
    if counts:
        rows.append("How a sample of citing papers use it: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return "\n".join(rows)


def card_text(pack: dict) -> str:
    c = pack.get("card") or {}
    return (f"Title: {pack.get('title', '')}\nFirst released: {pack.get('date', '')}\n"
            f"Starts from: {c.get('inherits', '')}\nMove: {c.get('move', '')}\nInsight: {c.get('insight', '')}\n"
            f"Leaves: {'; '.join(c.get('leaves') or [])}")


class Auditor:
    """Gathers evidence packs from the literature APIs, scores them blind and reviews flagged ones."""

    def __init__(self, cfg, source, llm, http=None, today: Optional[str] = None, th: Optional[Thresholds] = None,
                 openalex=None, reader=None):
        self.cfg, self.src, self.llm, self.http = cfg, source, llm, http
        self.oa = openalex
        # The gates' careful read of one paper (Gatekeeper.gate): works the gates did not read (the runners-up) are
        # read the same way as the map's papers, from the full text where it can be found.
        self.reader = reader
        self.today = today or dt.date.today().strftime("%Y-%m")
        self.th = th or Thresholds()
        self.rng = random.Random(7)

    # -- evidence ----------------------------------------------------------------
    def _fulltext(self, item: Item) -> tuple:
        """(text, basis[, coverage]): full-text selection carries its omissions into the claims check."""
        from tastecal.sources.fulltext import find_fulltext
        try:
            text, basis, _ = find_fulltext({"id": item.id, "title": item.title, "url": item.url}, item, self.http,
                                           getattr(self.cfg, "papers_dir", "papers"), getattr(self.cfg, "openalex_mailto", ""))
            if basis == "full text":
                from tastecal.sources.fulltext import select_for_reading
                shown, coverage = select_for_reading(text, 24000)
                return shown, basis, coverage
            return (text or item.abstract)[:40000], basis
        except Exception as e:  # offline, blocked
            log.info("no full text for %s: %s", item.title, e)
            return item.abstract, ("abstract" if item.abstract else "card")

    GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")

    def _stars(self, item: Item, pack: dict) -> None:
        """Stars of the code repository linked from the abstract or the arXiv page: a second attention signal."""
        if not self.http:
            return
        text = item.abstract or ""
        if item.ids.get("arxiv"):
            try:
                text += " " + self.http.get_text(f"https://arxiv.org/abs/{item.ids['arxiv']}")
            except Exception as e:
                log.info("arXiv page unavailable for %s: %s", item.title, e)
        m = self.GITHUB_RE.search(text)
        if not m:
            return
        name = m.group(2).rstrip(".")
        repo = f"{m.group(1)}/{name[:-4] if name.endswith('.git') else name}"
        token = os.environ.get("GITHUB_TOKEN", "")
        try:
            data = self.http.get_json(f"https://api.github.com/repos/{repo}",
                                      headers={"Authorization": f"Bearer {token}"} if token else None)
        except Exception as e:
            log.info("GitHub lookup failed for %s: %s", repo, e)
            return
        if isinstance(data, dict) and isinstance(data.get("stargazers_count"), int):
            pack["stars"], pack["repo"] = data["stargazers_count"], repo

    def _uptake(self, item: Item, pack: dict) -> None:
        cands = [c for c in self.src.citing_sample(item, self.cfg.citing_sample) if c.contexts]
        if not cands:
            return
        roles: List[str] = []
        for i in range(0, len(cands), 20):
            batch = cands[i:i + 20]
            rows = self.llm.json(P.AUDIT_SYSTEM, P.citation_roles([c.contexts[0] for c in batch]))
            got = {r.get("i"): r.get("role") for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
            roles += [got.get(k + 1) if got.get(k + 1) in ROLES else "mentions" for k in range(len(batch))]
        counts: Dict[str, int] = {}
        for r in roles:
            counts[r] = counts.get(r, 0) + 1
        pack["uptake_counts"] = counts
        pack["uptake_basis"] = (f"an even sample of the citers, not the most-cited ones ({len(cands)} citing sentences "
                                "classified); every paper in it cites the work")
        order = sorted(range(len(cands)), key=lambda k: (roles[k] not in SUBSTANTIVE, self.rng.random()))
        pack["uptake"] = [{"citer": f"{cands[k].item.title[:60]} ({cands[k].item.sort_date})", "role": roles[k],
                           "sentence": cands[k].contexts[0][:300]} for k in order[:8]]

    def _precedents(self, item: Item, pack: dict) -> None:
        mech = self.llm.json(P.AUDIT_SYSTEM, P.mechanism(card_text(pack)), note=False)
        mech = mech if isinstance(mech, dict) else {}
        found, seen = [], set()
        from tastecal.core.model import search_queries
        for q in search_queries(mech.get("queries"))[:2]:
            for it in self.src.search(q, None, limit=10, year_to=item.year):
                k = norm_title(it.title)
                if k in seen or title_similarity(it.title, item.title) > 0.8 or (it.sort_date or "") >= (item.sort_date or "9999"):
                    continue
                seen.add(k)
                found.append(it)
        if not found:
            return
        found = found[:10]
        cands = [{"id": f"c{k + 1}", "title": it.title, "year": it.year, "abstract": it.abstract} for k, it in enumerate(found)]
        rows = self.llm.json(P.AUDIT_SYSTEM, P.precedents(mech.get("mechanism", ""), item.sort_date, cands))
        refs = {norm_title(c.item.title) for c in self.src.backward(item, item.id)}
        out = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict) or r.get("overlap") not in ("same idea", "partial"):
                continue
            k = next((j for j, c in enumerate(cands) if c["id"] == r.get("id")), None)
            if k is None:
                continue
            it = found[k]
            out.append({"title": it.title, "year": it.year, "url": it.url, "overlap": r["overlap"],
                        "cited_by_target": norm_title(it.title) in refs, "note": r.get("note", "")})
        pack["precedents"] = sorted(out, key=lambda x: x["overlap"] != "same idea")[:3]

    def gather(self, item: Item, card: dict, short: str = "", challenges: Optional[List[str]] = None,
               reading: Optional[dict] = None) -> dict:
        """Evidence pack for one work. `reading` is the gates' careful read of the same paper: when it carries
        claims, the audit uses them instead of reading the paper a second time."""
        pack = {"id": item.id, "title": item.title, "short": short or item.title.split(":")[0][:40],
                "authors": item.author_line(), "date": item.sort_date, "venue": item.venue, "url": item.url,
                "citations": item.citations, "citations_note": "Semantic Scholar (all versions merged)",
                "citations_lower_bound": item.citations is None, "type": "", "card": card,
                "claims": [], "fairness_notes": [], "precedents": [], "uptake": [],
                "later_challenges": list(challenges or []), "notes": ""}
        if reading is None and self.reader:
            node = {"id": item.id, "title": item.title, "date": item.sort_date, "url": item.url, "card": card}
            try:
                reading = self.reader(node, item)
            except Exception as e:
                log.warning("shared reading failed for %s: %s", item.title, e)
        if reading:
            from tastecal.judge.gates import evidence_line
            pack["basis"] = reading.get("basis") or ""
            pack["reading_evidence"] = evidence_line(reading)
            for key in ("eval_fit", "coverage", "verified"):
                if isinstance(reading.get(key), dict):
                    pack[key] = dict(reading[key])
        if reading and reading.get("claims"):
            pack["claims"] = [c for c in reading["claims"] if isinstance(c, dict)][:4]
            pack["fairness_notes"] = [x for x in reading.get("fairness_notes") or [] if isinstance(x, str)][:5]
            pack["notes"] = f"Claims checked in the shared reading ({reading.get('source') or reading.get('basis', '')})."
        else:
            try:
                got = self._fulltext(item)
                text, pack["basis"] = got[:2]
                if len(got) > 2:
                    from tastecal.sources.fulltext import coverage_note
                    pack["coverage"] = got[2]
                    limits = coverage_note(got[2])
                    pack["reading_evidence"] = " ".join(filter(None, [pack.get("reading_evidence"), limits]))
                    text = limits + "\n\n" + text
                res = self.llm.json(P.AUDIT_SYSTEM, P.claims_check(card_text(pack), text))
                if isinstance(res, dict):
                    pack["claims"] = [c for c in res.get("claims") or [] if isinstance(c, dict)][:4]
                    pack["fairness_notes"] = [x for x in res.get("fairness_notes") or [] if isinstance(x, str)][:5]
            except Exception as e:
                log.warning("claims check failed for %s: %s", item.title, e)
        self._uptake(item, pack)
        self._precedents(item, pack)
        self._stars(item, pack)
        self._field_rank(item, pack)
        return pack

    def _field_rank(self, item: Item, pack: dict) -> None:
        """OpenAlex's citation percentile among works of the same field and year: an absolute attention check."""
        if not self.oa:
            return
        try:
            wid = item.ids.get("openalex") or self.oa.find(item)
            got = self.oa.percentile(wid) if wid else None
        except Exception as e:  # offline, rate limited
            log.info("OpenAlex field percentile unavailable for %s: %s", item.title, e)
            return
        if got and isinstance(got.get("value"), (int, float)):
            pack["field_pct"] = round(float(got["value"]), 3)

    # -- judgement ----------------------------------------------------------------
    def score(self, pack: dict) -> dict:
        return clean_contribution(self.llm.json(P.AUDIT_SYSTEM, P.contribution_blind(blind_pack(pack))))

    def review(self, pack: dict, cand: str = "", att: Optional[dict] = None) -> dict:
        text = blind_pack(pack)
        adv = self.llm.json(P.AUDIT_SYSTEM, P.advocate(text))
        crit = self.llm.json(P.AUDIT_SYSTEM, P.critic(text))
        adv = adv if isinstance(adv, dict) else {}
        crit = crit if isinstance(crit, dict) else {}
        judge = self.llm.json(P.AUDIT_SYSTEM, P.judge(text, adv, crit))
        judge = judge if isinstance(judge, dict) else {}
        if judge.get("verdict") not in VERDICTS:
            judge["verdict"] = "modest"
        out = {"advocate": adv, "critic": crit, "judge": judge}
        if cand == "hidden-gem":
            # The blind steps only judge the contribution. Whether the work is really unnoticed needs the counts.
            chk = self.llm.json(P.AUDIT_SYSTEM, P.attention_check(attention_facts(pack, att or {})))
            if isinstance(chk, dict) and chk.get("verdict") in ATTENTION:
                out["attention"] = {"verdict": chk["verdict"], "why": str(chk.get("why") or "")[:400]}
        return out

    def run(self, packs: List[dict], reference: Optional[List[dict]] = None) -> Dict[str, dict]:
        scores = {}
        for p in packs:
            if is_thin(p):
                log.info("audit: %s was read from the %s only, so it gets no blind score", p.get("short") or p.get("title"),
                         p.get("basis"))
            else:
                scores[p["id"]] = self.score(p)
        first = assess_packs(packs, scores, self.today, self.th, reference=reference)
        reviews = {}
        if self.cfg.review:
            for p in packs:
                f = first[p["id"]]
                if f["candidate"]:
                    log.info("adversarial review: %s (%s)", p.get("short"), f["candidate"])
                    reviews[p["id"]] = self.review(p, f["candidate"], f["attention"])
        return assess_packs(packs, scores, self.today, self.th, reviews, reference)


# ----------------------------------------------------------------------------- graph merge
def merge_into_graph(graph: dict, assessments: Dict[str, dict], meta: dict,
                     pool: Optional[List[dict]] = None) -> dict:
    """Attach assessments to map nodes, add extra assessed works as graph['pool'], set graph['audit']."""
    ids = {n["id"] for n in graph["nodes"]}
    for n in graph["nodes"]:
        if n["id"] in assessments:
            n["assessment"] = assessments[n["id"]]
    if pool is not None:
        graph["pool"] = []
        for w in pool:
            if w["id"] in ids:
                continue
            entry = {k: w.get(k) for k in ("id", "title", "short", "kind", "date", "year", "authors", "venue",
                                           "url", "citations", "card", "near", "reason") if w.get(k) is not None}
            entry.setdefault("kind", "paper")
            if w["id"] in assessments:
                entry["assessment"] = assessments[w["id"]]
            graph["pool"].append(entry)
    graph["audit"] = meta
    from tastecal.judge.quality import combine
    combine(graph)
    return graph


# ----------------------------------------------------------------------------- stage entry points
def challenges_for(graph: dict, nid: str) -> List[str]:
    """Later works on the map that challenge `nid` (edges read LATER <type> EARLIER: source is earlier)."""
    short = {n["id"]: n.get("short", n["id"]) for n in graph["nodes"]}
    return [f"{short.get(e['target'], e['target'])}: {e.get('label', '')}" + (f" (\"{e['evidence']}\")" if e.get("evidence") else "")
            for e in graph.get("edges", []) if e.get("source") == nid and e.get("type") == "challenges"]


def audit(graph: dict, targets: List[dict], auditor: "Auditor", pool: Optional[List[dict]] = None,
          readings: Optional[Dict[str, dict]] = None, reference: Optional[List[dict]] = None) -> dict:
    """targets: [{"item": Item, "card": {...}, "short": str}] with item.id equal to the graph id.
    pool: extra works (same shape plus "near", "reason") shown under "also considered"."""
    packs = []
    for t in (targets + list(pool or []))[: (auditor.cfg.assess_max or None)]:
        it = t["item"]
        log.info("audit: gathering evidence for %s", t.get("short") or it.title)
        packs.append(auditor.gather(it, t.get("card") or {}, t.get("short", ""), challenges_for(graph, it.id),
                                    (readings or {}).get(it.id)))
    assessments = auditor.run(packs, reference)
    # Your rated papers are not read here: the taste calibration (`fit`) reads them and measures them on your own
    # clauses, so a blind score of them would only be a second, different taste score.
    extra = []
    if any(p.get("citations_lower_bound") for p in packs):
        extra.append("Some citation counts were unavailable; those works are marked as lower bounds.")
    pool_rows = None
    if pool is not None:
        pool_rows = [{"id": t["item"].id, "title": t["item"].title, "short": t.get("short", ""), "kind": t["item"].kind,
                      "date": t["item"].sort_date, "year": t["item"].year, "authors": t["item"].author_line(),
                      "venue": t["item"].venue, "url": t["item"].url, "citations": t["item"].citations,
                      "card": t.get("card"), "near": t.get("near", ""), "reason": t.get("reason", "")} for t in pool]
    if not reference or len(reference) < auditor.th.ref_min:
        extra.append("Attention is ranked within the assessed works only, which were picked as the important ones, so "
                     "a well-cited work can look unnoticed. Possible gems are still checked against absolute ceilings.")
    meta = audit_meta(assessments, auditor.today, auditor.th, extra)
    if reference:
        meta["reference"] = len(reference)
        meta["reference_values"] = reference
    return merge_into_graph(graph, assessments, meta, pool_rows)


def targets_from_grower(grower, graph: dict) -> tuple:
    """Map items (after synthesis re-keyed them) and the best runners-up, with cards."""
    from tastecal.core.model import Node, slugify
    targets = [{"item": n.item, "card": next((x["card"] for x in graph["nodes"] if x["id"] == n.item.id), {}),
                "short": n.card.short if n.card else ""}
               for n in sorted(grower.nodes.values(), key=lambda n: (n.item.id != grower.seed_id, n.item.sort_date))
               if n.item.kind == "paper" and not n.borrowed]
    rows = grower.pool(grower.cfg.assess_pool)
    nodes = [Node(item=c.item, card=None) for _, c, _ in rows]
    grower._make_cards(nodes)
    taken = {n["id"] for n in graph["nodes"]}
    pool = []
    for (anchor, c, r), node in zip(rows, nodes):
        node.item.id = slugify(node.card.short if node.card else node.item.title, taken)
        card = {k: getattr(node.card, k) for k in ("inherits", "move", "insight", "leaves", "summary")} if node.card else {}
        pool.append({"item": node.item, "card": card, "short": node.card.short if node.card else "",
                     "near": anchor.item.id, "reason": r.get("label", "")})
    from tastecal.judge.quality import pick_for_reading
    budget = grower.cfg.assess_max
    if not budget:                                     # no limit: every paper on the map, and the runners-up
        return targets, pool
    by_id = {t["item"].id: t for t in targets}
    rows = [{"id": t["item"].id, "date": t["item"].sort_date, "role": "seed" if t["item"].id == grower.seed_id else ""}
            for t in targets]
    keep = [by_id[r["id"]] for r in pick_for_reading(rows, grower.seed_id, graph.get("edges", []), budget)]
    return keep, pool[: max(0, budget - len(keep))]
