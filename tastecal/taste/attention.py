"""How much the field attends to a paper, for the taste calibration (taste/axes.py): the axis the reader's scores
are set against. Several measures, all counts:

    cumulative   citations a year since publication (OpenAlex, else Semantic Scholar); when too few papers have a
                 count, the run's own percentile of citations a year among the works seen while growing, by rank
    recent       citations a month over the last two calendar years (OpenAlex counts by year)
    influential  Semantic Scholar's influential citations a year (citations that build on the work, not a mention)
    stars        GitHub stars a year, when the audit found the work's repository

A count is put on 0 to 1 on a log scale anchored at the paper you rated highest: x = s0 * log(1 + v) / log(1 + v0),
where v0 is that paper's count and s0 your score of it, so it sits on y = x at your own score, no citation is 0, and
a count above v0 goes past s0 (up to 1). Citations spread over orders of magnitude, so the log, not the count, is
compared with your linear scores. When none of your rated papers has the measure, Attention Is All You Need
(ANCHOR_TITLE, looked up in every run) is 1, else the most attended paper known.

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
    out = {"median": round(med, 3), "top": round(ref, 3), "x_top": x_top, "L": math.log1p(ref)}
    if ORIGIN == "median" and x_top > 0.55 and math.log1p(ref) > math.log1p(med) + 0.5:
        out.update(origin="median", Lm=math.log1p(med))
    return out


ORIGIN = "zero"     # "zero": no citation is 0; "median": these papers' median is 0.5 (compared on the page, one stays)


def place(v: float, sc: dict) -> float:
    """A count on 0 to 1: x_top * log(1 + v) / log(1 + top), at most 1 (or through the median at 0.5)."""
    lv = math.log1p(max(0.0, v))
    if sc.get("origin") == "median":
        return max(0.0, min(1.0, 0.5 + (sc["x_top"] - 0.5) * (lv - sc["Lm"]) / (sc["L"] - sc["Lm"])))
    return max(0.0, min(1.0, sc["x_top"] * lv / sc["L"]))


def count_at(x: float, sc: dict) -> float:
    """The count that sits at x on this scale (the inverse of place)."""
    if sc.get("origin") == "median":
        return max(0.0, math.expm1(sc["Lm"] + (x - 0.5) * (sc["L"] - sc["Lm"]) / (sc["x_top"] - 0.5)))
    return math.expm1(max(0.0, x) / sc["x_top"] * sc["L"])


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
