"""From a grown graph to the mechanism of the field.

1. threads      cluster the ledger's problems into 3-6 persistent questions
2. why-ladders  for each thread, ask "why is this hard?" until a root no paper can change
3. field        merge threads that share a root into driving forces; goal, core tension,
                enabling insight, external drivers, knock-on effects, open problems, roles
4. check        a backtest (backtest.py): forces rebuilt from early works only predict next moves, against a
                no-forces baseline, matched blind to later works on and off the map; then see which recent works
                realise them; list works no force explains
5. story        a newcomer's narrative with [[id]] links into the graph
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Dict, List

from tastecal import __version__
from tastecal.prompts import lineage as prompts
from tastecal.lineage.grow import Grower
from tastecal.core.llm import LLM
from tastecal.core.model import ROLES, slugify
from tastecal.core.schema import SCHEMA_ID

log = logging.getLogger("tastecal.synth")


def _rekey(g: Grower) -> Dict[str, str]:
    """Give every node a short readable id (lora, qlora, …) before synthesis."""
    taken: set = set()
    mapping: Dict[str, str] = {}
    order = sorted(g.nodes.values(), key=lambda n: (n.item.id != g.seed_id, n.item.sort_date))
    for n in order:
        base = n.card.short if n.card else n.item.title
        mapping[n.item.id] = slugify(base, taken)
    nodes = {}
    for old, n in g.nodes.items():
        n.item.ids["key"] = old
        n.item.id = mapping[old]
        nodes[n.item.id] = n
    g.nodes = nodes
    edges = {}
    for (s, t), e in g.edges.items():
        e.source, e.target = mapping.get(s, s), mapping.get(t, t)
        edges[(e.source, e.target)] = e
    g.edge_strength = {(mapping.get(s, s), mapping.get(t, t)): v for (s, t), v in g.edge_strength.items()}
    g.edges = edges
    for p in g.ledger.problems.values():
        p.raised_by = [mapping.get(x, x) for x in p.raised_by]
        p.addressed_by = [mapping.get(x, x) for x in p.addressed_by]
    g.seed_id = mapping[g.seed_id]
    for r in g.rounds:
        r["expanded"] = [mapping.get(x, x) for x in r.get("expanded", [])]
        if r.get("must"):
            r["must"] = [mapping.get(x, x) for x in r["must"]]
    for row in getattr(g, "imports", {}).values():
        row["used_by"] = [mapping.get(x, x) for x in row["used_by"]]
    return mapping


def synthesize(g: Grower, llm: LLM, seed_ref: str) -> dict:
    _rekey(g)
    seed = g.nodes[g.seed_id]
    nodes = sorted(g.nodes.values(), key=lambda n: n.item.sort_date)
    problems = list(g.ledger.problems.values())
    ids = set(g.nodes)

    # 1. threads ------------------------------------------------------------
    res = llm.json(prompts.SYSTEM, prompts.threads(seed, nodes, problems))
    thread_rows = [t for t in (res.get("threads") or []) if isinstance(t, dict) and t.get("id")]
    if not thread_rows:
        thread_rows = [{"id": "T1", "name": "Main line", "question": "What problem does this line of work solve?",
                        "problems": [p.id for p in problems], "status": "active", "status_note": ""}]
    tids = [t["id"] for t in thread_rows]
    assign = res.get("assign") or {}
    for n in nodes:
        ts = [t for t in (assign.get(n.item.id) or []) if t in tids]
        n.threads = ts
    # Unassigned items inherit the primary thread of their strongest neighbour.
    for n in nodes:
        if n.threads:
            continue
        for (s, t), e in sorted(g.edges.items(), key=lambda kv: -g.edge_strength.get(kv[0], 0)):
            other = t if s == n.item.id else s if t == n.item.id else None
            if other and g.nodes[other].threads:
                n.threads = [g.nodes[other].threads[0]]
                break
        n.threads = n.threads or [tids[0]]
    for t in thread_rows:
        t["nodes"] = [n.item.id for n in nodes if t["id"] in n.threads]
        t["problems"] = [p for p in t.get("problems", []) if g.ledger.get(p)]
        for p in t["problems"]:
            g.ledger.get(p).thread = t["id"]

    # 2. why-ladders ----------------------------------------------------------
    ladders = llm.json(prompts.SYSTEM, prompts.why_ladders(thread_rows, g.nodes, g.ledger.problems))
    ladders = ladders if isinstance(ladders, dict) else {}

    # 3. field ---------------------------------------------------------------
    field = llm.json(prompts.SYSTEM, prompts.field(seed, nodes, thread_rows, ladders))
    field = field if isinstance(field, dict) else {}
    forces = [f for f in field.get("driving_forces") or [] if isinstance(f, dict) and f.get("id")]
    for f in forces:
        f["threads"] = [t for t in f.get("threads", []) if t in tids]
    owner = {t: f["id"] for f in forces for t in f["threads"]}
    if forces:
        for t in tids:  # every thread belongs to exactly one force
            if t not in owner:
                forces[0]["threads"].append(t)
                owner[t] = forces[0]["id"]
    roles = field.get("roles") or {}
    for n in nodes:
        n.role = "seed" if n.item.id == g.seed_id else (roles.get(n.item.id) if roles.get(n.item.id) in ROLES else "improvement")
    knock = [k for k in field.get("knock_on") or [] if isinstance(k, dict)
             and k.get("from_thread") in tids and k.get("to_thread") in tids and k.get("via") in ids]

    # 4. check ----------------------------------------------------------------
    # The backtest rebuilds forces from early works only and compares with a no-forces baseline (backtest.py).
    # Off by default (--backtest): the report no longer shows it, so it would only cost calls.
    field_view = dict(field, driving_forces=forces)
    check: dict = {}
    if getattr(g.cfg, "backtest", False):
        from tastecal.lineage import backtest
        check = backtest.run(g, llm, nodes, field_view)
        # Coverage: does every work on the map fit one of the (full-map) forces?
        chk = llm.json(prompts.SYSTEM, prompts.misfits(nodes, forces))
        if isinstance(chk, dict):
            check["misfits"] = [m for m in chk.get("misfits", []) if isinstance(m, dict) and m.get("id") in ids]
        # Borrowed tools from other fields are not expected to fit this field's forces.
        own = [n for n in nodes if not getattr(n, "borrowed", False)]
        own_ids = {n.item.id for n in own}
        check["misfits"] = [m for m in check["misfits"] if m["id"] in own_ids]
        misfit_ids = {m["id"] for m in check["misfits"]}
        fit = sum(1 for n in own if n.item.id not in misfit_ids and any(t in owner for t in n.threads))
        check["coverage"] = {"fit": fit, "total": len(own)}

    # 5. story ------------------------------------------------------------------
    story = llm.json(prompts.SYSTEM, prompts.narrative(field_view, thread_rows, nodes))
    story = story if isinstance(story, dict) else {"title": "", "paragraphs": []}
    story["paragraphs"] = [re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(0) if m.group(1) in ids else m.group(1), p)
                           for p in story.get("paragraphs", []) if isinstance(p, str)]

    # assemble -------------------------------------------------------------------
    threads_out = []
    for t in thread_rows:
        lad = ladders.get(t["id"]) or {}
        threads_out.append({
            "id": t["id"], "name": t.get("name", t["id"]), "question": t.get("question", ""),
            "status": t.get("status", "active"), "status_note": t.get("status_note", ""),
            "force": owner.get(t["id"], ""), "problems": t["problems"],
            "ladder": {"rungs": [r for r in lad.get("rungs", []) if isinstance(r, dict)],
                       "root_type": lad.get("root_type", "other")},
        })
    out = {
        "schema": SCHEMA_ID,
        "meta": {
            "seed": g.seed_id,
            "seed_ref": seed_ref,
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "generator": f"tastecal {__version__}",
            "model": getattr(llm, "name", ""),
            "budget": g.cfg.budget,
            "note": "",
            "usage": llm.usage(),
        },
        "field": {
            "name": field.get("field", ""), "goal": field.get("goal", ""),
            "core_tension": field.get("core_tension", ""),
            "enabling_insights": [i for i in field.get("enabling_insights") or [] if isinstance(i, dict)],
            "driving_forces": forces,
            "external_drivers": [d for d in field.get("external_drivers") or [] if isinstance(d, dict)],
            "knock_on": knock,
            "open_problems": [p for p in field.get("open_problems") or [] if isinstance(p, str)],
            "keywords": [k.strip() for k in field.get("keywords") or [] if isinstance(k, str) and k.strip()][:8],
        },
        "threads": threads_out,
        "problems": [dict(p, thread=g.ledger.get(p["id"]).thread) for p in g.ledger.as_list()],
        "nodes": [node_json(n) for n in nodes],
        "edges": [{"source": e.source, "target": e.target, "type": e.type, "label": e.label,
                   "evidence": e.evidence, "evidence_source": e.evidence_source,
                   "confidence": e.confidence, "problem": e.problem} for e in g.edges.values()],
        "story": {"title": story.get("title", ""), "paragraphs": story["paragraphs"]},
        "check": check,
        "rounds": g.rounds,
    }
    if g.field:
        out["meta"]["scope"] = g.field
        out["meta"]["scope_source"] = "user" if g.cfg.scope else "inferred"
    if getattr(g, "must_missing", None):          # must-read papers that could not be found
        out["meta"]["must_missing"] = list(g.must_missing)
    if g.field or g.imports_list():
        out["imports"] = g.imports_list()
    return out


def node_json(n) -> dict:
    it, c = n.item, n.card
    return {
        "id": it.id, "title": it.title, "short": c.short if c else it.title[:30], "kind": it.kind,
        "date": it.date or (str(it.year) if it.year else ""), "year": it.year,
        "authors": it.author_line(), "venue": it.venue, "url": it.url, "citations": it.citations, "ids": dict(it.ids or {}),
        "role": n.role or "improvement", "threads": n.threads, "hop": n.hop, "direction": n.direction,
        "round": n.round, **({"borrowed": True} if getattr(n, "borrowed", False) else {}),
        **({"must": True} if getattr(n, "must", False) else {}),
        "card": {"inherits": c.inherits, "move": c.move, "insight": c.insight, "leaves": c.leaves,
                 "summary": c.summary} if c else {},
    }
