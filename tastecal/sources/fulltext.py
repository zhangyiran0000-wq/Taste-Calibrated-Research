"""Find a paper's full text, in this order:

  1. a file you put in the papers folder (default ./papers): PDF, TXT, MD or HTML, named after the
     node id, the arXiv id, the DOI (with "/" replaced by "_") or the start of the title
  2. arXiv: the HTML version, then the PDF
  3. a free PDF from elsewhere: the open-access PDF Semantic Scholar knows of, the open-access locations OpenAlex
     lists, and the PDF the publisher's own page names in its citation_pdf_url tag (Nature, Springer, MDPI, ACM,
     OpenReview and most others). Only links that really return a PDF count, so a paywall page is skipped.
  4. a legal open-access copy found through Unpaywall (needs an e-mail address: UNPAYWALL_EMAIL or OPENALEX_MAILTO)
  5. the abstract, then the work's card

Returns (text, basis, source). `basis` is "full text", "abstract" or "card"; anything short of full text
is shown as "not verified" in the report and is never folded.

PDFs are turned into text with the `pdftotext` command (poppler) when it is installed, or with the
`pypdf` package when that is importable. Neither is required: without them PDFs are skipped.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple
from urllib.parse import quote, urljoin

log = logging.getLogger("tastecal.fulltext")

FULL_TEXT_MIN = 4000
_WARNED = False


def pdf_reader() -> str:
    """Which PDF reader is available: "pdftotext", "pypdf" or ""."""
    if shutil.which("pdftotext"):
        return "pdftotext"
    try:
        import pypdf  # type: ignore  # noqa: F401
        return "pypdf"
    except ImportError:
        return ""
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", re.I)
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>?#]+)", re.I)
S2_RE = re.compile(r"semanticscholar\.org/paper/(?:[^/]+/)?([0-9a-f]{40})", re.I)
PDF_META = re.compile(r"<meta\b[^>]*\b(?:name|property)\s*=\s*[\"'](?:citation_pdf_url|eprints\.document_url)[\"'][^>]*>", re.I)
DOI_META = re.compile(r"<meta\b[^>]*\bname\s*=\s*[\"'](?:citation_doi|dc\.identifier|prism\.doi)[\"'][^>]*>", re.I)
CONTENT = re.compile(r"\bcontent\s*=\s*[\"']([^\"']+)[\"']", re.I)
EXTS = (".pdf", ".txt", ".md", ".html", ".htm")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def ids_of(node: dict, item=None) -> dict:
    ids = dict(node.get("ids") or {})
    ids.update(getattr(item, "ids", None) or {})
    url = node.get("url") or ""
    if not ids.get("arxiv"):
        m = ARXIV_RE.search(url)
        if m:
            ids["arxiv"] = m.group(1)
    if not ids.get("doi"):
        m = DOI_RE.search(url)
        if m:
            ids["doi"] = m.group(1).rstrip(".")
    if not ids.get("s2"):
        m = S2_RE.search(url)
        if m:
            ids["s2"] = m.group(1)
    return ids


def _metas(html: str, rx) -> List[str]:
    out = []
    for m in rx.finditer(html or ""):
        c = CONTENT.search(m.group(0))
        if c:
            out.append(c.group(1).replace("&amp;", "&").strip())
    return out


def _quiet(http, url: str, **kw):
    """One lookup that may fail without slowing the run much (few retries)."""
    try:
        return http.get_json(url, retries=1, **kw)
    except Exception as e:  # offline, rate-limited, not found
        log.info("lookup failed: %s (%s)", url[:100], str(e)[:120])
        return None


def open_access_pdfs(http, node: dict, ids: dict) -> List[Tuple[str, str]]:
    """Free PDF links for a work, best first, as (url, where it came from). Fills ids["doi"] when a lookup finds it."""
    found: List[Tuple[str, str]] = []
    if ids.get("s2"):
        from tastecal.core.config import clean_secret, env_value
        key = clean_secret(env_value("S2_API_KEY"))
        d = _quiet(http, f"https://api.semanticscholar.org/graph/v1/paper/{ids['s2']}",
                   params={"fields": "externalIds,openAccessPdf"}, headers={"x-api-key": key} if key else None) or {}
        pdf = (d.get("openAccessPdf") or {}).get("url") if isinstance(d, dict) else None
        if pdf:
            found.append((pdf, "open-access PDF (Semantic Scholar)"))
        if isinstance(d, dict) and not ids.get("doi") and (d.get("externalIds") or {}).get("DOI"):
            ids["doi"] = d["externalIds"]["DOI"]
    pages = []
    url = node.get("url") or ""
    if url.startswith("http") and not re.search(r"arxiv\.org|semanticscholar\.org|doi\.org/", url, re.I):
        pages.append(url)                       # a publisher page given directly, e.g. nature.com/articles/...
    if ids.get("doi"):
        w = _quiet(http, f"https://api.openalex.org/works/doi:{quote(ids['doi'], safe='/')}",
                   params={"select": "best_oa_location,locations"}) or {}
        for loc in ([w.get("best_oa_location") or {}] + list(w.get("locations") or [])) if isinstance(w, dict) else []:
            if isinstance(loc, dict) and loc.get("pdf_url"):
                found.append((loc["pdf_url"], "open-access PDF (OpenAlex)"))
        pages.append(f"https://doi.org/{ids['doi']}")
    for page in pages:
        try:
            html = http.get_text(page)
        except Exception as e:
            log.info("publisher page unavailable: %s (%s)", page[:100], str(e)[:120])
            continue
        found += [(urljoin(page, u), "publisher PDF") for u in _metas(html, PDF_META)]
        if not ids.get("doi"):
            for d in _metas(html, DOI_META):
                m = DOI_RE.search(d)
                if m:
                    ids["doi"] = m.group(1).rstrip(".")
                    break
    # Known publisher patterns, in case a page could not be read: Nature journals, then Springer.
    doi = ids.get("doi") or ""
    m = re.match(r"https?://www\.nature\.com/articles/([^/?#.]+)", url)
    if doi.lower().startswith("10.1038/") or m:
        found.append((f"https://www.nature.com/articles/{m.group(1) if m else doi.split('/', 1)[1]}.pdf", "publisher PDF"))
    if doi.lower().startswith("10.1007/"):
        found.append((f"https://link.springer.com/content/pdf/{doi}.pdf", "publisher PDF"))
    seen, out = set(), []
    for u, where in found:
        if u.startswith("http") and u not in seen:
            seen.add(u)
            out.append((u, where))
    return out


def pdf_to_text(data: bytes) -> str:
    """Text of a PDF, or "" when no extractor is available."""
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            out = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=120)
            return out.stdout.decode("utf-8", "replace")
        except Exception as e:  # broken PDF
            log.info("pdftotext failed: %s", e)
        finally:
            os.unlink(path)
    try:
        import io

        import pypdf  # type: ignore
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except ImportError:
        global _WARNED
        if not _WARNED:
            _WARNED = True
            log.warning("No PDF reader, so PDFs are skipped and those papers are read from the abstract. Install one: "
                        + ("pip install pypdf" if os.name == "nt" else "brew install poppler (or pip install pypdf)") + ".")
    except Exception as e:
        log.info("pypdf failed: %s", e)
    return ""


def papers_folder(papers_dir: str = "papers") -> str:
    """The papers folder: as given, or, for a relative path that is not in the current folder, the same name next to
    the tastecal package (the project folder), so a run started from another folder still finds your PDFs."""
    if not papers_dir or os.path.isabs(papers_dir) or os.path.isdir(papers_dir):
        return papers_dir
    near = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), papers_dir)
    return near if os.path.isdir(near) else papers_dir


def local_file(node: dict, item=None, papers_dir: str = "papers") -> Optional[str]:
    """Path of a file in the papers folder that belongs to this work."""
    papers_dir = papers_folder(papers_dir)
    if not papers_dir or not os.path.isdir(papers_dir):
        return None
    ids = ids_of(node, item)
    keys = [_norm(node.get("id", ""))]
    if ids.get("arxiv"):
        keys.append(_norm(ids["arxiv"]))
    if ids.get("doi"):
        keys.append(_norm(ids["doi"].replace("/", "_")))
    title = _norm(" ".join((node.get("title") or "").split()[:6]))
    for name in sorted(os.listdir(papers_dir)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in EXTS:
            continue
        s = _norm(stem)
        if not s:
            continue
        if s == keys[0] or any(k and len(k) >= 6 and k in s for k in keys[1:]) or (len(title) >= 12 and s.startswith(title[:30])):
            return os.path.join(papers_dir, name)
    return None


def suggested_name(node: dict, item=None) -> str:
    """A file name `local_file` will match for this work: the DOI with / as _, else the arXiv id, else the start
    of the title."""
    ids = ids_of(node, item)
    if ids.get("doi"):
        return ids["doi"].replace("/", "_") + ".pdf"
    if ids.get("arxiv"):
        return ids["arxiv"] + ".pdf"
    words = re.sub(r"[^\w\s-]", "", node.get("title") or getattr(item, "title", "") or "").split()[:6]
    return (" ".join(words) or node.get("id") or "paper") + ".pdf"


END_HEADS = re.compile(r"\n\s*(?:\d+(?:\.\d+)*\.?\s*|[IVX]+\.\s*)?(conclusions?|limitations?|discussion|future work)\b[^\n.]{0,40}\n",
                       re.I)
REFS = re.compile(r"\n\s*(?:references|bibliography|appendix\b[^\n]{0,60}|acknowledge?ments?)\s*\n", re.I)


READ_LIMIT = 64000
REFS_ONLY = re.compile(r"\n\s*(?:\d+\.?\s*)?(?:references|bibliography|参考文献)\s*\n", re.I)
APPENDIX_HEAD = re.compile(r"\n\s*(?:appendix\b[^\n]{0,60}|appendices|supplementary(?: material)?\b[^\n]{0,40})\s*\n", re.I)
RELATED_HEAD = re.compile(r"\n\s*(?:\d+(?:\.\d+)*\.?\s*|[IVX]+\.\s*)?(?:related works?|background|literature review|prior work)\b[^\n]{0,40}\n",
                          re.I)
# A numbered reference list: "[1] ..." followed within a few lines by "[2] ..." (one in-text "[1]" at the start
# of a wrapped line is not enough).
REF_LIST = re.compile(r"\n\s*\[1\]\s[^\n]*\n(?:[^\n]*\n){0,6}?\s*\[2\]\s")
NUMBERED_HEAD = re.compile(r"\n\s*(?:\d+\.?|[IVX]+\.)\s+[A-Z][^\n]{2,70}\n")


def select_for_reading(text: str, limit: int = READ_LIMIT) -> Tuple[str, dict]:
    """The part of a paper's full text a reader gets, and how much of the main text it covers.

    A plain cut at `limit` characters loses the experiments and results, which come last. Instead: the reference list
    is dropped; if the main text is well over the limit, the related-work section goes, then the middle (the start, with
    the abstract, introduction and method, and the end, with the experiments, results and conclusion, are kept); the
    appendix is added back while room is left. Omitted parts are marked in the text so the reader knows they exist.

    coverage: {"chars": all characters, "main_chars": the main text before references and appendix,
               "main_coverage": share of the main text read (0-1), "omitted": [what was left out]}."""
    text = text or ""
    omitted: List[str] = []
    # The last reference heading in the back three quarters (a heading named "References" can also open the paper's
    # own discussion of related work, but the list itself comes late).
    refs = next(reversed([m for m in REFS_ONLY.finditer(text) if m.start() > len(text) * 0.25]), None)
    if refs is None:
        # No heading found (PDF text often loses it): a numbered reference list starting in the back half.
        refs = REF_LIST.search(text, int(len(text) * 0.25))
    if refs:
        main, rest = text[:refs.start()], text[refs.end():]
        app = APPENDIX_HEAD.search(rest)
        appendix = rest[app.start():] if app else ""
        omitted.append("references")
    else:
        app = APPENDIX_HEAD.search(text, int(len(text) * 0.5))
        main, appendix = (text[:app.start()], text[app.start():]) if app else (text, "")
    main_len = len(main)
    lost = 0
    body = main
    # A small overflow costs only a slice of the middle; a large one first drops the related-work section.
    if len(body) > limit * 1.15:
        m = RELATED_HEAD.search(body)
        if m and m.start() < len(body) * 0.5:
            nxt = NUMBERED_HEAD.search(body, m.end() + 200)
            if nxt and nxt.start() - m.start() < len(body) * 0.35:
                lost += nxt.start() - m.start()
                body = body[:m.start()] + "\n[... related-work section omitted ...]\n" + body[nxt.start():]
                omitted.append("related work")
    if len(body) > limit:
        head = int(limit * 0.35)
        tail = limit - head
        cut = len(body) - head - tail
        lost += cut
        body = body[:head] + f"\n[... {cut} characters from the middle omitted ...]\n" + body[-tail:]
        omitted.append("middle of the main text")
    if appendix:
        room = limit - len(body)
        if room > 2000:
            body += "\n\n[Appendix]\n" + appendix[:room]
            if len(appendix) > room:
                omitted.append("part of the appendix")
        else:
            omitted.append("appendix")
    cov = round(1 - lost / main_len, 2) if main_len else 1.0
    return body, {"chars": len(text), "main_chars": main_len, "main_coverage": cov, "omitted": omitted}


def coverage_note(cov: Optional[dict]) -> str:
    """One line for the prompt: what part of the paper the reader sees."""
    if not cov:
        return ""
    pct = int(round(100 * cov.get("main_coverage", 1.0)))
    left = ", ".join(cov.get("omitted") or []) or "nothing"
    return (f"You see {pct}% of the main text. Left out: {left}. Do not report something as missing or untested if it "
            f"may sit in a part that was left out; say it was not in the text you have.")


def card_excerpt(text: str, head: int = 4500, tail: int = 2800) -> str:
    """Abstract and introduction, plus the limitations and conclusion sections: enough for a card and its open
    problems, without the whole paper. The appendix and references are left out."""
    text = text or ""
    refs = REFS.search(text, len(text) // 2)
    body = text[:refs.start()] if refs else text
    if len(body) <= head + tail:
        return body
    heads = [m for m in END_HEADS.finditer(body) if m.start() > head]
    if not heads:
        return body[:head] + "\n[...]\n" + body[-tail:]
    lim = next((m for m in heads if m.group(1).lower().startswith(("limitation", "future"))), None)
    con = [m for m in heads if m.group(1).lower().startswith(("conclusion", "discussion"))]
    con = con[-1] if con else None
    parts = []
    if lim and con and lim.start() < con.start():
        parts = [body[lim.start():con.start()][:tail // 2], body[con.start():][:tail // 2]]
    else:
        m = lim or con
        parts = [body[m.start():][:tail]]
    return body[:head] + "".join("\n[...]\n" + x for x in parts)


def read_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        with open(path, "rb") as f:
            return pdf_to_text(f.read())
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    if ext in (".html", ".htm"):
        from tastecal.sources.web import html_to_text
        return html_to_text(raw, max_chars=None)[2]
    return raw


def _pdf_from_url(http, url: str) -> str:
    key = "PDFTEXT " + url
    hit = http._cache_get(key)
    if hit is not None:
        return hit
    data = http.get_bytes(url)
    if not data.lstrip()[:5] == b"%PDF-":      # a login or paywall page, not the paper
        log.info("not a PDF (probably behind a paywall): %s", url[:120])
        return ""
    text = pdf_to_text(data)
    if text:
        http._cache_put(key, text)
    return text


def find_fulltext(node: dict, item=None, http=None, papers_dir: str = "papers", email: str = "",
                  min_chars: int = FULL_TEXT_MIN) -> Tuple[str, str, str]:
    path = local_file(node, item, papers_dir)
    if path:
        text = read_file(path)
        if len(text) >= min_chars:
            return text, "full text", "local file"
        log.info("local file for %s is too short or unreadable: %s", node.get("id"), path)
    ids = ids_of(node, item)
    if http is not None and ids.get("arxiv"):
        from tastecal.sources.web import html_to_text
        aid = ids["arxiv"]
        try:
            text = html_to_text(http.get_text(f"https://arxiv.org/html/{aid}"), max_chars=None)[2]
            if text and len(text) >= min_chars:
                return text, "full text", "arXiv HTML"
        except Exception as e:
            log.info("no arXiv HTML for %s: %s", aid, e)
        try:
            text = _pdf_from_url(http, f"https://arxiv.org/pdf/{aid}")
            if len(text) >= min_chars:
                return text, "full text", "arXiv PDF"
        except Exception as e:
            log.info("no arXiv PDF for %s: %s", aid, e)
    if http is not None:
        for url, where in open_access_pdfs(http, node, ids)[:5]:
            try:
                text = _pdf_from_url(http, url)
            except Exception as e:
                log.info("could not fetch %s: %s", url[:120], str(e)[:120])
                continue
            if len(text) >= min_chars:
                return text, "full text", where
    email = email or os.environ.get("UNPAYWALL_EMAIL") or os.environ.get("OPENALEX_MAILTO", "")
    if http is not None and ids.get("doi") and email:
        try:
            data = http.get_json(f"https://api.unpaywall.org/v2/{ids['doi']}", params={"email": email})
            loc = (data or {}).get("best_oa_location") or {}
            if loc.get("url_for_pdf"):
                text = _pdf_from_url(http, loc["url_for_pdf"])
                if len(text) >= min_chars:
                    return text, "full text", "open-access copy (Unpaywall)"
            if loc.get("url_for_landing_page"):
                from tastecal.sources.web import html_to_text
                text = html_to_text(http.get_text(loc["url_for_landing_page"]), max_chars=None)[2]
                if len(text) >= min_chars:
                    return text, "full text", "open-access copy (Unpaywall)"
        except Exception as e:
            log.info("Unpaywall found nothing for %s: %s", ids["doi"], e)
    abstract = getattr(item, "abstract", "") if item is not None else ""
    if abstract:
        return abstract, "abstract", "abstract only"
    c = node.get("card") or {}
    card = f"Starts from: {c.get('inherits', '')}\nMove: {c.get('move', '')}\nInsight: {c.get('insight', '')}"
    return card, "card", "summary card only"


META_ABSTRACT = re.compile(
    r'<meta\s+[^>]*?(?:name|property)\s*=\s*["\'](citation_abstract|dc\.description|dcterms\.abstract|'
    r'og:description|twitter:description|description)["\'][^>]*?content\s*=\s*["\']([^"\']{80,})["\']', re.I | re.S)
META_ABSTRACT_REV = re.compile(
    r'<meta\s+[^>]*?content\s*=\s*["\']([^"\']{80,})["\'][^>]*?(?:name|property)\s*=\s*["\'](citation_abstract|'
    r'dc\.description|dcterms\.abstract|og:description|twitter:description|description)["\']', re.I | re.S)
META_RANK = {"citation_abstract": 0, "dcterms.abstract": 1, "dc.description": 2, "og:description": 3,
             "twitter:description": 4, "description": 5}


def page_abstract(http, url: str) -> str:
    """The abstract a publisher's landing page declares in its meta tags (citation_abstract, Dublin Core, Open Graph).
    Many pages that hide the full text still carry the abstract there. "" when none is found or the page is blocked."""
    import html as _html
    if not (http and url):
        return ""
    try:
        page = http.get_text(url, max_bytes=600_000)
    except Exception as e:  # blocked, offline
        log.info("no landing page for %s: %s", url[:100], e)
        return ""
    found = [(m.group(1).lower(), m.group(2)) for m in META_ABSTRACT.finditer(page or "")]
    found += [(m.group(2).lower(), m.group(1)) for m in META_ABSTRACT_REV.finditer(page or "")]
    if not found:
        return ""
    found.sort(key=lambda kv: (META_RANK.get(kv[0], 9), -len(kv[1])))
    text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", found[0][1]))).strip()
    return text if len(text) >= 200 else ""


def fill_abstract(item, http=None, openalex=None) -> str:
    """Give an item without an abstract one, from OpenAlex and then the publisher's landing page. Sets item.abstract
    and returns where it came from ("" when nothing was found). Items that already have an abstract are left as is."""
    if item is None or getattr(item, "abstract", "") or getattr(item, "kind", "paper") != "paper":
        return ""
    if openalex is not None:
        text = openalex.abstract(item)
        if len(text or "") >= 200:
            item.abstract = text
            return "OpenAlex"
    ids = getattr(item, "ids", {}) or {}
    for url in ([f"https://doi.org/{ids['doi']}"] if ids.get("doi") else []) + ([item.url] if getattr(item, "url", "") else []):
        text = page_abstract(http, url)
        if text:
            item.abstract = text
            return "publisher page"
    return ""

