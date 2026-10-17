"""Seeds typed or pasted in any script: Chinese titles, full-width characters, curly quotes and 《》, links without
https://, mirror sites of arXiv, and Chinese report names on the page."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tastecal.cli import folder_slug  # noqa: E402
from tastecal.core.http import HttpError  # noqa: E402
from tastecal.core.model import slugify  # noqa: E402
from tastecal.app.serve import make_server, slug  # noqa: E402
from tastecal.sources.semantic_scholar import SemanticScholar, _path, clean_seed, normalise_ref  # noqa: E402

PAPER = {"paperId": "abc", "title": "Planning-oriented Autonomous Driving", "year": 2023, "externalIds": {"ArXiv": "2212.10156"}}


class CleanSeedTest(unittest.TestCase):
    def test_titles(self):
        for raw in ("“Planning-oriented Autonomous Driving”", "《Planning-oriented Autonomous Driving》",
                    "  Planning-oriented　 Autonomous   Driving ", "Planning-oriented Autonomous​ Driving",
                    "「Planning-oriented Autonomous Driving」", "Ｐｌａｎｎｉｎｇ-oriented Autonomous Driving"):
            self.assertEqual(clean_seed(raw), "Planning-oriented Autonomous Driving", repr(raw))
        self.assertEqual(clean_seed("《具身智能：一个综述》"), "具身智能:一个综述")      # Chinese kept, full-width colon made plain
        self.assertEqual(clean_seed("Don’t Stop Pretraining"), "Don't Stop Pretraining")
        self.assertEqual(clean_seed("EmbodiedEvo: Self-improving Coding Agents for Physical Intelligence"),
                         "EmbodiedEvo: Self-improving Coding Agents for Physical Intelligence")   # unchanged: old caches match

    def test_ids_and_links(self):
        cases = {
            "ａｒＸｉｖ：２２１２．１０１５６": "arXiv:2212.10156",
            "2212.10156": "arXiv:2212.10156",
            "https://arxiv.org/abs/2212.10156。": "arXiv:2212.10156",
            "arxiv.org/pdf/2212.10156v2": "arXiv:2212.10156",
            "https://www.alphaxiv.org/abs/2212.10156": "arXiv:2212.10156",
            "https://huggingface.co/papers/2212.10156": "arXiv:2212.10156",
            "“https://arxiv.org/abs/2212.10156”": "arXiv:2212.10156",
            "https://doi.org/10.1109/TITS.2024.3456789": "DOI:10.1109/TITS.2024.3456789",
            "https://doi.org/10.1000%2Fabc": "DOI:10.1000/abc",
            "10.1145/3292500.3330701": "DOI:10.1145/3292500.3330701",
            "Planning-oriented Autonomous Driving": None,
            "具身智能综述": None,
        }
        for raw, want in cases.items():
            self.assertEqual(normalise_ref(raw), want, raw)
        self.assertEqual(normalise_ref("www.example.com/论文"), "URL:https://www.example.com/论文")

    def test_url_path_is_ascii(self):
        p = _path("URL:https://www.example.com/论文?id=1#x")
        self.assertTrue(p.isascii())
        self.assertIn("%3F", p)
        self.assertEqual(_path("arXiv:2212.10156"), "arXiv:2212.10156")
        self.assertEqual(_path("DOI:10.1002/(SICI)1097-4571"), "DOI:10.1002/(SICI)1097-4571")


class FakeHttp:
    def __init__(self, routes, replay=False):
        self.routes, self.replay, self.seen = routes, replay, []

    def get_json(self, url, params=None, headers=None, **kw):
        self.seen.append((url, params))
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val(params) if callable(val) else val
        raise HttpError(404, url, "not found")


class TitleLookupTest(unittest.TestCase):
    def test_exact_then_closest(self):
        s2 = SemanticScholar(FakeHttp({"/paper/search/match": HttpError(404, "m", "Title match not found"),
                                       "/paper/search": {"data": [PAPER]}}))
        self.assertEqual(s2.resolve("“planning oriented autonomous driving”").title, PAPER["title"])
        self.assertEqual(s2.http.seen[0][1]["query"], "planning oriented autonomous driving")   # quotes gone

    def test_chinese_title_through_openalex(self):
        http = FakeHttp({"/paper/search/match": HttpError(404, "m", ""), "/paper/search": {"data": []},
                         "api.openalex.org": {"results": [{"doi": "https://doi.org/10.1000/xyz", "title": "具身智能综述"}]},
                         "/paper/DOI:10.1000/xyz": PAPER})
        self.assertEqual(SemanticScholar(http).resolve("《具身智能综述》").title, PAPER["title"])

    def test_not_found_says_what_to_do(self):
        http = FakeHttp({"/paper/search/match": HttpError(404, "m", ""), "/paper/search": {"data": []},
                         "api.openalex.org": {"results": []}})
        with self.assertRaises(LookupError) as caught:
            SemanticScholar(http).resolve("具身智能综述")
        self.assertIn("arXiv link, DOI or English title", str(caught.exception))

    def test_resume_replay(self):
        # When resuming, the exact match the first attempt never got fails with status 0; the closest hit is cached.
        http = FakeHttp({"/paper/search/match": HttpError(0, "m", "not in the earlier run's downloads"),
                         "/paper/search": {"data": [PAPER]}}, replay=True)
        self.assertEqual(SemanticScholar(http).resolve("Planning oriented").title, PAPER["title"])

    def test_network_errors_still_surface(self):
        http = FakeHttp({"/paper/search/match": HttpError(0, "m", "Connection reset")})
        with self.assertRaises(HttpError):
            SemanticScholar(http).resolve("Planning oriented")


class FolderNameTest(unittest.TestCase):
    def test_folder_slug(self):
        self.assertEqual(folder_slug("具身智能综述"), "具身智能综述")
        self.assertEqual(folder_slug("Planning-oriented Autonomous Driving"),
                         slugify("Planning-oriented Autonomous Driving", max_len=40))           # as before
        self.assertEqual(folder_slug("ＵｎｉＡＤ"), "uniad")
        self.assertEqual(folder_slug("自動運転のサーベイ"), "自動運転のサーベイ")
        self.assertEqual(slug("《具身智能综述》 survey"), "具身智能综述-survey")

    def test_page_buttons_work_for_chinese_names(self):
        base = tempfile.mkdtemp()
        rid = "具身智能综述-20261016-1200"
        os.makedirs(os.path.join(base, "runs", rid))
        with open(os.path.join(base, "runs", rid, "request.json"), "w", encoding="utf-8") as f:
            json.dump({"seed": "具身智能综述", "provider": "claude-cli", "model": "claude-opus-5-5", "budget": 10}, f,
                      ensure_ascii=False)
        srv = make_server(port=0, base=base, resume_command=lambda out: [sys.executable, "-c", "print('ok')"])
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/api/runs/{urllib.parse.quote(rid)}/resume"
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "X-TasteCal": "1"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(json.loads(r.read()), {"resumed": True})
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
