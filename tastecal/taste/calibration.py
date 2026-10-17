"""Calibration to your ratings: your scale (the blind score fit to your ratings) and the taste check.

Taste check: how well your taste profile predicts your own ratings.

Each paper you rated is scored by the same taste scorer the reading list uses, but with its own rating taken out of
the profile (papers are split into up to four groups, and each group is scored by a profile without that group).
The check reports how many pairs of your papers the scores put in your order, and how far the scores are from
your ratings on average. It needs at least three rated papers, and costs a card and a lookup per paper plus one
taste call per group; everything is cached.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from tastecal.prompts import lineage as prompts
from tastecal.prompts import gates as PG
from tastecal.taste.profiles import drop_rated, rated_papers

log = logging.getLogger("tastecal.calibration")

MAX_PAPERS = 20
GROUPS = 4


def pair_agreement(pairs: List[tuple]) -> tuple:
    """(agreeing pairs, pairs counted) for [(predicted, yours)]: pairs you rated differently, in the same order;
    a tie in the prediction counts half."""
    agree = total = 0.0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            du = pairs[i][1] - pairs[j][1]
            if abs(du) < 1e-9:
                continue
            total += 1
            dp = pairs[i][0] - pairs[j][0]
            agree += 1.0 if dp * du > 0 else 0.5 if abs(dp) < 1e-9 else 0.0
    return agree, int(total)


def your_scale(pairs: List[tuple]) -> dict:
    """Fit the blind contribution score to your own ratings. pairs: [(blind score, your score)].
    Agreement counts the pairs of rated papers that both put in the same order (a tie in the blind score counts
    half). The fit is a straight line, used only when it rises (higher blind score, higher rating of yours) and
    rests on at least 3 papers; otherwise nothing is put on your scale."""
    n = len(pairs)
    agree, total = pair_agreement(pairs)
    out = {"n": n, "pairs": total, "agree": agree, "usable": False}
    if n >= 3:
        mc = sum(c for c, _ in pairs) / n
        mu = sum(u for _, u in pairs) / n
        var = sum((c - mc) ** 2 for c, _ in pairs)
        cov = sum((c - mc) * (u - mu) for c, u in pairs)
        if var > 1e-6 and cov > 0:
            b = cov / var
            out.update(slope=round(b, 3), intercept=round(mu - b * mc, 3), usable=True)
    return out


def on_your_scale(blind: float, fit: dict) -> Optional[float]:
    if not fit.get("usable"):
        return None
    return round(min(1.0, max(0.0, fit["intercept"] + fit["slope"] * blind)), 2)


def taste_check(profile_text: str, source, llm, max_papers: int = MAX_PAPERS, groups: int = GROUPS,
                evidence: Optional[dict] = None) -> Optional[dict]:
    """None when there is no profile or nothing rated; otherwise the check (see the module note).
    `evidence`: {normalised title: what the careful read found}, from the audit's calibration, so the taste scorer
    sees the same details for your rated papers as for the map's works."""
    from tastecal.core.model import norm_title
    evidence = evidence or {}
    papers = rated_papers(profile_text)[:max_papers]
    if not papers:
        return None
    found = []
    for p in papers:
        try:
            found.append((p, source.resolve(p["ref"])))
        except Exception as e:  # not found: listed, not used
            log.info("rated paper not found: %s (%s)", p["ref"], e)
    rows = {}
    for i in range(0, len(found), 6):
        batch = [it for _, it in found[i:i + 6]]
        got = llm.json(prompts.SYSTEM, prompts.cards(batch, {}))
        for r in got if isinstance(got, list) else []:
            if isinstance(r, dict) and r.get("id"):
                rows[r["id"]] = r
    items = []
    for k, (p, it) in enumerate(found):
        c = rows.get(it.id) or {}
        items.append({"p": p, "it": it, "row": {"id": f"r{k + 1}", "short": c.get("short") or it.title[:40],
                                                "inherits": c.get("inherits", ""), "move": c.get("move", ""),
                                                "insight": c.get("insight", ""),
                                                "evidence": evidence.get(norm_title(it.title), "")}})
    out = {"n": 0, "pairs": 0, "agree": 0.0, "gap": None, "usable": False, "papers": []}
    if len(items) < 3:
        out["papers"] = [{"ref": x["p"]["ref"], "title": x["it"].title, "yours": x["p"]["score"]} for x in items]
        out["not_found"] = len(papers) - len(items)
        return out
    g = max(2, min(groups, len(items)))
    for k in range(g):
        part = [x for i, x in enumerate(items) if i % g == k]
        res = llm.json(PG.GATES_SYSTEM, PG.gates_taste(drop_rated(profile_text, [x["p"]["ref"] for x in part]),
                                                        [x["row"] for x in part]))
        for x in part:
            r = (res or {}).get(x["row"]["id"]) if isinstance(res, dict) else None
            try:
                x["pred"] = max(0.0, min(1.0, float((r or {}).get("score"))))
                x["why"] = str((r or {}).get("why") or "")[:200]
            except (TypeError, ValueError):
                x["pred"] = None
    scored = [x for x in items if x.get("pred") is not None]
    pairs = [(x["pred"], x["p"]["score"]) for x in scored]
    agree, total = pair_agreement(pairs)
    out.update(n=len(scored), pairs=total, agree=agree, usable=len(scored) >= 3 and total > 0,
               gap=round(sum(abs(a - b) for a, b in pairs) / len(pairs), 2) if pairs else None,
               not_found=len(papers) - len(items),
               papers=[{"ref": x["p"]["ref"], "title": x["it"].title, "url": x["it"].url, "yours": x["p"]["score"],
                        "predicted": round(x["pred"], 2) if x.get("pred") is not None else None, "why": x.get("why", "")}
                       for x in items])
    return out
