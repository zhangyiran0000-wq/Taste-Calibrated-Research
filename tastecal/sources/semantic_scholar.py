"""Semantic Scholar Graph API: metadata, references and citations *with the
sentences in which one paper cites another* (contexts) and coarse intents."""
from __future__ import annotations

import logging
import math
import re
import unicodedata
import urllib.parse
from datetime import date
from typing import Any, Dict, List, Optional

from tastecal.core.http import Http, HttpError
from tastecal.core.model import Candidate, Item
from tastecal.sources import Source, cue_score

log = logging.getLogger("tastecal.s2")

BASE = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = ("paperId,externalIds,title,abstract,year,publicationDate,venue,"
                "citationCount,influentialCitationCount,authors,url")
LINK_FIELDS = "contexts,intents,isInfluential," + PAPER_FIELDS

ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
# Pages that name a paper by its arXiv id: arXiv itself, its mirrors and readers.
ARXIV_HOSTS = ("arxiv.org", "alphaxiv.org", "ar5iv.org", "huggingface.co/papers", "papers.cool/arxiv",
               "scholar.archive.org", "semanticscholar.org/arxiv")
_PAIRS = (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"), ("《", "》"), ("〈", "〉"), ("「", "」"), ("『", "』"),
          ("【", "】"), ("<", ">"), ("„", "“"), ("«", "»"))
_INNER = str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"', "‘": "'", "’": "'", "‚": "'", "‛": "'"})


def clean_seed(ref: str) -> str:
    """A seed as people paste it, made plain. Full-width letters, digits, colons and slashes (Chinese input)
    become ASCII (Unicode NFKC); invisible characters go; runs of spaces become one; quotes or 《》 around
    a title, and a stray full stop or comma after a link, are dropped; curly quotes inside a title become
    straight ones. Chinese and other scripts in a title are kept as they are."""
    r = unicodedata.normalize("NFKC", str(ref or ""))
    r = "".join(c for c in r if unicodedata.category(c) not in ("Cf", "Cc") or c in "\t\n")
    r = " ".join(r.split())
    changed = True
    while changed and len(r) > 2:
        changed = False
        r = r.strip().rstrip("。，、；：")
        for a, b in _PAIRS:
            if r.startswith(a) and r.endswith(b):
                r, changed = r[len(a):len(r) - len(b)].strip(), True
    r = r.translate(_INNER)
    if re.match(r"(?i)^(https?://|www\.|[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}/)\S*$", r):
        r = r.rstrip(".,;:!?)]}>'\"")          # a link pasted at the end of a sentence
        if not r.lower().startswith("http"):
            r = "https://" + r
    return r


def _path(pid: str) -> str:
    """A paper id for the URL path: non-ASCII letters, spaces and ?#"<>{}|\\^` are percent-encoded."""
    return urllib.parse.quote(pid, safe=":/;()[]@!$&'*+,=%-._~")


def normalise_ref(ref: str) -> Optional[str]:
    """Turn a user-supplied seed into an S2 paper id, or None for a title."""
    r = clean_seed(ref)
    low = r.lower()
    if low.startswith(("arxiv:", "doi:", "corpusid:", "s2:", "url:", "pmid:", "acl:")):
        if low.startswith("s2:"):
            return r[3:]
        return r
    if low.startswith("http"):
        m = ARXIV_RE.search(r)
        if m and any(h in low for h in ARXIV_HOSTS):
            return "arXiv:" + m.group(1)
        if "doi.org/" in low:
            return "DOI:" + urllib.parse.unquote(r.split("doi.org/", 1)[1])
        return "URL:" + r
    if ARXIV_RE.fullmatch(r):
        return "arXiv:" + ARXIV_RE.fullmatch(r).group(1)
    if r.startswith("10.") and "/" in r:
        return "DOI:" + r
    if re.fullmatch(r"[0-9a-f]{40}", r):
        return r
    return None


def to_item(p: Dict[str, Any]) -> Optional[Item]:
    if not p or not p.get("paperId") or not p.get("title"):
        return None
    ext = p.get("externalIds") or {}
    arxiv = ext.get("ArXiv")
    url = f"https://arxiv.org/abs/{arxiv}" if arxiv else (p.get("url") or "")
    pub = p.get("publicationDate") or ""
    year = p.get("year")
    ids = {"s2": p["paperId"]}
    if arxiv:
        ids["arxiv"] = arxiv
    if ext.get("DOI"):
        ids["doi"] = ext["DOI"]
    return Item(
        id="s2:" + p["paperId"],
        title=p["title"].strip(),
        kind="paper",
        year=year,
        date=pub[:7] if pub else (str(year) if year else ""),
        authors=[a.get("name", "") for a in (p.get("authors") or []) if a.get("name")],
        venue=p.get("venue") or "",
        url=url,
        abstract=(p.get("abstract") or "").strip(),
        citations=p.get("citationCount"),
        ids=ids,
    )


def influence(item: Item) -> float:
    """Citations normalised by age, squashed to roughly 0..1."""
    if not item.citations:
        return 0.0
    age = max(1, date.today().year - (item.year or date.today().year) + 1)
    return min(1.0, math.log1p(item.citations / age) / math.log1p(500))


class SemanticScholar(Source):
    def __init__(self, http: Http, api_key: str = "", max_citations_scan: int = 1000,
                 popularity_weight: float = 0.5):
        self.http = http
        self.popularity_weight = popularity_weight
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.max_citations_scan = max_citations_scan

    def _get(self, path: str, **params: Any) -> Any:
        return self.http.get_json(BASE + path, params=params, headers=self.headers)

    # ----------------------------------------------------------------------
    def resolve(self, ref: str) -> Item:
        pid = normalise_ref(ref)
        if pid is None:
            item = self._by_title(clean_seed(ref))
        else:
            item = to_item(self._get("/paper/" + _path(pid), fields=PAPER_FIELDS))
        if item is None:
            raise LookupError(f"Could not resolve {ref!r}")
        return item

    def _by_title(self, title: str) -> Item:
        """Exact title match, then the best search hit, then OpenAlex (which also knows many Chinese titles) for a
        DOI or arXiv id that Semantic Scholar can look up."""
        # "Not found", or (when resuming) not among the earlier run's downloads: try the next way.
        missing = lambda e: e.status in (400, 404) or self.http.replay  # noqa: E731
        try:
            rows = (self._get("/paper/search/match", query=title, fields=PAPER_FIELDS).get("data") or [])
        except HttpError as e:
            if not missing(e):
                raise
            rows = []
        if not rows:
            try:
                rows = self._get("/paper/search", query=title, fields=PAPER_FIELDS, limit=1).get("data") or []
            except HttpError as e:
                if not missing(e):
                    raise
                rows = []
            if rows:
                log.info("no exact title match for %r; using the closest: %r", title, rows[0].get("title"))
        item = to_item(rows[0]) if rows else None
        if item is None:
            item = self._via_openalex(title)
        if item is None:
            raise LookupError(f"No paper matches the title {title!r}. For a paper whose title is not in English, "
                              "give its arXiv link, DOI or English title instead.")
        return item

    def _via_openalex(self, title: str) -> Optional[Item]:
        try:
            data = self.http.get_json("https://api.openalex.org/works",
                                      params={"search": title, "per-page": 1, "select": "id,doi,title,ids"})
        except HttpError as e:
            log.info("OpenAlex title search failed for %r: %s", title, e)
            return None
        for w in data.get("results") or []:
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            for pid in ([f"DOI:{doi}"] if doi else []):
                try:
                    item = to_item(self._get("/paper/" + _path(pid), fields=PAPER_FIELDS))
                except HttpError:
                    item = None
                if item:
                    log.info("found %r through OpenAlex (%s)", w.get("title"), pid)
                    return item
        return None

    def by_id(self, pid: str) -> Optional[Item]:
        try:
            return to_item(self._get("/paper/" + pid, fields=PAPER_FIELDS))
        except HttpError as e:
            log.info("lookup failed for %s: %s", pid, e)
            return None

    def _paged(self, path: str, key: str, cap: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        offset = 0
        while offset < cap:
            limit = min(1000, cap - offset)
            try:
                data = self._get(path, fields=LINK_FIELDS, limit=limit, offset=offset)
            except HttpError as e:
                log.warning("S2 %s failed at offset %d: %s", path, offset, e)
                break
            rows = data.get("data") or []
            out.extend(r for r in rows if r.get(key))
            if "next" not in data or not rows:
                break
            offset = data["next"]
        return out

    def backward(self, item: Item, anchor_id: str) -> List[Candidate]:
        pid = item.ids.get("s2")
        if not pid:
            return []
        rows = self._paged(f"/paper/{pid}/references", "citedPaper", 1000)
        cands = []
        for r in rows:
            it = to_item(r["citedPaper"])
            if not it:
                continue
            c = Candidate(item=it, anchor_id=anchor_id, direction="backward",
                          contexts=[s.strip() for s in (r.get("contexts") or []) if s][:4],
                          intents=r.get("intents") or [], influential=bool(r.get("isInfluential")))
            # Backward: what matters is how the *seed* talks about the reference.
            c.prior = cue_score(c.contexts) + (1.0 if c.influential else 0.0) \
                + 0.5 * len(c.contexts) ** 0.5 + influence(it)
            cands.append(c)
        return cands

    def forward(self, item: Item, anchor_id: str) -> List[Candidate]:
        pid = item.ids.get("s2")
        if not pid:
            return []
        rows = self._paged(f"/paper/{pid}/citations", "citingPaper", self.max_citations_scan)
        cands = []
        for r in rows:
            it = to_item(r["citingPaper"])
            if not it:
                continue
            c = Candidate(item=it, anchor_id=anchor_id, direction="forward",
                          contexts=[s.strip() for s in (r.get("contexts") or []) if s][:4],
                          intents=r.get("intents") or [], influential=bool(r.get("isInfluential")))
            # 2.0 x influence at the default popularity weight of 0.5
            c.prior = cue_score(c.contexts) + (1.0 if c.influential else 0.0) + 4.0 * self.popularity_weight * influence(it)
            cands.append(c)
        return cands

    def search(self, query: str, year_from: Optional[int], limit: int = 15,
               year_to: Optional[int] = None) -> List[Item]:
        years = f"{year_from or ''}-{year_to or ''}" if (year_from or year_to) else None
        try:
            data = self._get("/paper/search", query=query, fields=PAPER_FIELDS, limit=limit, year=years)
        except HttpError as e:
            log.warning("S2 search failed for %r: %s", query, e)
            return []
        return [i for i in (to_item(p) for p in data.get("data") or []) if i]

    def citation_context(self, citing: Item, cited: Item) -> Optional[Candidate]:
        """Find the sentences in `citing` that mention `cited` (one API call)."""
        cpid, tpid = citing.ids.get("s2"), cited.ids.get("s2")
        if not cpid or not tpid:
            return None
        try:
            data = self._get(f"/paper/{cpid}/references", fields="contexts,intents,isInfluential,paperId", limit=1000)
        except HttpError:
            return None
        for r in data.get("data") or []:
            if (r.get("citedPaper") or {}).get("paperId") == tpid:
                return Candidate(item=citing, anchor_id="", direction="forward",
                                 contexts=[s for s in (r.get("contexts") or []) if s][:4],
                                 intents=r.get("intents") or [], influential=bool(r.get("isInfluential")))
        return None

    def match_title(self, title: str) -> Optional[Item]:
        try:
            data = self._get("/paper/search/match", query=title, fields=PAPER_FIELDS)
        except HttpError:
            return None
        rows = data.get("data") or []
        return to_item(rows[0]) if rows else None
