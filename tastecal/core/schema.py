"""The graph.json contract shared by the pipeline, the demo and the report page."""
from __future__ import annotations

from typing import List

from tastecal.core.model import KINDS, RELATION_TYPES, ROLES

SCHEMA_ID = "deepanalyze.graph/1"
ROOT_TYPES = ("hardware", "math", "data", "goal", "economics", "other")


def validate(g: dict) -> List[str]:
    """Return a list of human-readable problems; empty means valid."""
    errs: List[str] = []
    for key in ("meta", "field", "threads", "nodes", "edges"):
        if key not in g:
            errs.append(f"missing top-level key: {key}")
    if errs:
        return errs
    node_ids = [n.get("id") for n in g["nodes"]]
    ids = set(node_ids)
    if len(ids) != len(node_ids):
        errs.append("duplicate node ids")
    thread_ids = {t.get("id") for t in g["threads"]}
    force_ids = {f.get("id") for f in g["field"].get("driving_forces", [])}
    problem_ids = {p.get("id") for p in g.get("problems", [])}

    seeds = [n for n in g["nodes"] if n.get("role") == "seed"]
    if len(seeds) != 1:
        errs.append(f"expected exactly one seed node, found {len(seeds)}")
    for n in g["nodes"]:
        nid = n.get("id")
        for k in ("title", "short", "kind", "date", "threads", "card"):
            if not n.get(k):
                errs.append(f"node {nid}: missing {k}")
        if n.get("kind") and n["kind"] not in KINDS:
            errs.append(f"node {nid}: unknown kind {n['kind']}")
        if n.get("role") and n["role"] not in ROLES:
            errs.append(f"node {nid}: unknown role {n['role']}")
        for t in n.get("threads", []):
            if t not in thread_ids:
                errs.append(f"node {nid}: unknown thread {t}")
    for e in g["edges"]:
        tag = f"edge {e.get('source')}→{e.get('target')}"
        if e.get("source") not in ids or e.get("target") not in ids:
            errs.append(f"{tag}: endpoint not a node")
        if e.get("type") not in RELATION_TYPES:
            errs.append(f"{tag}: unknown type {e.get('type')}")
        if not e.get("label"):
            errs.append(f"{tag}: missing label")
        if e.get("confidence") not in ("stated", "inferred"):
            errs.append(f"{tag}: confidence must be stated or inferred")
    for t in g["threads"]:
        if t.get("force") and t["force"] not in force_ids:
            errs.append(f"thread {t.get('id')}: unknown force {t['force']}")
        for p in t.get("problems", []):
            if problem_ids and p not in problem_ids:
                errs.append(f"thread {t.get('id')}: unknown problem {p}")
        rungs = (t.get("ladder") or {}).get("rungs") or []
        if len(rungs) < 2:
            errs.append(f"thread {t.get('id')}: why-ladder needs at least 2 rungs")
    for f in g["field"].get("driving_forces", []):
        for t in f.get("threads", []):
            if t not in thread_ids:
                errs.append(f"force {f.get('id')}: unknown thread {t}")
    for k in g["field"].get("knock_on", []):
        if k.get("via") and k["via"] not in ids:
            errs.append(f"knock-on via unknown node {k['via']}")
    for p in g.get("problems", []):
        for ref in p.get("raised_by", []) + p.get("addressed_by", []) + p.get("claimed_by", []):
            if ref not in ids:
                errs.append(f"problem {p.get('id')}: unknown node {ref}")
    errs += _validate_audit(g, ids)
    errs += _validate_gates(g, ids)
    errs += _validate_v2(g, ids, thread_ids, problem_ids)
    return errs


def _validate_v2(g: dict, ids: set, thread_ids: set, problem_ids: set) -> List[str]:
    """Optional v2 fields: graph['outlook'], graph['quality'], node['gates']['checks']."""
    from tastecal.judge.gates import CHECK_VALUES
    errs: List[str] = []
    o = g.get("outlook")
    if o is not None:
        for a in o.get("active") or []:
            if a.get("thread") not in thread_ids:
                errs.append(f"outlook: active row for unknown thread {a.get('thread')}")
            errs += [f"outlook: active names unknown node {x}" for x in a.get("nodes") or [] if x not in ids]
        for s in o.get("next_steps") or []:
            if not s.get("text"):
                errs.append("outlook: next step without text")
            if s.get("problem") and s["problem"] not in problem_ids:
                errs.append(f"outlook: next step names unknown problem {s['problem']}")
            errs += [f"outlook: next step names unknown node {x}" for x in s.get("attempts") or [] if x not in ids]
        for a in o.get("assumptions") or []:
            if not a.get("text"):
                errs.append("outlook: assumption without text")
            errs += [f"outlook: assumption names unknown node {x}" for x in a.get("nodes") or [] if x not in ids]
            errs += [f"outlook: assumption names unknown thread {x}" for x in a.get("threads") or [] if x not in thread_ids]
    for d in (g.get("quality") or {}).get("disagreements") or []:
        if d.get("id") not in ids:
            errs.append(f"quality: disagreement about unknown node {d.get('id')}")
    for n in g.get("nodes") or []:
        ck = (n.get("gates") or {}).get("checks") or {}
        for k, allowed in CHECK_VALUES.items():
            if k in ck and ck[k] not in allowed:
                errs.append(f"gates {n.get('id')}: unknown {k} check {ck[k]}")
    return errs


def _validate_audit(g: dict, ids: set) -> List[str]:
    """Optional audit fields: node['assessment'], graph['pool'], graph['audit']."""
    from tastecal.judge.audit import FLAGS, QUADRANTS
    errs: List[str] = []
    pool = g.get("pool") or []
    pool_ids = [w.get("id") for w in pool]
    if len(set(pool_ids)) != len(pool_ids):
        errs.append("duplicate pool ids")
    for pid in set(pool_ids) & ids:
        errs.append(f"pool item {pid}: id also used by a map node")
    for w in pool:
        if not w.get("id") or not w.get("title"):
            errs.append("pool item without id or title")
    rows = [(n.get("id"), n.get("assessment")) for n in g["nodes"]] + [(w.get("id"), w.get("assessment")) for w in pool]
    assessed = 0
    for nid, a in rows:
        if a is None:
            continue
        assessed += 1
        if a.get("flag") not in FLAGS:
            errs.append(f"assessment {nid}: unknown flag {a.get('flag')}")
        if a.get("quadrant") not in QUADRANTS:
            errs.append(f"assessment {nid}: unknown quadrant {a.get('quadrant')}")
        sc = (a.get("contribution") or {}).get("score")
        if not isinstance(sc, (int, float)) or not 0 <= sc <= 1:
            errs.append(f"assessment {nid}: contribution score must be in [0, 1]")
        pct = (a.get("attention") or {}).get("pct")
        if not isinstance(pct, (int, float)) or not 0 <= pct <= 1:
            errs.append(f"assessment {nid}: attention pct must be in [0, 1]")
    if assessed and "audit" not in g:
        errs.append("assessments present but no top-level audit block")
    if "audit" in g:
        for k in ("thresholds", "counts", "method", "caveats"):
            if k not in g["audit"]:
                errs.append(f"audit: missing {k}")
    return errs


def _validate_gates(g: dict, ids: set) -> List[str]:
    """Optional gate fields: node['gates'], graph['gates'], problem['claimed_by'] and status."""
    from tastecal.judge.gates import BASES, DELIVERY, LEVERS, REASON_TYPES, ROBUSTNESS, VERDICTS
    errs: List[str] = []
    gated = 0
    for n in g["nodes"]:
        x = n.get("gates")
        if x is None:
            continue
        gated += 1
        nid = n.get("id")
        for key, allowed in (("verdict", VERDICTS), ("delivery", DELIVERY), ("reason_type", REASON_TYPES),
                             ("robustness", ROBUSTNESS), ("basis", BASES)):
            if x.get(key) not in allowed:
                errs.append(f"gates {nid}: unknown {key} {x.get(key)}")
        if not isinstance(x.get("fold"), bool):
            errs.append(f"gates {nid}: fold must be true or false")
        elif x["fold"] and (n.get("role") == "seed" or x.get("basis") != "full text" or x.get("verdict") not in ("incremental", "not-delivered")):
            errs.append(f"gates {nid}: folded against the rules")
        elif x["fold"] and not ((x.get("fold_reason") or {}).get("summary") and (x.get("fold_reason") or {}).get("evidence")):
            errs.append(f"gates {nid}: folded without a reason and evidence")
        a = x.get("attractiveness")
        if a is not None and (not isinstance(a, (int, float)) or not 0 <= a <= 1):
            errs.append(f"gates {nid}: attractiveness must be in [0, 1]")
        for lv in x.get("levers") or []:
            if lv.get("lever") not in LEVERS:
                errs.append(f"gates {nid}: unknown lever {lv.get('lever')}")
        r = x.get("reaction") or {}
        for ref in (r.get("adopted_by") or []) + (r.get("challenged_by") or []):
            if ref not in ids:
                errs.append(f"gates {nid}: reaction names unknown node {ref}")
    if gated and "gates" not in g:
        errs.append("gates present on nodes but no top-level gates block")
    if "gates" in g:
        for k in ("thresholds", "counts", "method", "caveats"):
            if k not in g["gates"]:
                errs.append(f"gates: missing {k}")
    for p in g.get("problems", []):
        if p.get("status") and p["status"] not in ("addressed", "claimed", "open"):
            errs.append(f"problem {p.get('id')}: unknown status {p['status']}")
        if set(p.get("claimed_by") or []) & set(p.get("addressed_by") or []):
            errs.append(f"problem {p.get('id')}: a work is both addressing and only claiming it")
    return errs
