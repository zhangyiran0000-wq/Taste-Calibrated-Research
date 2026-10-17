"""Gates: which works earn a station on the map, and which are worth reading.

Runs after synthesis (and after the optional attention audit). Gates 0-2 read the work's own
full text; Gate 3 reads the graph.

  0  claim vs delivery  Does the work show what its title and abstract claim?
                        delivered | partial | not, plus what it really delivered.
  1  reason             Why should it work, and when would it not?
                        proof | mechanism | analogy | none.
  2  robustness         Do the gains repeat across settings, and which levers sit behind the number?
                        repeats | single | unclear, plus a list of levers.
  3  field reaction     Later works on the map that adopt it versus challenge it (with the attention
                        audit's citer sample when present). Skipped for works too recent to have one.

A taste profile (a short text file written by the reader) scores how attractive each work is.
Only the treasure verdict and the reading order read that score. The gate prompt never sees the
profile, so taste can decide what is worth reading but not how the evidence is judged. The taste
scorer does see what the gate read found in the paper (what it delivers, the levers shown, the
fairness checks), because readers' tastes are often about evidence ("gains that come from tuning
are not interesting") and a summary card does not carry those details.

Verdicts follow from the gate answers by fixed rules:

  not-delivered  the headline claim is not realised                          -> folded
  treasure       a reason, not yet robust, and attractive to the reader      -> station, reading list
  solid          delivered, with a reason (proof or mechanism) or robustness,
                 and the gain is not confounded                              -> station
  unattributed   delivered, but the gain may come from something other than
                 the idea (a lever shown in the text, unfair baselines with no
                 ablation of the new part, a headline number the tables do
                 not back)                                                   -> station, marked
  incremental    delivered, but neither a reason nor robustness              -> folded

A mechanism only counts as a reason when the paper itself says when the method would not help
(fails_when_stated), and the sentence it quotes for that is found in the text. A causal story the
paper never bounds is not a reason.

Levers only count when the reader marked them "present" and pointed to where they show. A lever the
reader merely suspects, or one the paper controls for, is listed but does not change the verdict.
A work the field has adopted (Gate 3) is not marked unattributed: others building on it is evidence
that the idea, not a lever, carries the gain.

A folded work is hidden behind a "+N other attempts" badge on its line. Every fold carries a
reason: a one-line summary plus evidence taken from the text (where the claim fails, what was and
was not tested, which levers sit behind the number). A work is folded only when it was read from
the full text and that evidence exists; the seed is never folded. Otherwise it stays on the map,
with the verdict and the reason it was kept (fold_blocked). A problem whose only "solutions" were
not delivered goes back to open, with status "claimed".
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from tastecal.prompts import gates as P
from tastecal.judge.audit import clamp01, months_between

log = logging.getLogger("tastecal.gates")

DELIVERY = ("delivered", "partial", "not")
REASON_TYPES = ("proof", "mechanism", "analogy", "none")
ROBUSTNESS = ("repeats", "single", "unclear")
LEVERS = ("cost-assumption", "metric-trained", "unequal-tuning", "mismatched-setup",
          "small-or-saturated-benchmark", "missing-novelty-ablation", "other")
LEVER_STATUS = ("present", "controlled", "suspected")
# Levers that, when shown in the text, can by themselves produce the headline number.
SERIOUS_LEVERS = ("unequal-tuning", "mismatched-setup", "metric-trained", "cost-assumption")
PARTIAL_KINDS = ("narrower", "unisolated")
VERDICTS = ("solid", "treasure", "unattributed", "incremental", "not-delivered")
FOLDED = ("incremental", "not-delivered")
BASES = ("full text", "abstract", "card")
LABELS = {"solid": "Solid", "treasure": "Treasure candidate", "unattributed": "Gain not attributed",
          "incremental": "Incremental", "not-delivered": "Claim not delivered"}
SKEW_SHARE = 0.7          # a verdict given to more than this share of works is reported as a warning
SKEW_MIN = 8              # ... once at least this many works were gated
ADOPT_TYPES = ("extends", "applies", "inspires", "resolves")   # later work keeps the earlier work's idea
FULL_TEXT_MIN = 4000                                          # shorter "full texts" are treated as abstracts

METHOD_NOTE = (
    "Each work was read from its own text and passed through four checks in order. 0: does it deliver what its "
    "title and abstract claim, or does the gain come from something else? 1: does it say why it should work, in a "
    "way that also says when it would not (a proof or a mechanism, rather than an analogy or nothing)? 2: do the "
    "gains repeat beyond one setting, and which levers (chosen cost ratios, components trained on the metric, "
    "unequal tuning, mismatched setups, small benchmarks, a missing ablation) could produce the number without the "
    "idea? 3: did later works on the map build on it or challenge it? A method needs a reason or robust evidence. "
    "A reason only counts when the sentence the reader quotes for it is found in the text. When the text shows a lever "
    "that could produce the number, or the baselines were not treated equally and no experiment removes only the new "
    "idea, the work is marked 'gain not attributed' instead of solid, unless later works on the map build on it. "
    "Works that fail check 0, or pass it with neither a reason nor robust evidence, are folded. A taste profile, when given, only decides which "
    "reasoned but unverified works are worth reading; the checks never see it.")
CAVEATS = [
    "Verdicts are a reading aid, not a ruling. Open the drawer to see the evidence behind each one.",
    "Every folded work shows why: a summary and the evidence from its text. A verdict without evidence never folds a work.",
    "Only works read from the full text are folded; works read from an abstract or a card stay on the map.",
    "The field-reaction check only sees later works that made it onto this map, plus the audit's citer sample when present.",
    "A model judged the text. It can miss an ablation buried in an appendix, or take a claim too literally.",
]


@dataclass
class GateThresholds:
    attractive: float = 0.6        # taste score at or above which an idea counts as attractive
    too_early_months: int = 6      # younger works get no field-reaction check
    adopted_min: int = 2           # later works on the map that build on it, for field robustness
    builds_on_share: float = 0.15  # ... or this share of the audit's citer sample building on it


# ----------------------------------------------------------------------------- cleaning
def _s(x, n: int = 600) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()[:n]


def clean_gates(r) -> Optional[dict]:
    """Normalise one gates_audit answer. None when it cannot be used."""
    if not isinstance(r, dict):
        return None
    d, rt, rb = r.get("delivery"), r.get("reason_type"), r.get("robustness")
    if d not in DELIVERY or rt not in REASON_TYPES:
        return None
    levers: List[dict] = []
    for lv in r.get("levers") or []:
        if isinstance(lv, dict) and lv.get("lever"):
            name = str(lv["lever"]).strip()
            status = str(lv.get("status") or "").strip().lower()
            row = {"lever": name if name in LEVERS else "other",
                   "note": _s(lv.get("note") or ("" if name in LEVERS else name), 300),
                   # Answers from before statuses existed listed every lever that *could* matter: suspected.
                   "status": status if status in LEVER_STATUS else "suspected"}
            if _s(lv.get("where")):
                row["where"] = _s(lv.get("where"), 200)
            levers.append(row)
        elif isinstance(lv, str) and lv.strip():
            name = lv.strip()
            levers.append({"lever": name if name in LEVERS else "other", "note": "" if name in LEVERS else _s(name, 300),
                           "status": "suspected"})
    levers.sort(key=lambda lv: LEVER_STATUS.index(lv["status"]))      # shown levers first
    out = {"claimed": _s(r.get("claimed")), "delivery": d, "delivered": _s(r.get("delivered")),
           "delivery_evidence": _s(r.get("delivery_evidence")), "reason_type": rt, "reason": _s(r.get("reason")),
           "fails_when": _s(r.get("fails_when")), "robustness": rb if rb in ROBUSTNESS else "unclear",
           "robustness_note": _s(r.get("robustness_note")), "levers": levers[:6],
           "check_next": _s(r.get("check_next"))}
    if d == "partial" and r.get("partial_kind") in PARTIAL_KINDS:
        out["partial_kind"] = r["partial_kind"]
    fws = r.get("fails_when_stated")
    if isinstance(fws, bool):
        out["fails_when_stated"] = fws
    ver = r.get("verified")
    if isinstance(ver, dict):
        out["verified"] = {k: v for k, v in ver.items() if isinstance(v, bool)}
    checks = clean_checks(r.get("checks"))
    if checks:
        out["checks"] = checks
    claims = [{"claim": _s(c.get("claim"), 300), "support": c.get("support") if c.get("support") in SUPPORT else "untested",
               "evidence": _s(c.get("evidence"), 300)} for c in r.get("claims") or [] if isinstance(c, dict) and c.get("claim")]
    if claims:
        out["claims"] = claims[:4]
    notes = [_s(x, 300) for x in r.get("fairness_notes") or [] if isinstance(x, str) and x.strip()]
    if notes:
        out["fairness_notes"] = notes[:5]
    return out


SUPPORT = ("supported", "partial", "unsupported", "untested")
CHECK_VALUES = {"numbers": ("match", "mismatch", "not checked"), "fair_baselines": ("yes", "no", "unclear"),
                "novelty_ablation": ("yes", "no"), "code": ("released", "promised", "none", "unknown"),
                "numbers_severity": ("headline", "minor")}
CHECK_NOTES = {"numbers": "numbers_note", "fair_baselines": "baselines_note", "novelty_ablation": "ablation_note",
               "code": "code_note"}


def clean_checks(c) -> Optional[dict]:
    """The deeper read's four checks. Unknown values are dropped rather than guessed."""
    if not isinstance(c, dict):
        return None
    out = {}
    for k, allowed in CHECK_VALUES.items():
        v = str(c.get(k) or "").strip().lower()
        if v in allowed:
            out[k] = v
            note = _s(c.get(CHECK_NOTES[k]), 300) if k in CHECK_NOTES else ""
            if note:
                out[CHECK_NOTES[k]] = note
    return out or None


# ----------------------------------------------------------------------------- quote checks
def _norm_words(text: str) -> List[str]:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).split()


def quote_in_text(quote: str, text: str, min_words: int = 5) -> Optional[bool]:
    """Is `quote` (roughly) in `text`? None when there is nothing to check against.

    Exact after normalising case, punctuation and spacing; otherwise true when at least 70% of the quote's words
    appear in order in one stretch of the text, including an unbroken run of at least `min_words`. Short or empty quotes are false."""
    if not text or len(text) < 200:
        return None
    q = _norm_words(quote)
    if len(q) < min_words:
        return False
    t = _norm_words(text)
    tj, qj = " " + " ".join(t) + " ", " " + " ".join(q) + " "
    if qj in tj:
        return True
    from difflib import SequenceMatcher
    need = max(min_words, int(0.7 * len(q) + 0.999))
    first = set(q)
    # Only look near words the quote uses, so a long paper stays cheap.
    for i in range(len(t)):
        if t[i] not in first:
            continue
        window = t[i:i + len(q) + 10]
        blocks = SequenceMatcher(None, q, window, autojunk=False).get_matching_blocks()
        if sum(b.size for b in blocks) >= need and max(b.size for b in blocks) >= min_words:
            return True
    return False


def clean_taste(r) -> Optional[dict]:
    if not isinstance(r, dict) or r.get("score") is None:
        return None
    return {"score": round(clamp01(r.get("score")), 3), "why": _s(r.get("why"), 300)}


# ----------------------------------------------------------------------------- rules
def reaction(graph: dict, nid: str, months: int, th: GateThresholds) -> dict:
    """Gate 3. Edges read LATER <type> EARLIER, so the earlier work is the edge's source."""
    adopted: List[str] = []
    challenged: List[str] = []
    for e in graph.get("edges", []):
        if e.get("source") != nid:
            continue
        if e.get("type") in ADOPT_TYPES:
            adopted.append(e.get("target"))
        elif e.get("type") == "challenges":
            challenged.append(e.get("target"))
    adopted, challenged = list(dict.fromkeys(adopted)), list(dict.fromkeys(challenged))
    node = next((n for n in graph.get("nodes", []) if n.get("id") == nid), {})
    counts = (((node.get("assessment") or {}).get("evidence") or {}).get("uptake_counts")) or {}
    total = sum(v for v in counts.values() if isinstance(v, (int, float)))
    share = round(counts.get("builds_on", 0) / total, 3) if total else None
    too_early = months < th.too_early_months
    broad = len(adopted) >= th.adopted_min or (share is not None and share >= th.builds_on_share)
    robust = (not too_early) and broad and len(challenged) <= len(adopted)
    return {"adopted_by": adopted, "challenged_by": challenged, "builds_on_share": share,
            "too_early": too_early, "robust": robust}


def bounded(g: dict) -> bool:
    """Does the paper say when its mechanism would not help? The quote must be found in the text when the text
    was checked; answers without a check fall back to the reader's own yes or no."""
    found = (g.get("verified") or {}).get("fails_when")
    if found is not None:
        return found
    return g.get("fails_when_stated") is not False


def has_reason(g: dict) -> bool:
    return g["reason_type"] == "proof" or (g["reason_type"] == "mechanism" and bounded(g))


CONF_TXT = {
    "en": {"unfair": "Baselines not treated equally, and no experiment removes only the new idea",
           "unisolated": "The new part's own effect is not isolated",
           "numbers": "Headline number not backed by the paper's own tables",
           "why": "The gain may come from something other than the idea."},
    "zh": {"unfair": "基线没有得到同等对待，也没有只去掉新想法的消融实验",
           "unisolated": "新组件自身的作用没有被单独验证",
           "numbers": "核心数字在论文自己的表格里找不到依据",
           "why": "增益可能来自想法之外的因素。"},
}
LEVER_ZH = {"cost-assumption": "作者自选的成本或价格比", "metric-trained": "在评测指标上训练的组件",
            "unequal-tuning": "基线没有得到的调参", "mismatched-setup": "不对等的实验设置",
            "small-or-saturated-benchmark": "小或已饱和的基准", "missing-novelty-ablation": "缺少对新想法的消融",
            "other": "其他杠杆"}


def _lang(graph: Optional[dict]) -> str:
    return "zh" if str(((graph or {}).get("meta") or {}).get("language", "")).lower().startswith("zh") else "en"


def confounders(g: dict, lang: str = "en") -> List[str]:
    """Why the gain may come from something other than the idea, each with its pointer. [] when nothing is shown.

    - a serious lever marked "present" with a note saying where it shows;
    - baselines that did not get the same data, inputs, compute or tuning, with no experiment that removes only
      the new idea (with such an ablation, the comparison inside the paper is still fair);
    - a "partial" delivery because the new part's own effect is not isolated, with no such ablation;
    - a headline number the paper's own tables do not back."""
    out: List[str] = []
    T = CONF_TXT.get(lang, CONF_TXT["en"])
    sep = "：" if lang == "zh" else ": "
    ck = g.get("checks") or {}
    ablated = ck.get("novelty_ablation") == "yes"
    for lv in g.get("levers") or []:
        if lv.get("status") == "present" and lv.get("lever") in SERIOUS_LEVERS and _real(lv.get("note")):
            name = LEVER_ZH.get(lv["lever"], "") if lang == "zh" else ""
            line = f"{name}{sep}{lv['note']}" if name else _lever_line(lv)
            out.append(line + (f" ({lv['where']})" if lv.get("where") else ""))
    if ck.get("fair_baselines") == "no" and not ablated:
        out.append(T["unfair"] + (f"{sep}{ck['baselines_note']}" if _real(ck.get("baselines_note")) else "."))
    if g.get("delivery") == "partial" and g.get("partial_kind") == "unisolated" and not ablated:
        out.append(T["unisolated"] + (f"{sep}{g['delivery_evidence']}" if _real(g.get("delivery_evidence")) else "."))
    if ck.get("numbers") == "mismatch" and ck.get("numbers_severity") == "headline" and _real(ck.get("numbers_note")):
        out.append(f"{T['numbers']}{sep}{ck['numbers_note']}")
    return out


def verdict(g: dict, react: dict, attract: Optional[float], th: GateThresholds) -> str:
    if g["delivery"] == "not":
        return "not-delivered"
    reasoned = has_reason(g)
    robust = g["robustness"] == "repeats" or bool(react.get("robust"))
    if not (reasoned or robust):
        return "incremental"
    # It would earn a station; but if the text shows the gain may come from a lever, say so instead of "solid".
    # Adoption by later works on the map overrides this: others building on it credit the idea, not the lever.
    if confounders(g) and not react.get("robust"):
        return "unattributed"
    if reasoned and not robust and (attract is None or attract >= th.attractive):
        return "treasure"
    return "solid"


REASON_TXT = {"proof": "a proof", "mechanism": "a mechanism", "analogy": "an analogy only", "none": "no reason"}
ROBUST_TXT = {"repeats": "evidence that repeats", "single": "evidence from one setting", "unclear": "unclear evidence"}
LEVER_TXT = {"cost-assumption": "a chosen cost or price ratio", "metric-trained": "a component trained on the metric",
             "unequal-tuning": "tuning the baselines did not get", "mismatched-setup": "a mismatched setup",
             "small-or-saturated-benchmark": "a small or saturated benchmark",
             "missing-novelty-ablation": "no ablation of the new idea", "other": "another lever"}


def why_line(v: str, g: dict, react: dict, lang: str = "en") -> str:
    if v == "not-delivered":
        return f"Claims: {g['claimed'] or 'see the abstract'}. Really delivers: {g['delivered'] or 'unclear'}."
    if v == "treasure":
        return f"Reason: {(g['reason'] or REASON_TXT[g['reason_type']]).rstrip('. ')}. Not yet verified beyond one setting." + (
            f" Check next: {g['check_next']}" if g["check_next"] else "")
    if v == "unattributed":
        why = confounders(g, lang)
        end = "。" if lang == "zh" else "."
        return CONF_TXT.get(lang, CONF_TXT["en"])["why"] + (" " if lang != "zh" else "") + (
            why[0].rstrip(".。") + end if why else "")
    if v == "solid":
        if has_reason(g) and g["reason"]:
            return f"Reason: {g['reason']}"
        if react.get("robust"):
            return f"No stated reason, but {len(react['adopted_by'])} later works on the map build on it."
        return g["robustness_note"] or "Gains repeat across settings."
    lever = (g["levers"] or [{}])[0]
    tail = (f" Main lever: {LEVER_TXT.get(lever.get('lever'), 'another lever')}"
            + (f" ({lever['note']})" if lever.get("note") else "") + ".") if lever else ""
    return f"Delivered, with {REASON_TXT[g['reason_type']]} and {ROBUST_TXT[g['robustness']]}.{tail}"


BOILERPLATE = {"", "none", "none given", "n/a", "na", "unclear", "unknown", "not stated", "not given", "-"}


def _real(x) -> bool:
    return _s(x).lower().strip(" .") not in BOILERPLATE


def _lever_line(lv: dict) -> str:
    name = LEVER_TXT.get(lv.get("lever"), "another lever")
    name = name[0].upper() + name[1:]
    return f"{name}: {lv['note']}" if lv.get("note") else name


def fold_reason(v: str, g: dict) -> Optional[dict]:
    """Why a work does not earn a station: a summary and the evidence for it, taken from the gate answer.
    None for verdicts that keep a station."""
    levers = [_lever_line(lv) for lv in g["levers"]]
    if v == "not-delivered":
        summary = "The experiments do not show what the title and abstract claim."
        if _real(g["claimed"]):
            summary += f" Claims: {g['claimed'].rstrip('.')}."
        if _real(g["delivered"]):
            summary += f" Shows: {g['delivered'].rstrip('.')}."
        evidence = [g["delivery_evidence"]] + levers
        needs = _real(g["claimed"]) and _real(g["delivered"])
    elif v == "incremental":
        summary = (f"It delivers its claim, but gives {REASON_TXT[g['reason_type']]} for why it should work "
                   f"and {ROBUST_TXT[g['robustness']]}.")
        evidence = [g["robustness_note"]]
        if g["reason_type"] == "analogy" and _real(g["reason"]):
            evidence.append(f"Its only justification is an analogy: {g['reason'].rstrip('.')}.")
        evidence += levers
        needs = True
    else:
        return None
    evidence = [e for e in evidence if _real(e)][:5]
    return {"summary": summary, "evidence": evidence, "sufficient": bool(needs and evidence)}


def split_ledger(graph: dict) -> int:
    """Move 'solutions' that were not delivered from addressed_by to claimed_by. Idempotent.
    Returns how many problems are now only claimed."""
    status = {n["id"]: (n.get("gates") or {}).get("verdict") for n in graph.get("nodes", [])}
    only_claimed = 0
    for p in graph.get("problems", []):
        every = list(dict.fromkeys(list(p.get("addressed_by") or []) + list(p.get("claimed_by") or [])))
        p["addressed_by"] = [x for x in every if status.get(x) != "not-delivered"]
        p["claimed_by"] = [x for x in every if status.get(x) == "not-delivered"]
        p["status"] = "addressed" if p["addressed_by"] else ("claimed" if p["claimed_by"] else "open")
        only_claimed += p["status"] == "claimed"
    return only_claimed


def gates_meta(graph: dict, today: str, th: GateThresholds, taste: bool, reopened: int, taste_name: str = "") -> dict:
    gated = [n for n in graph.get("nodes", []) if n.get("gates")]
    counts = {v: 0 for v in VERDICTS}
    for n in gated:
        counts[n["gates"]["verdict"]] += 1
    caveats = list(CAVEATS)
    skew = None
    if len(gated) >= SKEW_MIN:
        top = max(counts, key=lambda v: counts[v])
        share = counts[top] / len(gated)
        if share > SKEW_SHARE:
            skew = {"verdict": top, "share": round(share, 3)}
            caveats.insert(0, f"{counts[top]} of {len(gated)} works got the same verdict ({LABELS[top]}). The checks "
                              "may not be telling these works apart; read the evidence rather than the label.")
            log.warning("gates: %d of %d works are '%s'; the verdicts may not discriminate", counts[top], len(gated), top)
    return {"today": today, "thresholds": asdict(th), "gated": len(gated),
            "folded": sum(1 for n in gated if n["gates"]["fold"]), "reopened": reopened, "taste": taste,
            "counts": counts, "labels": LABELS, "method": METHOD_NOTE, "caveats": caveats,
            **({"skew": skew} if skew else {}), **({"taste_name": taste_name} if taste_name else {})}


def apply_gates(graph: dict, raw: Dict[str, dict], taste: Optional[Dict[str, dict]] = None,
                today: Optional[str] = None, th: Optional[GateThresholds] = None, taste_name: str = "") -> dict:
    """Merge gate answers into the graph: node['gates'], the problem ledger, graph['gates'].

    raw:   {node id: gates_audit answer, plus "basis" ("full text" | "abstract" | "card")}.
           An answer may carry its own "taste": {"score", "why"}.
    taste: {node id: {"score", "why"}}; None or {} when no profile was given.
    Nodes missing from `raw` keep any gates they already had."""
    th = th or GateThresholds()
    today = today or dt.date.today().strftime("%Y-%m")
    taste = dict(taste or {})
    seed = (graph.get("meta") or {}).get("seed")
    lang = _lang(graph)
    have_taste = bool(taste) or any(isinstance(r, dict) and r.get("taste") for r in raw.values())
    for n in graph.get("nodes", []):
        r = raw.get(n["id"])
        if r is None:
            continue
        g = clean_gates(r)
        if g is None:
            log.warning("gates: unusable answer for %s", n["id"])
            continue
        basis = r.get("basis") if r.get("basis") in BASES else "card"
        t = clean_taste(taste.get(n["id"]) or r.get("taste"))
        months = months_between(n.get("date", ""), today)
        react = reaction(graph, n["id"], months, th)
        v = verdict(g, react, t["score"] if t else None, th)
        is_seed = n["id"] == seed or n.get("role") == "seed"
        reason = fold_reason(v, g)
        blocked = ""
        if reason:
            if is_seed:
                blocked = "The seed is never folded."
            elif basis != "full text":
                blocked = f"Read from the {basis} only, so it stays on the map."
            elif not reason["sufficient"]:
                blocked = "The verdict came without evidence from the text, so it stays on the map."
        fold = bool(reason) and not blocked
        n["gates"] = dict(g, basis=basis, months=months, reaction=react,
                          attractiveness=t["score"] if t else None, taste_why=t["why"] if t else "",
                          verdict=v, label=LABELS[v], why=reason["summary"] if reason else why_line(v, g, react, lang),
                          **({"confounders": confounders(g, lang)} if v == "unattributed" else {}),
                          fold=fold, fold_reason={"summary": reason["summary"], "evidence": reason["evidence"]} if reason else None,
                          fold_blocked=blocked, **({"source": _s(r["source"], 80)} if r.get("source") else {}))
    reopened = split_ledger(graph)
    graph["gates"] = gates_meta(graph, today, th, have_taste, reopened, taste_name)
    from tastecal.judge.quality import combine
    combine(graph)
    return graph


# ----------------------------------------------------------------------------- live pipeline
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", re.I)


def arxiv_id(node: dict, item=None) -> str:
    if item is not None and (item.ids or {}).get("arxiv"):
        return item.ids["arxiv"]
    m = ARXIV_RE.search(node.get("url") or "")
    return m.group(1) if m else ""


def card_text(node: dict) -> str:
    c = node.get("card") or {}
    return (f"Starts from: {c.get('inherits', '')}\nMove: {c.get('move', '')}\nInsight: {c.get('insight', '')}\n"
            f"Leaves: {'; '.join(c.get('leaves') or [])}")


def read_taste(spec: str) -> str:
    """The profile text for a path or a preset name (see taste/profiles.py)."""
    from tastecal.taste.profiles import load_profile
    return load_profile(spec)[1]


class Gatekeeper:
    """Reads each work, asks the gate questions, scores taste, and merges the result into the graph."""

    def __init__(self, cfg, llm, http=None, today: Optional[str] = None, th: Optional[GateThresholds] = None,
                 profile: str = "", profile_name: str = ""):
        self.cfg, self.llm, self.http = cfg, llm, http
        self.today = today or dt.date.today().strftime("%Y-%m")
        self.th = th or GateThresholds()
        self.profile = profile
        self.profile_name = profile_name

    def fulltext(self, node: dict, item=None) -> Tuple[str, str, str]:
        """(text, basis, source): a local file, arXiv, an open-access copy, else the abstract or the card."""
        from tastecal.sources.fulltext import find_fulltext
        return find_fulltext(node, item, self.http, getattr(self.cfg, "papers_dir", "papers"),
                             getattr(self.cfg, "openalex_mailto", ""), FULL_TEXT_MIN)

    def gate(self, node: dict, item=None) -> Optional[dict]:
        got = self.fulltext(node, item)          # (text, basis[, source]); older overrides return two values
        text, basis, source = got[0], got[1], (got[2] if len(got) > 2 else "")
        r = self.llm.json(P.GATES_SYSTEM, P.gates_audit(node.get("title", ""), node.get("date", ""),
                                                        card_text(node), text, basis))
        if not isinstance(r, dict):
            return None
        return dict(r, basis=basis, source=source, verified=verify(r, text if basis != "card" else ""))

    TASTE_BATCH = 6

    def taste(self, nodes: List[dict], raw: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
        if not self.profile:
            return {}
        raw = raw or {}
        out: Dict[str, dict] = {}
        for i in range(0, len(nodes), self.TASTE_BATCH):
            batch = nodes[i:i + self.TASTE_BATCH]
            rows = [dict(id=n["id"], short=n.get("short", n["id"]), evidence=evidence_line(raw.get(n["id"])),
                         **{k: (n.get("card") or {}).get(k, "") for k in ("inherits", "move", "insight")})
                    for n in batch]
            res = self.llm.json(P.GATES_SYSTEM, P.gates_taste(self.profile, rows))
            if isinstance(res, dict):
                for n in batch:
                    t = clean_taste(res.get(n["id"]))
                    if t:
                        out[n["id"]] = t
        return out

    def targets(self, graph: dict) -> List[dict]:
        from tastecal.judge.quality import pick_for_reading
        seed = (graph.get("meta") or {}).get("seed")
        papers = [n for n in graph.get("nodes", []) if n.get("kind", "paper") == "paper"]
        papers.sort(key=lambda n: (n["id"] != seed and n.get("role") != "seed", n.get("date") or ""))
        return pick_for_reading(papers, seed, graph.get("edges", []), self.cfg.gates_max)

    def read(self, graph: dict, items: Optional[Dict[str, object]] = None) -> Dict[str, dict]:
        """One careful read per paper. The audit reuses these readings instead of reading the papers again."""
        items = items or {}
        raw: Dict[str, dict] = {}
        for n in self.targets(graph):
            log.info("reading %s", n.get("short") or n["id"])
            try:
                r = self.gate(n, items.get(n["id"]))
            except Exception as e:
                log.warning("reading failed for %s: %s", n.get("short") or n["id"], e)
                continue
            if r:
                raw[n["id"]] = r
        return raw

    def run(self, graph: dict, items: Optional[Dict[str, object]] = None, raw: Optional[Dict[str, dict]] = None) -> dict:
        if raw is None:
            raw = self.read(graph, items)
        apply_gates(graph, raw, self.taste(self.targets(graph), raw), self.today, self.th, self.profile_name)
        if self.profile:
            graph["gates"]["taste_profile"] = self.profile
        nxt = rate_next(graph, self.profile)
        if nxt:
            graph["gates"]["rate_next"] = nxt
        return graph


def evidence_line(r: Optional[dict]) -> str:
    """What the gate read found in a paper, in one compact line for the taste scorer. "" without a read."""
    g = clean_gates(r) if isinstance(r, dict) else None
    if not g:
        return ""
    parts = []
    if _real(g["delivered"]):
        parts.append(f"shows: {g['delivered'].rstrip('.')}")
    parts.append(f"claim {g['delivery']}" + (f" ({g['partial_kind']})" if g.get("partial_kind") else ""))
    parts.append(f"reason: {REASON_TXT[g['reason_type']]}" + ("" if g["reason_type"] != "mechanism" or bounded(g)
                                                             else ", never says when it would not help"))
    parts.append(f"gains: {ROBUST_TXT[g['robustness']]}")
    shown = [_lever_line(lv) for lv in g["levers"] if lv.get("status") == "present"][:3]
    if shown:
        parts.append("levers shown: " + "; ".join(shown))
    ck = g.get("checks") or {}
    if ck.get("fair_baselines") == "no":
        parts.append("baselines not treated equally")
    if ck.get("novelty_ablation") == "no":
        parts.append("no ablation of the new idea alone")
    if ck.get("numbers") == "mismatch" and ck.get("numbers_severity") == "headline":
        parts.append("headline number not in its tables")
    notes = (g.get("fairness_notes") or [])[:2]
    if notes:
        parts.append("reviewer notes: " + " / ".join(notes))
    return _s(". ".join(parts), 700)


def rate_next(graph: dict, profile: str, k: int = 5, enough: int = 8) -> List[str]:
    """Works on the map worth rating next, so the taste check and your scale have something to fit: spread over
    the blind contribution score (or the taste score), skipping papers already rated. [] once enough are rated."""
    from tastecal.taste.profiles import rated_papers
    from tastecal.core.model import title_similarity
    rated = rated_papers(profile or "")
    if len(rated) >= enough:
        return []

    def score(n):
        a = ((n.get("assessment") or {}).get("contribution") or {}).get("score")
        return a if isinstance(a, (int, float)) else (n.get("gates") or {}).get("attractiveness")
    pool = [n for n in graph.get("nodes", []) if n.get("kind", "paper") == "paper" and isinstance(score(n), (int, float))
            and not any(title_similarity(n.get("title", ""), r["ref"]) > 0.85 for r in rated)]
    pool.sort(key=score)
    want = min(k, len(pool), enough - len(rated))
    if want <= 0:
        return []
    if want == 1:
        return [pool[len(pool) // 2]["id"]]
    return list(dict.fromkeys(pool[round(i * (len(pool) - 1) / (want - 1))]["id"] for i in range(want)))


def verify(r: dict, text: str) -> dict:
    """Check the reader's quotes against the text it read. Only keys that could be checked are set."""
    out = {}
    if r.get("fails_when_stated") is True:
        found = quote_in_text(str(r.get("fails_when") or ""), text)
        if found is not None:
            out["fails_when"] = found
    elif r.get("fails_when_stated") is False:
        out["fails_when"] = False
    return out


def load_raw(path: str) -> Dict[str, dict]:
    """Gate answers prepared elsewhere (for example by a reader or an assistant in a chat), keyed by node id."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = {r.get("id"): r for r in data if isinstance(r, dict) and r.get("id")}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def summary(graph: dict) -> Iterable[str]:
    m = graph.get("gates") or {}
    c = m.get("counts") or {}
    yield (f"gates: {m.get('gated', 0)} works · {c.get('solid', 0)} solid · {c.get('treasure', 0)} treasure · "
           f"{c.get('unattributed', 0)} gain not attributed · "
           f"{c.get('incremental', 0)} incremental · {c.get('not-delivered', 0)} not delivered · "
           f"{m.get('folded', 0)} folded · {m.get('reopened', 0)} problems reopened")
