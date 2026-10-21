"""Gates: read each work from its own text and write down what was found.

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

The gates give no taste score. The reading notes they write are what the taste calibration (`fit`)
measures each paper on, against the reader's own rated papers; the gate prompt never sees a taste
profile. The run keeps the profile in graph['gates']['taste_profile'] only so that `fit` can find it.

The report does not show the notes; nothing is folded and every work stays on the map. A label (the
verdict below) is still stored in graph.json, from fixed rules, for older readers of the file and to
mark works read from an abstract or a card only ("unread"):

  not-delivered  the headline claim is not realised
  treasure       a reason, not yet robust
  uncertain      insufficient reading or unresolved evidence
  solid          delivered, with a reason or robustness, and the gain is not confounded
  unattributed   delivered, but the gain may come from something other than the idea
  incremental    delivered, but neither a reason nor robustness

A mechanism only counts as a reason when the paper itself says when the method would not help
(fails_when_stated), and the sentence it quotes for that is found in the text. Levers only count when
the reader marked them "present" and quoted where they show.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from tastecal.prompts import gates as P
from tastecal.judge.audit import months_between

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
VERDICTS = ("solid", "treasure", "unattributed", "incremental", "not-delivered", "unread", "uncertain")
FOLDED = ("incremental", "not-delivered")
BASES = ("full text", "abstract", "card")
LABELS = {"solid": "Solid", "treasure": "Reasoned, not yet verified", "unattributed": "Gain not attributed",
          "incremental": "Incremental", "not-delivered": "Claim not delivered", "unread": "Not read in full",
          "uncertain": "Insufficient evidence"}
UNREAD_TXT = {
    "en": "Only the {what} could be read, so no verdict is given: a missing reason or test in a summary says nothing "
          "about the paper. Put the paper's PDF in the papers folder and run `assess` and `gates` again.",
    "zh": "只读到了{what}，所以不下结论：摘要里没写理由或实验，不代表论文里没有。把这篇的 PDF 放进 papers 文件夹，再运行 assess 和 gates。",
}
WHAT = {"en": {"abstract": "abstract", "card": "summary card"}, "zh": {"abstract": "摘要", "card": "摘要卡片"}}
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
    "idea, the work is marked 'gain not attributed' instead of solid. Adoption does not override evidence defects. "
    "Works that fail check 0, or pass it with neither a reason nor robust evidence, are folded.")
CAVEATS = [
    "Verdicts are a reading aid, not a ruling. Open the drawer to see the evidence behind each one.",
    "Every folded work shows why: a summary and the evidence from its text. A verdict without evidence never folds a work.",
    "Only works read from the full text are folded; works read from an abstract or a card stay on the map.",
    "The field-reaction check only sees later works that made it onto this map, plus the audit's citer sample when present.",
    "A model judged the text. It can miss an ablation buried in an appendix, or take a claim too literally.",
]


@dataclass
class GateThresholds:
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
            if _s(lv.get("quote")):
                row["quote"] = _s(lv.get("quote"), 240)
            if isinstance(lv.get("quote_found"), bool):
                row["quote_found"] = lv["quote_found"]
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
    if isinstance(r.get("coverage"), dict):
        out["coverage"] = dict(r["coverage"])
    checks = clean_checks(r.get("checks"))
    if checks:
        if incomplete_reading(out) and checks.get("novelty_ablation") == "no":
            checks["novelty_ablation"] = "unknown"
        out["checks"] = checks
    ef = r.get("eval_fit")
    if isinstance(ef, dict) and ef.get("can_show") in EVAL_FIT:
        out["eval_fit"] = {"property": _s(ef.get("property"), 300), "property_quote": _s(ef.get("property_quote"), 300),
                           "shown_by": _s(ef.get("shown_by"), 300), "can_show": ef["can_show"],
                           "fit_why": _s(ef.get("fit_why"), 400),
                           "kind": ef.get("kind") if ef.get("kind") in WORK_KINDS else "other",
                           "threat_model": _s(ef.get("threat_model"), 300)}
    claims = [{"claim": _s(c.get("claim"), 300), "support": c.get("support") if c.get("support") in SUPPORT else "untested",
               "evidence": _s(c.get("evidence"), 300)} for c in r.get("claims") or [] if isinstance(c, dict) and c.get("claim")]
    if claims:
        out["claims"] = claims[:4]
    notes = [_s(x, 300) for x in r.get("fairness_notes") or [] if isinstance(x, str) and x.strip()]
    if notes:
        out["fairness_notes"] = notes[:5]
    return out


SUPPORT = ("supported", "partial", "unsupported", "untested")
EVAL_FIT = ("yes", "partly", "no")
WORK_KINDS = ("method", "testing", "benchmark", "analysis", "other")
CHECK_VALUES = {"numbers": ("match", "mismatch", "not checked"), "fair_baselines": ("yes", "no", "unclear"),
                "novelty_ablation": ("yes", "no", "unknown", "not checked"), "code": ("released", "promised", "none", "unknown"),
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
           "eval": "The evaluation cannot, in principle, show the claimed property",
           "why": "The gain may come from something other than the idea."},
    "zh": {"unfair": "基线没有得到同等对待，也没有只去掉新想法的消融实验",
           "unisolated": "新组件自身的作用没有被单独验证",
           "numbers": "核心数字在论文自己的表格里找不到依据",
           "eval": "评估在原理上测不出它声称的性质",
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
    missing_ablation = ck.get("novelty_ablation") == "no" and not incomplete_reading(g)
    for lv in g.get("levers") or []:
        if (lv.get("status") == "present" and lv.get("lever") in SERIOUS_LEVERS and _real(lv.get("note"))
                and lv.get("quote_found") is not False):        # a lever whose quote is not in the text does not count
            name = LEVER_ZH.get(lv["lever"], "") if lang == "zh" else ""
            line = f"{name}{sep}{lv['note']}" if name else _lever_line(lv)
            out.append(line + (f" ({lv['where']})" if lv.get("where") else ""))
    if ck.get("fair_baselines") == "no" and missing_ablation:
        out.append(T["unfair"] + (f"{sep}{ck['baselines_note']}" if _real(ck.get("baselines_note")) else "."))
    if g.get("delivery") == "partial" and g.get("partial_kind") == "unisolated" and missing_ablation:
        out.append(T["unisolated"] + (f"{sep}{g['delivery_evidence']}" if _real(g.get("delivery_evidence")) else "."))
    if ck.get("numbers") == "mismatch" and ck.get("numbers_severity") == "headline" and _real(ck.get("numbers_note")):
        out.append(f"{T['numbers']}{sep}{ck['numbers_note']}")
    ef = g.get("eval_fit") or {}
    # A missing or unchecked quotation is not verified evidence of the claimed property.
    if ef.get("can_show") == "no" and _real(ef.get("fit_why")) and (g.get("verified") or {}).get("eval_quote") is True:
        out.insert(0, f"{T['eval']}{sep}{ef['fit_why']}")
    return out


def incomplete_reading(g: dict) -> bool:
    """Was part of the main text (not references, related work or appendix) left out of the reading? Then an absence
    ("no ablation", "not delivered", "one setting only") cannot be established. A long appendix that did not fit is
    not enough: the reader is told what was omitted and answers "unknown" where the appendix may hold the answer."""
    cov = g.get("coverage") or {}
    fraction = cov.get("main_coverage")
    return (isinstance(fraction, (int, float)) and fraction < 0.97) or "middle of the main text" in (cov.get("omitted") or [])


def verdict(g: dict, react: dict, attract: Optional[float], th: GateThresholds) -> str:
    """Fixed rules over the gate answers. Taste and adoption never change it (adoption only keeps a work on the map,
    see apply_gates). An evaluation that cannot show the claim counts as a confounder only when the claimed property
    was quoted from the text; an unchecked or "partly" answer is shown to the reader but decides nothing."""
    if g["delivery"] == "not":
        return "uncertain" if incomplete_reading(g) else "not-delivered"
    reasoned = has_reason(g)
    robust = g["robustness"] == "repeats"
    if not (reasoned or robust):
        # Folding needs a positive finding (one setting only, read in full); "unclear" reserves judgement.
        return "uncertain" if incomplete_reading(g) or g["robustness"] == "unclear" else "incremental"
    if confounders(g):
        return "unattributed"
    if reasoned and not robust:
        return "treasure"
    return "solid"


REASON_TXT = {"proof": "a proof", "mechanism": "a mechanism", "analogy": "an analogy only", "none": "no reason"}
ROBUST_TXT = {"repeats": "evidence that repeats", "single": "evidence from one setting", "unclear": "unclear evidence"}
REASON_ZH = {"proof": "给出了证明", "mechanism": "给出了机制解释", "analogy": "只给出了类比", "none": "没有给出理由"}
ROBUST_ZH = {"repeats": "证据在多个设定下重复出现", "single": "证据只来自单一设定", "unclear": "证据不清楚"}
LEVER_TXT = {"cost-assumption": "a chosen cost or price ratio", "metric-trained": "a component trained on the metric",
             "unequal-tuning": "tuning the baselines did not get", "mismatched-setup": "a mismatched setup",
             "small-or-saturated-benchmark": "a small or saturated benchmark",
             "missing-novelty-ablation": "no ablation of the new idea", "other": "another lever"}


def why_line(v: str, g: dict, react: dict, lang: str = "en") -> str:
    if v == "uncertain":
        return ("阅读不完整，或关键证据尚未核实；保留判断，不折叠。" if lang == "zh" else
                "The reading is incomplete or key evidence remains unresolved; judgement is reserved and the work stays on the map.")
    if lang == "zh":
        return _why_zh(v, g, react)
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
        return g["robustness_note"] or "Gains repeat across settings."
    lever = (g["levers"] or [{}])[0]
    tail = (f" Main lever: {LEVER_TXT.get(lever.get('lever'), 'another lever')}"
            + (f" ({lever['note']})" if lever.get("note") else "") + ".") if lever else ""
    return f"Delivered, with {REASON_TXT[g['reason_type']]} and {ROBUST_TXT[g['robustness']]}.{tail}"


def _why_zh(v: str, g: dict, react: dict) -> str:
    if v == "not-delivered":
        return f"主张：{g['claimed'] or '见摘要'}。实际兑现：{g['delivered'] or '不清楚'}。"
    if v == "treasure":
        return (f"理由：{(g['reason'] or REASON_ZH[g['reason_type']]).rstrip('。. ')}。尚未在单一设定之外得到验证。"
                + (f"下一步可检查：{g['check_next']}" if g["check_next"] else ""))
    if v == "unattributed":
        why = confounders(g, "zh")
        return CONF_TXT["zh"]["why"] + (why[0].rstrip(".。") + "。" if why else "")
    if v == "solid":
        if has_reason(g) and g["reason"]:
            return f"理由：{g['reason']}"
        return g["robustness_note"] or "增益在多个设定下重复出现。"
    lever = (g["levers"] or [{}])[0]
    tail = (f"主要杠杆：{LEVER_ZH.get(lever.get('lever'), '其他杠杆')}"
            + (f"（{lever['note']}）" if lever.get("note") else "") + "。") if lever else ""
    return f"已兑现，{REASON_ZH[g['reason_type']]}，{ROBUST_ZH[g['robustness']]}。{tail}"


BOILERPLATE = {"", "none", "none given", "n/a", "na", "unclear", "unknown", "not stated", "not given", "-"}


def _real(x) -> bool:
    return _s(x).lower().strip(" .") not in BOILERPLATE


def _lever_line(lv: dict, lang: str = "en") -> str:
    if lang == "zh":
        name = LEVER_ZH.get(lv.get("lever"), "其他杠杆")
        return f"{name}：{lv['note']}" if lv.get("note") else name
    name = LEVER_TXT.get(lv.get("lever"), "another lever")
    name = name[0].upper() + name[1:]
    return f"{name}: {lv['note']}" if lv.get("note") else name


def fold_reason(v: str, g: dict, lang: str = "en") -> Optional[dict]:
    """Why a work does not earn a station: a summary and the evidence for it, taken from the gate answer.
    None for verdicts that keep a station."""
    levers = [_lever_line(lv, lang) for lv in g["levers"]]
    zh = lang == "zh"
    if v == "not-delivered" and zh:
        summary = "实验没有展示标题和摘要所主张的内容。"
        if _real(g["claimed"]):
            summary += f"主张：{g['claimed'].rstrip('.。')}。"
        if _real(g["delivered"]):
            summary += f"实际展示：{g['delivered'].rstrip('.。')}。"
        evidence = [g["delivery_evidence"]] + levers
        needs = _real(g["claimed"]) and _real(g["delivered"])
    elif v == "incremental" and zh:
        why = "没有说明为什么有效" if g["reason_type"] == "none" else f"关于为什么有效{REASON_ZH[g['reason_type']]}"
        summary = f"兑现了主张，但{why}，{ROBUST_ZH[g['robustness']]}。"
        evidence = [g["robustness_note"]]
        if g["reason_type"] == "analogy" and _real(g["reason"]):
            evidence.append(f"唯一的理由是一个类比：{g['reason'].rstrip('.。')}。")
        evidence += levers
        needs = True
    elif v == "not-delivered":
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


def restore_ledger(graph: dict) -> int:
    """Undo split_ledger on graphs gated before: a verdict no longer moves solutions to "claimed". Returns 0."""
    for p in graph.get("problems", []):
        every = list(dict.fromkeys(list(p.get("addressed_by") or []) + list(p.get("claimed_by") or [])))
        p["addressed_by"], p["claimed_by"] = every, []
        p["status"] = "addressed" if every else "open"
    return 0


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


def gates_meta(graph: dict, today: str, th: GateThresholds, reopened: int, taste_name: str = "") -> dict:
    gated = [n for n in graph.get("nodes", []) if n.get("gates")]
    counts = {v: 0 for v in VERDICTS}
    for n in gated:
        counts[n["gates"]["verdict"]] += 1
    caveats = list(CAVEATS)
    skew = None
    read = [n for n in gated if n["gates"]["verdict"] != "unread"]
    if counts.get("unread"):
        caveats.insert(0, f"{counts['unread']} of {len(gated)} works could only be read from an abstract or a summary, "
                          "so they get no verdict. Put their PDFs in the papers folder and run `gates` again.")
    if len(read) >= SKEW_MIN:
        top = max((v for v in counts if v != "unread"), key=lambda v: counts[v])
        share = counts[top] / len(read)
        if share > SKEW_SHARE:
            skew = {"verdict": top, "share": round(share, 3)}
            caveats.insert(0, f"{counts[top]} of {len(read)} works read in full got the same verdict ({LABELS[top]}). The checks "
                              "may not be telling these works apart; read the evidence rather than the label.")
            log.warning("gates: %d of %d works are '%s'; the verdicts may not discriminate", counts[top], len(read), top)
    return {"today": today, "thresholds": asdict(th), "gated": len(gated),
            "folded": sum(1 for n in gated if n["gates"]["fold"]), "reopened": reopened,
            "counts": counts, "labels": LABELS, "method": METHOD_NOTE, "caveats": caveats,
            **({"skew": skew} if skew else {}), **({"taste_name": taste_name} if taste_name else {})}


def apply_gates(graph: dict, raw: Dict[str, dict], today: Optional[str] = None, th: Optional[GateThresholds] = None,
                taste_name: str = "") -> dict:
    """Merge gate answers into the graph: node['gates'], the problem ledger, graph['gates'].

    raw:   {node id: gates_audit answer, plus "basis" ("full text" | "abstract" | "card")}.
    Nodes missing from `raw` keep any gates they already had; a node read again loses any taste score an older
    run gave it."""
    th = th or GateThresholds()
    today = today or dt.date.today().strftime("%Y-%m")
    seed = (graph.get("meta") or {}).get("seed")
    lang = _lang(graph)
    for n in graph.get("nodes", []):
        r = raw.get(n["id"])
        if r is None:
            continue
        g = clean_gates(r)
        if g is None:
            log.warning("gates: unusable answer for %s", n["id"])
            continue
        basis = r.get("basis") if r.get("basis") in BASES else "card"
        months = months_between(n.get("date", ""), today)
        react = reaction(graph, n["id"], months, th)
        v = verdict(g, react, None, th)
        if basis != "full text":
            # A verdict needs the paper's own text. From an abstract or a card, "no reason given" or "one setting"
            # only means the summary did not say, so no verdict is given (and nothing is folded).
            v = "unread"
        # A one-line summary of what was found (the old fold summary, kept as text). Nothing is folded: hiding
        # works on the strength of a label took whole parts of the field off the map.
        reason = fold_reason(v, g, lang)
        if isinstance(r.get("coverage"), dict):
            g["coverage"] = r["coverage"]
        n["gates"] = dict(g, basis=basis, months=months, reaction=react, verdict=v, label=LABELS[v],
                          why=(UNREAD_TXT[lang].format(what=WHAT[lang].get(basis, basis)) if v == "unread"
                               else reason["summary"] if reason else why_line(v, g, react, lang)),
                          **({"confounders": confounders(g, lang)} if v == "unattributed" else {}),
                          fold=False, **({"source": _s(r["source"], 80)} if r.get("source") else {}))
    reopened = restore_ledger(graph)
    previous = graph.get("gates") or {}
    # The profile survives partial reruns (fit reads it); an older run's taste check or reading list does not.
    retained = {k: previous[k] for k in ("taste_profile", "taste_name", "view") if k in previous}
    graph["gates"] = dict(retained, **gates_meta(graph, today, th, reopened, taste_name))
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


class Gatekeeper:
    """Reads each work, asks the gate questions, and merges the result into the graph. `profile` is only kept in the
    graph, for `fit`: nothing here scores taste."""

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
        from tastecal.sources.fulltext import coverage_note, select_for_reading
        got = self.fulltext(node, item)          # (text, basis[, source]); older overrides return two values
        text, basis, source = got[0], got[1], (got[2] if len(got) > 2 else "")
        cov = None
        shown = text
        if basis == "full text":
            # Drop references, then related work and the middle if needed, so the experiments are always read.
            shown, cov = select_for_reading(text)
        r = self.llm.json(P.GATES_SYSTEM, P.gates_audit(node.get("title", ""), node.get("date", ""),
                                                        card_text(node), shown, basis, coverage_note(cov)))
        if not isinstance(r, dict):
            return None
        checked = shown if basis != "card" else ""
        for lv in r.get("levers") or []:
            if isinstance(lv, dict) and str(lv.get("status") or "").strip().lower() == "present":
                found = quote_in_text(str(lv.get("quote") or ""), checked, min_words=4)
                if found is not None:
                    lv["quote_found"] = found
        extra = {"coverage": cov} if cov else {}
        return dict(r, basis=basis, source=source, verified=verify(r, shown if basis != "card" else ""), **extra)

    def targets(self, graph: dict) -> List[dict]:
        from tastecal.judge.quality import pick_for_reading
        seed = (graph.get("meta") or {}).get("seed")
        # Borrowed tools from other fields are not judged here: the map is about this field's works.
        papers = [n for n in graph.get("nodes", []) if n.get("kind", "paper") == "paper" and not n.get("borrowed")]
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
        apply_gates(graph, raw, self.today, self.th, self.profile_name)
        graph["gates"]["taste_profile"] = self.profile
        graph["gates"]["taste_name"] = self.profile_name
        return graph


def evidence_line(r: Optional[dict]) -> str:
    """What the gate read found in a paper, in one compact line (the audit's evidence pack). "" without a read."""
    g = clean_gates(r) if isinstance(r, dict) else None
    if not g:
        return ""
    parts = []
    ef = g.get("eval_fit") or {}
    if ef:
        parts.append(f"evaluation fit: {ef['can_show']}; property: {ef['property']}; measured by: {ef['shown_by']}; "
                     f"why: {ef['fit_why']}; property quote verified: {(g.get('verified') or {}).get('eval_quote', 'unchecked')}")
        if ef.get("threat_model"):
            parts.append("threat model: " + ef["threat_model"])
    if g.get("coverage"):
        from tastecal.sources.fulltext import coverage_note
        parts.append(coverage_note(g["coverage"]))
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
    return _s(". ".join(parts), 3000)


def verify(r: dict, text: str) -> dict:
    """Check the reader's quotes against the text it read. Only keys that could be checked are set."""
    out = {}
    if r.get("fails_when_stated") is True:
        found = quote_in_text(str(r.get("fails_when") or ""), text)
        if found is not None:
            out["fails_when"] = found
    elif r.get("fails_when_stated") is False:
        out["fails_when"] = False
    ef = r.get("eval_fit")
    if isinstance(ef, dict):
        found = quote_in_text(str(ef.get("property_quote") or ""), text, min_words=3)
        if found is not None:
            out["eval_quote"] = found
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
    # Reading notes only: no verdict counts, since the report shows no verdicts.
    gated = m.get("gated", 0)
    unread = c.get("unread", 0)
    yield f"gates: {gated} works read · {gated - unread} from full text · {unread} not read in full"
