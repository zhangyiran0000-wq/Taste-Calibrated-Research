"""Blog / technical-report discovery through a web search API (Tavily or Brave),
plus a small HTML-to-text extractor so the LLM can read the page."""
from __future__ import annotations

import hashlib
import logging
import re
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

from tastecal.core.http import Http, HttpError
from tastecal.core.model import Item
from tastecal.sources import WebSource

log = logging.getLogger("tastecal.web")

# Paper hosts are covered by the scholarly sources; skip them here.
PAPER_HOSTS = ("arxiv.org", "semanticscholar.org", "openreview.net", "aclanthology.org",
               "scholar.google", "dl.acm.org", "ieeexplore.ieee.org", "proceedings.",
               "researchgate.net", "paperswithcode.com", "openalex.org", "doi.org")


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self.published = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in ("article:published_time", "og:published_time", "date", "datepublished",
                        "publish-date", "parsely-pub-date") and a.get("content") and not self.published:
                self.published = a["content"]
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "pre", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str, max_chars: int = 9000):
    p = _Text()
    try:
        p.feed(html)
    except Exception:  # malformed pages: keep whatever was parsed
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), p.published[:10], text[:max_chars]


def is_paper_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(h in host for h in PAPER_HOSTS)


class WebSearch(WebSource):
    def __init__(self, http: Http, tavily_key: str = "", brave_key: str = ""):
        self.http = http
        self.tavily_key = tavily_key
        self.brave_key = brave_key
        self.available = bool(tavily_key or brave_key)

    def _results(self, query: str, limit: int):
        if self.tavily_key:
            data = self.http.post_json("https://api.tavily.com/search",
                                       {"query": query, "max_results": limit, "search_depth": "basic"},
                                       headers={"Authorization": f"Bearer {self.tavily_key}"})
            for r in data.get("results") or []:
                yield r.get("title", ""), r.get("url", ""), r.get("content", ""), r.get("published_date", "")
        elif self.brave_key:
            data = self.http.get_json(f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={limit}",
                                      headers={"X-Subscription-Token": self.brave_key})
            for r in (data.get("web") or {}).get("results") or []:
                yield r.get("title", ""), r.get("url", ""), r.get("description", ""), r.get("page_age", "")

    def search(self, query: str, limit: int = 6) -> List[Item]:
        if not self.available:
            return []
        items: List[Item] = []
        try:
            results = list(self._results(query, limit))
        except HttpError as e:
            log.warning("web search failed for %r: %s", query, e)
            return []
        for title, url, snippet, published in results:
            if not url or is_paper_host(url):
                continue
            item = self.fetch(url, title, snippet, published)
            if item:
                items.append(item)
        return items

    def fetch(self, url: str, title: str = "", snippet: str = "", published: str = "") -> Optional[Item]:
        try:
            html = self.http.get_text(url)
        except HttpError as e:
            log.info("could not fetch %s: %s", url, e)
            text, page_title, meta_date = snippet, title, ""
        else:
            page_title, meta_date, text = html_to_text(html)
        date = (published or meta_date or "")[:10]
        year = int(date[:4]) if date[:4].isdigit() else None
        host = urlparse(url).netloc.replace("www.", "")
        return Item(
            id="web:" + hashlib.sha1(url.encode()).hexdigest()[:12],
            title=(title or page_title or url).strip(),
            kind="blog",
            year=year,
            date=date[:7],
            authors=[],
            venue=host,
            url=url,
            abstract=text or snippet,
            ids={"url": url},
        )
