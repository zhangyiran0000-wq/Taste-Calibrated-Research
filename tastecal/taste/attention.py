"""How much the field attends to a paper, for the taste calibration (taste/axes.py): the axis the reader's scores
are set against. Several measures, all counts:

    cumulative   citations a year since publication (OpenAlex, else Semantic Scholar); when too few papers have a
                 count, the run's own percentile of citations a year among the works seen while growing, by rank
    recent       citations a month over the last two calendar years (OpenAlex counts by year)
    influential  Semantic Scholar's influential citations a year (citations that build on the work, not a mention)
    stars        GitHub stars a year, when the audit found the work's repository

A count is put on 0 to 1 against papers of the same age (age_scale): citations pile up with age, so a paper is set
against the typical count of a paper of its age among the papers compared (a line through log(1 + count) against
log(months), fitted on those a year old or more), on a log scale: 0.5 is typical for its age, and the axis is
stretched so the middle 80% of these papers spans half of it. The landmark is the paper you rated highest (Attention
Is All You Need when none of your rated papers has a count: it is looked up in every run as ANCHOR_TITLE). It sits at
your score of it when the field still spans half to SPREAD_MAX of the axis that way; one far beyond the field makes
the axis past BREAK compressed so it still fits, and a paper of the field as attended as it would land beside it. Papers under NEW_MONTHS are not placed: their counts say
too little yet. With fewer than six papers a year old, the plain log scale of `scale` is used instead.

Every paper also gets a reliability: a paper months old with a handful of citations says little yet. It widens the
paper's attention bar on the chart and lowers its weight in the fit; it never removes the paper.
Nothing here reads a paper or asks a model: these are counts from the sources."""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional

log = logging.getLogger("tastecal.attention")

METRICS = ("cumulative", "recent", "influential", "stars")
FIT_METRIC = "cumulative"          # the measure the fit brings the papers towards; the others are views
ANCHOR_TITLE = "Attention Is All You Need"     # 1 on the attention scale when none of your rated papers has a count
ANCHOR_NODE = {"id": "anchor:attention-is-all-you-need", "title": ANCHOR_TITLE, "year": 2017, "date": "2017-06",
               "ids": {"s2": "arXiv:1706.03762"}}


def months_since(date_str: str, today: str) -> Optional[int]:
    from tastecal.judge.audit import months_between
    if not date_str or not today:
        return None
    return max(0, months_between(date_str, today))


def fetch(nodes: List[dict], openalex=None, s2=None) -> Dict[str, dict]:
    """Raw counts per node id, from the sources (cached by the http layer). A source that fails leaves its fields out."""
    from tastecal.core.model import Item
    out: Dict[str, dict] = {}
    for n in nodes:
        raw: dict = {}
        ids = n.get("ids") or {}
        if openalex is not None:
            try:
                wid = ids.get("openalex") or openalex.find(Item(id=n["id"], title=n.get("title", ""), year=n.get("year")))
                got = openalex.attention(wid) if wid else None
                if got:
                    raw.update(got)
            except Exception as e:  # one paper's lookup never stops the fit
                log.info("OpenAlex attention failed for %s: %s", n.get("title", "")[:60], e)
        if s2 is not None and ids.get("s2"):
            try:
                got = s2.counts(ids["s2"])
                if got:
                    raw.update(got)
            except Exception as e:
                log.info("S2 counts failed for %s: %s", n.get("title", "")[:60], e)
        out[n["id"]] = raw
    return out


def measures(node: dict, raw: Optional[dict], today: str) -> dict:
    """{"cumulative", "recent", "influential", "stars"} (values to rank; None when unknown), the source of the
    cumulative one, the paper's age in months, its citations, and its reliability (0.1 to 1)."""
    raw = raw or {}
    att = ((node.get("assessment") or {}).get("attention") or {})
    months = months_since(node.get("date") or raw.get("pub", "")[:7], today)
    # one rule for every paper: the count looked up now, the larger of OpenAlex's and Semantic Scholar's (both miss
    # citations, and a record matched wrongly shows few), else the one the map recorded for it (node, then audit)
    looked = [v for v in (raw.get("cited_by"), raw.get("s2_cites")) if v is not None]
    cites = max(looked) if looked else next((v for v in (node.get("citations"), att.get("citations")) if v is not None), None)
    rate = None if cites is None else cites / max(0.5, (months if months is not None else 12) / 12)
    cumulative, source = raw.get("pct"), "field and year (OpenAlex)"
    if cumulative is None and att.get("pct") is not None:
        cumulative, source = att.get("pct"), "neighbourhood of this run"
    if cumulative is None:
        source = ""
    recent = None
    by_year = raw.get("by_year") or {}
    if by_year and today:
        year, month = int(today[:4]), int(today[5:7] or 6)
        window = by_year.get(str(year), 0) + by_year.get(str(year - 1), 0)
        exposed = min(month + 12, months if months is not None else month + 12)
        recent = window / max(1, exposed)
    influential = None
    if raw.get("influential") is not None:
        influential = raw["influential"] / max(0.5, (months or 6) / 12)
    stars = att.get("stars_per_year") if not att.get("stars_shared_with") else None
    age = 1.0 if months is None else min(1.0, months / 18)
    count = 1.0 if cites is None else min(1.0, (cites + 1) / 6)
    rel = round(max(0.1, min(1.0, age * count)), 3)
    return {"cumulative": cumulative, "recent": recent, "influential": influential, "stars": stars,
            "source": source, "months": months, "citations": cites, "rel": rel,
            "pct_field": raw.get("pct"), "pct_run": att.get("pct"), "rate": None if rate is None else round(rate, 3)}


MIN_COUNTS = 8        # citation counts are used when at least this many of the papers have one (enough to fit to)
LOG_METRICS = ("recent", "influential", "stars")     # always counts: on the log scale


def unify(ms: List[dict], also: List[dict] = ()) -> str:
    """One measure of cumulative attention for every paper, never two mixed (counts and this run's percentile are on
    different scales: mixed, the papers with one all rank high and those with the other all rank low). Citations a
    year, on the log scale, when at least MIN_COUNTS of the papers `ms` (or nearly all) have a count (those without one have no
    attention: they are scored but neither fitted to the field nor drawn against it); else this run's own percentile
    for every paper, by rank. `also` (your rated papers, the anchor) get the same measure. Rewrites m["cumulative"],
    m["source"] and m["scale"]; returns the source used."""
    have = [m for m in ms if m.get("rate") is not None]
    counts = bool(have) and (len(have) >= MIN_COUNTS or len(have) >= 0.8 * len(ms))
    source = "citations a year" if counts else "neighbourhood of this run"
    for m in list(ms) + list(also):
        v = m.get("rate") if counts else m.get("pct_run")
        m["cumulative"], m["source"], m["scale"] = v, (source if v is not None else ""), ("log" if counts else "rank")
    log.info("cumulative attention: %s for all papers (%d of %d have a citation count)",
             "citations a year, log scale" if counts else "the run's own percentile, by rank", len(have), len(ms))
    return source


def scale(rows: List[dict], metric: str, anchors: List[float] = (), top=None) -> Optional[dict]:
    """How a count of `metric` is put on 0 to 1 for these rows (see the module note): {"median", "top", "x_top", "L"}:
    these rows' median count (for the page), the reference count and where it sits (x_top), and log(1 + top). `top`
    is (count, x) of your highest-rated paper, or a bare count that sits at 1 (Attention Is All You Need) unless a
    known count is larger; without one, the largest count among the rows and the `anchors` (your rated papers) sits
    at 1. None when fewer than two rows have the measure."""
    vals = sorted(max(0.0, float(r["m"][metric])) for r in rows if (r.get("m") or {}).get(metric) is not None)
    if len(vals) < 2:
        return None
    known = vals + [max(0.0, float(a)) for a in anchors if a is not None]
    if isinstance(top, (tuple, list)) and top[0] and float(top[0]) > 0:
        ref, x_top = float(top[0]), float(top[1])
    else:                                        # a bare count sits at 1; nothing known may pass it
        ref, x_top = max(known + [float(top) if top else 0.0]), 1.0
    ref = max(float(ref), 1.0)                   # never a reference below one citation: the log would blow up
    half = len(vals) // 2
    med = vals[half] if len(vals) % 2 else math.expm1((math.log1p(vals[half - 1]) + math.log1p(vals[half])) / 2)
    x_top = round(max(0.05, min(1.0, float(x_top))), 3)
    return {"median": round(med, 3), "top": round(ref, 3), "x_top": x_top, "L": math.log1p(ref)}


AGE = True          # against papers of the same age (age_scale); False only to compare with the plain log scale


def place(v: float, sc: dict) -> float:
    """A count on 0 to 1 on the plain log scale: x_top * log(1 + v) / log(1 + top), at most 1."""
    return max(0.0, min(1.0, sc["x_top"] * math.log1p(max(0.0, v)) / sc["L"]))


def count_at(x: float, sc: dict) -> float:
    """The count that sits at x on the plain log scale (the inverse of place)."""
    return math.expm1(max(0.0, x) / sc["x_top"] * sc["L"])


NEW_MONTHS = 12      # younger: its counts say too little yet; not placed by attention, never fitted to it
SPREAD = 0.5         # the middle 80% of the field's papers (a year old or more) spans at least this much of the axis
SPREAD_MAX = 0.8     # and at most this much, however close to typical your top paper is
BREAK = 0.88         # past this, the axis is compressed so the landmark still fits (drawn with a break)
TOP_END = 0.98       # where the landmark lands when the axis is compressed


def age_scale(rows: List[dict], metric: str, top=None) -> Optional[dict]:
    """The age scale (see the module note): a paper's count against the typical count of a paper of its age among
    these rows. The typical count: log(1 + v) = a + b log(months), fitted on the rows a year old or more; a paper's
    ratio to it, r, is measured from these rows' median ratio, so the typical paper of its age is 0.5. Stretch: the
    middle 80% of the rows spans SPREAD, or more when that puts `top` (count, your score, months) at your score.
    When `top` would land past TOP_END, the axis past BREAK is compressed so it lands at TOP_END. None when fewer
    than six rows are a year old with the measure."""
    pts = [(math.log(r["m"]["months"]), math.log1p(max(0.0, float(r["m"][metric]))))
           for r in rows if (r.get("m") or {}).get(metric) is not None and (r["m"].get("months") or 0) >= NEW_MONTHS]
    if len(pts) < 6:
        return None
    mx, my = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    b = max(0.0, sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx) if sxx > 1e-9 else 0.0
    a = my - b * mx
    res = sorted(p[1] - (a + b * p[0]) for p in pts)
    med = quantile(res, 0.5)
    span = max(quantile(res, 0.9) - quantile(res, 0.1), 0.3)
    sc = {"kind": "age", "a": a, "b": b, "med": med, "k": SPREAD / span, "n": len(pts)}
    if isinstance(top, (tuple, list)) and len(top) >= 3 and top[0] and top[2]:
        r_top = math.log1p(float(top[0])) - (a + b * math.log(max(1.0, float(top[2])))) - med
        sc["top_ratio"] = math.exp(r_top)
        if r_top > 0:                            # your top paper at your score, if the field still spans half to
            k_top = (float(top[1]) - 0.5) / r_top    # SPREAD_MAX of the axis; else where the field's stretch puts it
            sc["k"] = max(sc["k"], min(k_top, SPREAD_MAX / span))
        lin = 0.5 + sc["k"] * r_top
        if lin > TOP_END:                        # far beyond the field: the end of the axis is compressed
            sc["cut"] = lin
        sc["top_x"] = round(_bend(lin, sc), 3)
    return sc


def _bend(lin: float, sc: dict) -> float:
    """Past BREAK, the compressed part of the axis (when there is one)."""
    if sc.get("cut") and lin > BREAK:
        lin = BREAK + (lin - BREAK) * (TOP_END - BREAK) / (sc["cut"] - BREAK)
    return max(0.0, min(1.0, lin))


def age_ratio(v: float, months: float, sc: dict) -> float:
    """How many times the typical paper of its age (on log(1 + count)): 1 is typical."""
    return math.exp(math.log1p(max(0.0, v)) - (sc["a"] + sc["b"] * math.log(max(1.0, months))) - sc["med"])


def age_place(v: float, months: float, sc: dict) -> float:
    return _bend(0.5 + sc["k"] * math.log(age_ratio(v, months, sc)), sc)


def ratio_at(t: float, sc: dict) -> float:
    """Where "t times the typical paper of its age" sits on the axis."""
    return _bend(0.5 + sc["k"] * math.log(t), sc)


def position(rows: List[dict], metric: str, scores: Dict[str, float], anchors: List[float] = (),
             top: Optional[float] = None) -> Dict[str, dict]:
    """Each row's attention on 0 to 1. Counts through the log scale of `scale` and `place`, anchored at `top` (your
    highest-rated paper's count and score, or Attention Is All You Need at 1). The bar: the count
    moved by the paper's unreliability (v -/+ u (v + 1), u = 1 - reliability). A measure that is not a count
    (the run's own percentile) is put on your scale by rank instead (on_scale). rows: [{"id", "m"}]; returns {id:
    {"rank", "x", "lo", "hi"}}."""
    have = [r for r in rows if (r.get("m") or {}).get(metric) is not None and r["id"] in scores]
    if len(have) < 2:
        return {}
    is_log = metric in LOG_METRICS or all((r["m"].get("scale") == "log") for r in have)
    if not is_log:
        return on_scale(rows, metric, scores)
    sa = age_scale(have, metric, top) if AGE else None
    if sa:                                       # against papers of the same age; the newest are not placed
        out = {}
        vals = [max(0.0, float(r["m"][metric])) for r in have]
        for r, v in zip(have, vals):
            mo = r["m"].get("months")
            if mo is None or mo < NEW_MONTHS:
                continue
            spread = (1 - r["m"].get("rel", 1.0)) * (v + 1)
            out[r["id"]] = {"rank": round(rank(vals, v), 3), "x": round(age_place(v, mo, sa), 3),
                            "t": round(age_ratio(v, mo, sa), 2),
                            "lo": round(age_place(max(0.0, v - spread), mo, sa), 3),
                            "hi": round(age_place(v + spread, mo, sa), 3)}
        return out
    sc = scale(have, metric, anchors, top)
    vals = [max(0.0, float(r["m"][metric])) for r in have]
    out = {}
    for r, v in zip(have, vals):
        u = 1 - r["m"].get("rel", 1.0)
        spread = u * (v + 1)                     # +1: a paper with no citation yet has a bar too
        out[r["id"]] = {"rank": round(rank(vals, v), 3), "x": round(place(v, sc), 3),
                        "lo": round(place(max(0.0, v - spread), sc), 3), "hi": round(place(v + spread, sc), 3)}
    return out


def rank(values: List[float], v: float) -> float:
    """Share of the values below v, ties counting half; 0 to 1."""
    if not values:
        return 0.5
    return (sum(u < v for u in values) + 0.5 * sum(u == v for u in values)) / len(values)


def quantile(sorted_vals: List[float], q: float) -> float:
    """The value at rank q (0 to 1) of an ascending list, interpolated."""
    if not sorted_vals:
        return 0.5
    q = max(0.0, min(1.0, q))
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (pos - lo) * (sorted_vals[hi] - sorted_vals[lo])


def on_scale(rows: List[dict], metric: str, scores: Dict[str, float]) -> Dict[str, dict]:
    """Each row's attention on the reader's scale: its rank among the rows that have the measure, read off the
    distribution of the scores of those same rows (so the two axes share a scale and y = x means the field ranks a
    paper where the reader's line does). The bar: the rank moved by the paper's unreliability, on the same scale.
    rows: [{"id", "m": measures}]; returns {id: {"rank", "x", "lo", "hi"}}."""
    have = [r for r in rows if (r.get("m") or {}).get(metric) is not None and r["id"] in scores]
    if len(have) < 2:
        return {}
    vals = [r["m"][metric] for r in have]
    ref = sorted(scores[r["id"]] for r in have)
    out = {}
    for r in have:
        q = rank(vals, r["m"][metric])
        hw = 0.5 * (1 - r["m"].get("rel", 1.0))
        out[r["id"]] = {"rank": round(q, 3), "x": round(quantile(ref, q), 3),
                        "lo": round(quantile(ref, q - hw), 3), "hi": round(quantile(ref, q + hw), 3)}
    return out
