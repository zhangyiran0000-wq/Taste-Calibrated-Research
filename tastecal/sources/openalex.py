"""OpenAlex: used for one thing Semantic Scholar can't do, listing a paper's
citers *sorted by their own citation count*, so influential descendants
are found even when a paper has tens of thousands of citers."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from tastecal.core.http import Http, HttpError
from tastecal.core.model import Item, title_similarity

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
    if not w or not w.get("display_name"):
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
        """Best OpenAlex work id for an item: title search, most-cited match wins
        (preprint and published versions are often split into separate records)."""
        try:
            data = self.http.get_json(BASE + "/works", params={
                "search": item.title, "per-page": 8, "sort": "cited_by_count:desc",
                "select": "id,display_name,publication_year,cited_by_count", "mailto": self.mailto})
        except HttpError as e:
            log.info("OpenAlex find failed: %s", e)
            return None
        best, best_sim = None, 0.0
        for w in data.get("results") or []:
            sim = title_similarity(item.title, w.get("display_name", ""))
            if sim > best_sim:
                best, best_sim = w, sim
        if best and best_sim >= 0.8:
            return best["id"].rsplit("/", 1)[-1]
        return None

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
