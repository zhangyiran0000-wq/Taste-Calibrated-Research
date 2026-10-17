"""Does the explanation predict? A backtest of the driving forces that cannot see the answer.

The earlier check asked the model to predict from forces it had built from the WHOLE map, then matched the
predictions against works on the same map. Both steps leaked: the forces had already seen the later works,
and the later works had been chosen by following the same problems. This version:

  1. Splits the map at a cutoff (the 70th percentile of dates). Driving forces are rebuilt from the works up
     to the cutoff only, and the problems they raised.
  2. Predicts 4-6 next moves from those forces, and, as a baseline, from the same early works WITHOUT forces.
     The forces only earn credit for what they add over the baseline.
  3. Matches both sets, shuffled and unlabelled, against later works: the map's later works plus a sample of
     later papers found by a plain field search, which were not chosen by following the map's problems. Each
     match must point to what in the work realises the prediction, and each prediction gets a specificity
     score, so vague predictions that would match anything count for little.

The model may still know papers after the cutoff from its training. The baseline absorbs part of that (it
knows them just as well), and the report says so. Set TASTECAL_MODEL_CUTOFF=YYYY-MM to mark a backtest whose
cutoff falls inside the model's knowledge as illustrative.
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

from tastecal.core.config import from_env
from tastecal.prompts import lineage as prompts

log = logging.getLogger("tastecal.backtest")

OUTSIDE_MAX = 15
SPECIFIC = 2          # specificity (1-3) a matched prediction needs to count as a hit


def _cutoff(nodes) -> str:
    dates = sorted(n.item.sort_date for n in nodes if n.item.sort_date)
    return dates[int(len(dates) * 0.7)] if dates else ""


def outside_sample(g, field_name: str, seed_title: str, cutoff: str, on_map: set) -> List[dict]:
    """Later papers from a plain field search, not chosen by following the map's problems."""
    if not cutoff or not hasattr(g.src, "search"):
        return []
    year = int(cutoff[:4]) if cutoff[:4].isdigit() else None
    out, seen = [], set()
    for q in [x for x in (field_name, seed_title) if x][:2]:
        try:
            hits = g.src.search(q, year, limit=OUTSIDE_MAX)
        except Exception as e:  # rate limited, offline
            log.info("backtest: outside search failed for %r: %s", q, e)
            continue
        for it in hits:
            key = it.title.lower()
            if key in seen or it.id in on_map or not (it.sort_date or "") > cutoff:
                continue
            seen.add(key)
            out.append({"id": f"x{len(out) + 1}", "title": it.title, "date": it.sort_date,
                        "abstract": (it.abstract or "")[:500], "url": it.url})
    return out[:OUTSIDE_MAX]


def run(g, llm, nodes, field: dict, rng: Optional[random.Random] = None) -> dict:
    """The backtest. `nodes` are the grower's nodes sorted by date; `field` the synthesis' field object."""
    rng = rng or random.Random(11)
    cutoff = _cutoff(nodes)
    check: Dict[str, object] = {"cutoff": cutoff[:7], "predictions": [], "baseline": [], "misfits": []}
    if not cutoff:
        return check
    early = [n for n in nodes if n.item.sort_date and n.item.sort_date <= cutoff]
    recent = [n for n in nodes if n.item.sort_date and n.item.sort_date > cutoff]
    early_ids = {n.item.id for n in early}
    early_problems = [p for p in g.ledger.problems.values() if any(r in early_ids for r in p.raised_by)]
    name, goal = field.get("field", ""), field.get("goal", "")

    got = llm.json(prompts.SYSTEM, prompts.early_forces(name, goal, early, early_problems, cutoff))
    early_forces = [f for f in (got.get("driving_forces") if isinstance(got, dict) else []) or []
                    if isinstance(f, dict) and f.get("statement")]
    preds = llm.json(prompts.SYSTEM, prompts.predict({"field": name, "goal": goal, "core_tension": "",
                                                       "driving_forces": [dict(f, name=f.get("name", "")) for f in early_forces]},
                                                      cutoff))
    forced = [p for p in (preds.get("predictions") if isinstance(preds, dict) else []) or [] if isinstance(p, str)]
    null = llm.json(prompts.SYSTEM, prompts.predict_null(name, goal, early, cutoff))
    baseline = [p for p in (null.get("predictions") if isinstance(null, dict) else []) or [] if isinstance(p, str)]

    seed = g.nodes.get(g.seed_id)
    outside = outside_sample(g, name, seed.item.title if seed else "", cutoff, set(g.nodes))
    rows = [("F", t) for t in forced] + [("B", t) for t in baseline]
    rng.shuffle(rows)
    labels = {f"A{k + 1}": r for k, r in enumerate(rows)}
    scored = {}
    if rows and (recent or outside):
        res = llm.json(prompts.SYSTEM, prompts.check_blind([(k, t) for k, (_, t) in labels.items()], recent, outside))
        for r in (res.get("predictions") if isinstance(res, dict) else []) or []:
            if isinstance(r, dict) and r.get("id") in labels:
                scored[r["id"]] = r
    map_ids = {n.item.id for n in recent}
    out_ids = {w["id"]: w for w in outside}
    for k, (side, text) in labels.items():
        r = scored.get(k) or {}
        matched = [m for m in r.get("matched") or [] if m in map_ids]
        matched_out = [out_ids[m]["title"] for m in r.get("matched") or [] if m in out_ids]
        try:
            spec = max(1, min(3, int(r.get("specificity") or 1)))
        except (TypeError, ValueError):
            spec = 1
        row = {"text": text, "matched": matched, "outside": matched_out, "specificity": spec,
               "evidence": str(r.get("evidence") or "")[:300]}
        row["hit"] = bool(matched or matched_out) and spec >= SPECIFIC
        check["predictions" if side == "F" else "baseline"].append(row)
    # keep the forces' predictions in the order they were made
    order = {t: i for i, t in enumerate(forced)}
    check["predictions"].sort(key=lambda r: order.get(r["text"], 99))
    hits = sum(r["hit"] for r in check["predictions"])
    base = sum(r["hit"] for r in check["baseline"])
    check.update(hits=hits, baseline_hits=base, lift=hits - base, early_forces=early_forces,
                 sample={"map": len(recent), "outside": len(outside)},
                 outside=[{k: w[k] for k in ("id", "title", "date", "url")} for w in outside])
    model_cut = from_env("MODEL_CUTOFF")
    illustrative = bool(model_cut) and cutoff[:7] < model_cut[:7]
    check["illustrative"] = illustrative
    np, nb = len(check["predictions"]), len(check["baseline"])
    note = (f"Forces rebuilt from the {len(early)} works up to {cutoff[:7]} only. Predictions from those forces: "
            f"{hits} of {np} realised specifically; from the same works without forces: {base} of {nb}. "
            f"Matched against {len(recent)} later works on the map and {len(outside)} later papers from a plain "
            "field search, with both sets shuffled and unlabelled. ")
    if hits <= base:
        note += "The forces predict no better than the baseline, so this check does not support them. "
    note += ("The model may know later papers from its training; the baseline knows them equally, so the "
             "difference is the fairer number." + (" The cutoff falls inside the model's knowledge, so treat this "
                                                  "as illustrative." if illustrative else ""))
    if str(getattr(getattr(g, "cfg", None), "language", "en")).lower().startswith("zh"):
        note = (f"驱动力只用截止 {cutoff[:7]} 之前的 {len(early)} 篇工作重建。用这些驱动力做的预测，{np} 条中有 {hits} 条被"
                f"具体实现；不用驱动力、只看同一批工作的对照组，{nb} 条中有 {base} 条。对照的是图上 {len(recent)} 篇后续工作，"
                f"以及普通领域检索找到的 {len(outside)} 篇后续论文，两组预测打乱、去掉标签后一起匹配。")
        if hits <= base:
            note += "驱动力的预测并不比对照组好，所以这项检验不支持这些驱动力。"
        note += ("模型可能在训练中见过截止之后的论文；对照组同样见过，所以两组之差才是更公平的数字。"
                 + ("截止日期落在模型的知识范围内，结果只能作为示意。" if illustrative else ""))
    check["note"] = note
    return check
