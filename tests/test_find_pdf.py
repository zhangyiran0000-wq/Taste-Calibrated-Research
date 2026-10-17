"""Free PDFs beyond arXiv: Semantic Scholar's open-access PDF, OpenAlex's open-access locations, and the PDF a
publisher page names (citation_pdf_url, e.g. Nature). Paywall pages are skipped."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.sources import fulltext  # noqa: E402
from tastecal.sources.fulltext import find_fulltext, ids_of, open_access_pdfs  # noqa: E402

NATURE = "https://www.nature.com/articles/s41467-026-77370-x"
NATURE_PAGE = ('<html><head><meta name="citation_doi" content="10.1038/s41467-026-77370-x">'
               '<meta name="citation_pdf_url" content="https://www.nature.com/articles/s41467-026-77370-x.pdf">'
               '</head><body>Abstract only here</body></html>')
PDF = b"%PDF-1.7 fake"


class FakeHttp:
    def __init__(self, json=None, text=None, data=None):
        self.json, self.text, self.data, self.got, self.cache = json or {}, text or {}, data or {}, [], {}

    def get_json(self, url, params=None, headers=None, **kw):
        self.got.append(url)
        for k, v in self.json.items():
            if k in url:
                return v
        raise RuntimeError("HTTP 404")

    def get_text(self, url, **kw):
        self.got.append(url)
        if url in self.text:
            return self.text[url]
        raise RuntimeError("HTTP 404")

    def get_bytes(self, url, **kw):
        self.got.append(url)
        if url in self.data:
            return self.data[url]
        raise RuntimeError("HTTP 404")

    def _cache_get(self, key):
        return self.cache.get(key)

    def _cache_put(self, key, value):
        self.cache[key] = value


class FindPdfTest(unittest.TestCase):
    def setUp(self):
        self.real = fulltext.pdf_to_text
        fulltext.pdf_to_text = lambda data: "full paper text " * 400 if data.startswith(b"%PDF") else ""

    def tearDown(self):
        fulltext.pdf_to_text = self.real

    def test_nature_page_names_its_pdf(self):
        http = FakeHttp(text={NATURE: NATURE_PAGE}, data={NATURE + ".pdf": PDF})
        node = {"id": "hugcl", "title": "Human-guided continual learning", "url": NATURE}
        text, basis, source = find_fulltext(node, None, http, papers_dir="")
        self.assertEqual((basis, source), ("full text", "publisher PDF"))
        ids = ids_of(node)
        open_access_pdfs(http, node, ids)
        self.assertEqual(ids["doi"], "10.1038/s41467-026-77370-x")              # read from the page

    def test_nature_pattern_without_the_page(self):
        http = FakeHttp(data={NATURE + ".pdf": PDF})                      # the page itself could not be read
        _, basis, source = find_fulltext({"id": "hugcl", "title": "H", "url": NATURE}, None, http, papers_dir="")
        self.assertEqual((basis, source), ("full text", "publisher PDF"))

    def test_paywall_page_is_skipped_for_the_next_link(self):
        s2 = "a" * 40
        http = FakeHttp(json={"api.semanticscholar.org": {"openAccessPdf": {"url": "https://pub.example/paywalled.pdf"},
                                                          "externalIds": {"DOI": "10.1000/xyz"}},
                              "api.openalex.org": {"best_oa_location": {"pdf_url": "https://repo.example/oa.pdf"}, "locations": []}},
                        data={"https://pub.example/paywalled.pdf": b"<html>Sign in</html>", "https://repo.example/oa.pdf": PDF})
        node = {"id": "w", "title": "W", "url": f"https://www.semanticscholar.org/paper/{s2}"}
        text, basis, source = find_fulltext(node, None, http, papers_dir="")
        self.assertEqual((basis, source), ("full text", "open-access PDF (OpenAlex)"))

    def test_nothing_free_falls_back_to_the_abstract(self):
        class Item:
            abstract, ids = "An abstract.", {"doi": "10.1109/TITS.2024.3524609"}
        http = FakeHttp(text={"https://doi.org/10.1109/TITS.2024.3524609": "<html>IEEE page, no free PDF</html>"})
        text, basis, _ = find_fulltext({"id": "x", "title": "X", "url": ""}, Item(), http, papers_dir="")
        self.assertEqual((text, basis), ("An abstract.", "abstract"))

    def test_arxiv_still_comes_first(self):
        http = FakeHttp(text={"https://arxiv.org/html/2212.10156": "<p>" + "arxiv text " * 600 + "</p>"})
        _, basis, source = find_fulltext({"id": "u", "title": "U", "url": "https://arxiv.org/abs/2212.10156"}, None, http,
                                         papers_dir="")
        self.assertEqual((basis, source), ("full text", "arXiv HTML"))
        self.assertFalse(any("openalex" in u or "doi.org" in u for u in http.got))


if __name__ == "__main__":
    unittest.main()
