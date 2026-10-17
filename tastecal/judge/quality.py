"""Where the gates and the audit disagree about a work.

The gates ask whether a paper's own text holds up. The audit asks whether the notice it got matches a
blind score of its contribution. They usually agree; when they do not, the report says so instead of
showing two verdicts side by side. Called after either step, so it is always current.
"""
from __future__ import annotations

from collections import Counter
from typing import List

from typing import List

KEPT = ("solid", "treasure")
FOLDED = ("incremental", "not-delivered")

NOTES = {
    ("kept", "skip"): {"en": "Its own text holds up, but the blind score found little that is new.",
                       "zh": "原文自身站得住，但盲评认为新东西不多。"},
    ("kept", "overhyped"): {"en": "Its own text holds up, but it gets more notice than its contribution.",
                            "zh": "原文自身站得住，但受到的关注多于它的贡献。"},
    ("folded", "hidden-gem"): {"en": "The blind score found a real contribution, but its own text does not show that it holds up.",
                               "zh": "盲评认为贡献实在，但原文没有证明它站得住。"},
    ("folded", "fair"): {"en": "Widely noticed and fairly scored, yet its own text does not show that it holds up.",
                         "zh": "关注度和盲评都正常，但原文没有证明它站得住。"},
}


def combine(graph: dict) -> List[dict]:
    """Set graph['quality'] = {"disagreements": [...]} and return the list."""
    lang = "zh" if str((graph.get("meta") or {}).get("language", "")).lower().startswith("zh") else "en"
    out = []
    for n in graph.get("nodes") or []:
        gt, a = n.get("gates") or {}, n.get("assessment") or {}
        v, f = gt.get("verdict"), a.get("flag")
        if not v or not f:
            continue
        side = "kept" if v in KEPT else "folded" if v in FOLDED else ""
        key = (side, f)
        if key == ("folded", "fair") and a.get("quadrant") != "classic":
            continue                      # only a well-known work that fails its own text is worth a flag here
        if key in NOTES:
            out.append({"id": n["id"], "gate": v, "audit": f, "note": NOTES[key][lang]})
    if graph.get("gates") or graph.get("audit"):
        graph["quality"] = {"disagreements": out}
    return out


def pick_for_reading(papers: List[dict], seed: str, edges: List[dict], cap: int) -> List[dict]:
    """The papers to read or audit. All of them when there is no limit (cap 0) or the limit covers them, in the given
    order. Otherwise the seed and the most connected works, newer first on ties, so a limit never drops the
    recent half of a large map; they are returned in the given order."""
    if not cap or cap >= len(papers):
        return list(papers)
    deg = Counter()
    for e in edges or []:
        deg[e.get("source")] += 1
        deg[e.get("target")] += 1
    rank = sorted(papers, key=lambda n: (n.get("id") != seed and n.get("role") != "seed", -deg[n.get("id")],
                                         "".join(chr(0x10FFFF - ord(c)) for c in str(n.get("date") or ""))))
    keep = {n.get("id") for n in rank[:cap]}
    return [n for n in papers if n.get("id") in keep]


def note_coverage(graph: dict, gates_cap: int = 0, assess_cap: int = 0, only=("gates", "audit")) -> None:
    """Say in the report which papers on the map were not read or not audited, and why."""
    papers = [n for n in graph.get("nodes", []) if n.get("kind", "paper") == "paper"]
    for key, field, cap, verb, flag in (("gates", "gates", gates_cap, "read through the gates", "--gates-max 0"),
                                        ("audit", "assessment", assess_cap, "audited", "--assess-max 0")):
        sec = graph.get(key)
        if key not in only or not isinstance(sec, dict):
            continue
        missing = [n for n in papers if not n.get(field)]
        sec["not_covered"] = [n["id"] for n in missing]
        if not missing:
            continue
        capped = bool(cap and len(papers) > cap)
        if str((graph.get("meta") or {}).get("language", "")).lower().startswith("zh"):
            names = "、".join(n.get("short") or n["id"] for n in missing[:12]) + ("等" if len(missing) > 12 else "")
            what = {"gates": "没有经过原文检查", "audit": "没有审计"}[key]
            why = (f"上限是 {cap} 篇；用 {flag} 可以覆盖全部" if capped else "拿不到原文或证据")
            note = f"图上 {len(papers)} 篇论文中有 {len(missing)} 篇{what}（{why}）：{names}。"
        else:
            names = ", ".join(n.get("short") or n["id"] for n in missing[:12]) + (" and others" if len(missing) > 12 else "")
            why = (f"the limit was {cap}; run with {flag} to include every paper" if capped
                   else "their text or evidence could not be gathered")
            note = f"{len(missing)} of {len(papers)} papers on the map were not {verb} ({why}): {names}."
        old = (" papers on the map were not ", "篇论文中有")
        sec["caveats"] = [c for c in sec.get("caveats") or [] if not any(o in c for o in old)] + [note]

