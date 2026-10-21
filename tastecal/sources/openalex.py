"""OpenAlex: used for one thing Semantic Scholar can't do, listing a paper's
citers *sorted by their own citation count*, so influential descendants
are found even when a paper has tens of thousands of citers."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from tastecal.core.http import Http, HttpError
from tastecal.core.model import Item, junk_title, title_similarity

log = logging.getLogger("tastecal.openalex")

BASE = "https://api.openalex.org"
SELECT = ("id,doi,display_name,publication_year,publication_date,cited_by_count,"
          "authorships,primary_location,abstract_inverted_index,type")


def rebuild_abstract(inv: Optional[Dict[str, List[int]]]) -> str:
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def to_item(w: Dict[str, Any]) -> Optional[Item]:
    if not w or not w.get("display_name") or junk_title(w["display_name"]):
        return None
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    ids = {"openalex": w["id"].rsplit("/", 1)[-1]}
    if doi:
        ids["doi"] = doi
        if doi.lower().startswith("10.48550/arxiv."):
            ids["arxiv"] = doi.split("arxiv.", 1)[1] if "arxiv." in doi.lower() else doi[16:]
    loc = (w.get("primary_location") or {}).get("source") or {}
    pub = w.get("publication_date") or ""
    return Item(
        id="oa:" + ids["openalex"],
        title=w["display_name"].strip(),
        kind="paper",
        year=w.get("publication_year"),
        date=pub[:7],
        authors=[(a.get("author") or {}).get("display_name", "") for a in (w.get("authorships") or [])][:12],
        venue=loc.get("display_name") or "",
        url=("https://arxiv.org/abs/" + ids["arxiv"]) if ids.get("arxiv") else (w.get("doi") or w["id"]),
        abstract=rebuild_abstract(w.get("abstract_inverted_index")),
        citations=w.get("cited_by_count"),
        ids=ids,
    )


class OpenAlex:
    def __init__(self, http: Http, mailto: str = ""):
        self.http = http
        self.mailto = mailto or None

    def find(self, item: Item) -> Optional[str]:
        """Best OpenAlex work id for an item: a title search ranked by relevance, then, among the results whose title
        matches, the most cited (preprint and published versions are often split into separate records). Ranking the
        search itself by citations would fill the first page with famous works that only share a word or two."""
        try:
            data = self.http.get_json(BASE + "/works", params={       # ? and * are wildcards there: a title with them is refused
                "search": " ".join(re.sub(r"[?*]", " ", item.title).split()), "per-page": 10,
                "select": "id,display_name,publication_year,cited_by_count", "mailto": self.mailto})
        except HttpError as e:
            log.info("OpenAlex find failed: %s", e)
            return None
        same = [(title_similarity(item.title, w.get("display_name", "")), w) for w in data.get("results") or []]
        same = [(sim, w) for sim, w in same if sim >= 0.8]
        if not same:
            return None
        best = max(same, key=lambda t: ((t[1].get("cited_by_count") or 0), t[0]))[1]
        return best["id"].rsplit("/", 1)[-1]

    def top_citing(self, work_id: str, n: int = 50, from_year: Optional[int] = None) -> List[Item]:
        flt = f"cites:{work_id}"
        if from_year:
            flt += f",from_publication_date:{from_year}-01-01"
        try:
            data = self.http.get_json(BASE + "/works", params={
                "filter": flt, "sort": "cited_by_count:desc", "per-page": min(n, 200),
                "select": SELECT, "mailto": self.mailto})
        except HttpError as e:
            log.info("OpenAlex citing failed: %s", e)
            return []
        return [i for i in (to_item(w) for w in data.get("results") or []) if i]

    def percentile(self, work_id: str) -> Optional[dict]:
        """OpenAlex's citation percentile among works of the same field and publication year:
        {"value": 0..1, "is_in_top_10_percent": bool, ...}, or None."""
        try:
            data = self.http.get_json(f"{BASE}/works/{work_id}", params={
                "select": "id,citation_normalized_percentile,cited_by_count", "mailto": self.mailto})
        except HttpError as e:
            log.info("OpenAlex percentile failed: %s", e)
            return None
        got = data.get("citation_normalized_percentile") if isinstance(data, dict) else None
        return got if isinstance(got, dict) else None

    def attention(self, work_id: str) -> Optional[dict]:
        """Counts for the taste fit: {"pct": percentile among works of the same subfield, type and year, "top10",
        "cited_by", "by_year": {"2025": n, ...}, "pub": "YYYY-MM-DD"}, or None."""
        try:
            data = self.http.get_json(f"{BASE}/works/{work_id}", params={
                "select": "id,citation_normalized_percentile,cited_by_count,counts_by_year,publication_date",
                "mailto": self.mailto})
        except HttpError as e:
            log.info("OpenAlex attention failed: %s", e)
            return None
        if not isinstance(data, dict):
            return None
        pct = data.get("citation_normalized_percentile") or {}
        return {"pct": pct.get("value") if isinstance(pct, dict) else None,
                "top10": bool(pct.get("is_in_top_10_percent")) if isinstance(pct, dict) else False,
                "cited_by": data.get("cited_by_count"),
                "by_year": {str(r.get("year")): r.get("cited_by_count", 0) for r in data.get("counts_by_year") or []
                            if isinstance(r, dict) and r.get("year")},
                "pub": data.get("publication_date") or ""}

    def abstract(self, item: Item) -> str:
        """The work's abstract from OpenAlex (by DOI, else by title), or "" when it has none."""
        doi = (item.ids or {}).get("doi")
        try:
            if doi:
                w = self.http.get_json(f"{BASE}/works/doi:{doi}", params={"select": "id,abstract_inverted_index",
                                                                          "mailto": self.mailto})
            else:
                wid = (item.ids or {}).get("openalex") or self.find(item)
                if not wid:
                    return ""
                w = self.http.get_json(f"{BASE}/works/{wid}", params={"select": "id,abstract_inverted_index",
                                                                      "mailto": self.mailto})
        except HttpError as e:
            log.info("OpenAlex abstract failed for %s: %s", item.title[:60], e)
            return ""
        return rebuild_abstract((w or {}).get("abstract_inverted_index")) if isinstance(w, dict) else ""

