"""What's next: who is working on what now, the next step for each open problem, and the assumptions
the whole map shares.

`active` is computed from dates alone. `next_steps` and `assumptions` come from one LLM call over the
finished graph, and every id it names is checked against the graph. Nothing here predicts a new
paradigm: the assumptions are where one would start looking, not a forecast.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Dict, List, Optional

from tastecal.judge.audit import months_between

log = logging.getLogger("tastecal.outlook")

NOTE = {
    "en": "Next steps follow from the open problems. A new paradigm cannot be predicted; the shared assumptions are where one would start looking.",
    "zh": "下一步来自尚未解决的问题。新范式无法预测；共同假设是可以开始找的地方。",
}


def active(graph: dict, today: str, months: int = 12) -> List[dict]:
    """Per thread, the works released in the last `months` months, newest first."""
    seed = (graph.get("meta") or {}).get("seed")
    out = []
    for t in graph.get("threads") or []:
        ids = [n for n in graph.get("nodes") or []
               if t["id"] in (n.get("threads") or []) and n.get("date") and n.get("id") != seed
               and 0 <= months_between(n["date"], today) < months]
        ids.sort(key=lambda n: n["date"], reverse=True)
        if ids:
            out.append({"thread": t["id"], "nodes": [n["id"] for n in ids]})
    return out


def clean(res, graph: dict) -> Dict[str, list]:
    ids = {n["id"] for n in graph.get("nodes") or []}
    tids = {t["id"] for t in graph.get("threads") or []}
    pids = {p["id"] for p in graph.get("problems") or []}
    res = res if isinstance(res, dict) else {}
    steps, assumptions = [], []
    for s in res.get("next_steps") or []:
        if not isinstance(s, dict) or not s.get("text"):
            continue
        steps.append({"problem": s.get("problem") if s.get("problem") in pids else "", "text": str(s["text"]),
                      "attempts": [x for x in s.get("attempts") or [] if x in ids][:5], "settle": str(s.get("settle") or "")})
    for a in res.get("assumptions") or []:
        if not isinstance(a, dict) or not a.get("text"):
            continue
        assumptions.append({"text": str(a["text"]), "threads": [x for x in a.get("threads") or [] if x in tids],
                            "nodes": [x for x in a.get("nodes") or [] if x in ids][:6], "if_broken": str(a.get("if_broken") or "")})
    return {"next_steps": steps[:6], "assumptions": assumptions[:5]}


def build(graph: dict, llm=None, today: Optional[str] = None, months: int = 12) -> dict:
    """Set graph['outlook']. Without an LLM only `active` is filled."""
    from tastecal.prompts import lineage as prompts
    today = today or dt.date.today().strftime("%Y-%m")
    lang = "zh" if str((graph.get("meta") or {}).get("language", "")).lower().startswith("zh") else "en"
    out = {"today": today, "window_months": months, "active": active(graph, today, months),
           "next_steps": [], "assumptions": [], "note": NOTE[lang]}
    if llm is not None:
        try:
            res = llm.json(prompts.SYSTEM, prompts.outlook(graph.get("field") or {}, graph.get("threads") or [],
                                                           graph.get("problems") or [], graph.get("nodes") or [], today))
            out.update(clean(res, graph))
        except Exception as e:  # keep what dates alone can give
            log.warning("outlook failed: %s", e)
    graph["outlook"] = out
    return graph
