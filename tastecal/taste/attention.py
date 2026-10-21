"""How much the field attends to a paper, for the taste calibration (taste/axes.py): the axis the reader's scores
are set against. Several measures, all counts:

    cumulative   citations a year since publication (OpenAlex, else Semantic Scholar); when too few papers have a
                 count, the run's own percentile of citations a year among the works seen while growing, by rank
    recent       citations a month over the last two calendar years (OpenAlex counts by year)
    influential  Semantic Scholar's influential citations a year (citations that build on the work, not a mention)
    stars        GitHub stars a year, when the audit found the work's repository

A count is put on 0 to 1 through a normal distribution on the log of the count, l = log(1 + v), in two halves that
meet at the median of the papers compared in this run (0.5). Below it, the spread is these papers' own: sigma = (m -
q) / 0.674, q the lower quartile, so the little-cited new papers are spread out rather than pressed to 0. Above it,
Attention Is All You Need (ANCHOR_TITLE, looked up in every run) is +3 sigma: sigma = (L - m) / 3, so the scale still
ends at the landmark and no paper of the field looks as attended as it. x = Phi((l - m) / sigma). When the landmark
cannot be looked up, the most attended paper known (your rated papers included) takes its place. Not linear:
citations spread over orders of magnitude.

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
ANCHOR_TITLE = "Attention Is All You Need"     # +3 sigma of the attention scale (no citation is -3 sigma)
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


def median_(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def _quartile(sorted_vals: List[float]) -> float:
    """The lower quartile of an ascending list, interpolated."""
    return quantile(sorted_vals, 0.25)


def scale(rows: List[dict], metric: str, anchors: List[float] = (), top: Optional[float] = None) -> Optional[dict]:
    """How a count of `metric` is put on 0 to 1 for these rows (see the module note): {"median", "top", "lo", "m", "L",
    "low"}: the median, the top end and the count one lower sigma below the median, and on the log scale the median,
    the top end and the lower sigma. `top` is the landmark's count (Attention Is All You
    Need); without it, the largest count among the rows and the `anchors` (your rated papers). None when fewer than
    two rows have the measure."""
    vals = sorted(max(0.0, float(r["m"][metric])) for r in rows if (r.get("m") or {}).get(metric) is not None)
    if len(vals) < 2:
        return None
    half = len(vals) // 2
    med = vals[half] if len(vals) % 2 else math.expm1((math.log1p(vals[half - 1]) + math.log1p(vals[half])) / 2)
    if med <= 0:                                 # most papers not cited yet: the middle is the least-cited paper that
        med = min([v for v in vals if v > 0] or [0.0])   # is, so no citation stays below it
    m = math.log1p(med)
    ls = [math.log1p(v) for v in vals]
    q = _quartile(ls)
    low = (m - q) / 0.6745                       # the lower half's own spread (its quartile is 0.6745 sigma down)
    if low <= 1e-9:                              # ties down there: the spread of all of them, else the old third
        low = 1.4826 * median_([abs(v - m) for v in ls]) or m / 3 or 1.0
    known = max(vals + [max(0.0, float(a)) for a in anchors if a is not None])
    if not top or math.log1p(top) <= m:          # no landmark, or one at or below the middle (a wrong record)
        top = known
    L = math.log1p(top)
    return {"median": round(math.expm1(m), 3), "top": round(top, 3), "m": m, "L": L if L > m else None,
            "low": low, "lo": round(math.expm1(max(0.0, m - low)), 3)}


def place(v: float, sc: dict) -> float:
    """A count on 0 to 1: the median at 0.5; below it the lower half's own spread, above it the top end at +3 sigma."""
    l, m, L = math.log1p(max(0.0, v)), sc["m"], sc["L"]
    sigma = sc["low"] if (l < m or L is None) else (L - m) / 3    # nothing above the middle to hold: the lower sigma
    return 0.5 * (1 + math.erf(((l - m) / max(sigma, 1e-9)) / math.sqrt(2)))


def position(rows: List[dict], metric: str, scores: Dict[str, float], anchors: List[float] = (),
             top: Optional[float] = None) -> Dict[str, dict]:
    """Each row's attention on 0 to 1. Counts through the normal scale of `scale` and `place`: the median of these
    rows in the middle, their own spread below it, `top` (Attention Is All You Need) at +3 sigma above it. The bar: the count
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
