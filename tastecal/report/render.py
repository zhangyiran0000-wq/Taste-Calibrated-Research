"""graph.json → a single self-contained HTML report: the lineage and its logic, and, when the run has a taste
calibration (taste_fit.json next to the report), the taste part after it."""
from __future__ import annotations

import html
import json
import os
from typing import Optional

from tastecal.report.i18n_zh import is_zh, localize

TEMPLATE = os.path.join(os.path.dirname(__file__), "report.html")
MARKER = "/*__GRAPH_DATA__*/null"
TASTE_MARKER = "<!--__TASTE__-->"
TASTE_FILE = "taste_fit.json"

STANDALONE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
body{margin:0;font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
img{max-width:100%}[hidden]{display:none!important}
</style>
</head>
<body>
"""
STANDALONE_TAIL = "\n</body>\n</html>\n"


def page_title(graph: dict) -> str:
    seed_id = (graph.get("meta") or {}).get("seed")
    seed = next((n for n in graph.get("nodes", []) if n.get("role") == "seed" or n.get("id") == seed_id), None)
    if is_zh(graph):
        name = (seed or {}).get("short") or "研究"
        return f"{name} 脉络"
    name = (seed or {}).get("short") or "Research"
    return f"{name} Lineage"


def render_html(graph: dict, fragment: bool = False, template_path: Optional[str] = None, taste: Optional[dict] = None) -> str:
    """`fragment=True` returns the page body only (for hosts that add their own skeleton). `taste` is a taste
    calibration (taste_fit.json) of the same run: the report then has it as its second part."""
    with open(template_path or TEMPLATE, "r", encoding="utf-8") as f:
        tpl = f.read()
    if MARKER not in tpl:
        raise ValueError("template is missing the data marker")
    data = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    # "<" only occurs inside JSON strings, where \u003c is equivalent and cannot close the <script>.
    data = data.replace("<", "\\u003c")
    zh = is_zh(graph)
    if zh:
        tpl = localize(tpl)
    if TASTE_MARKER not in tpl:
        raise ValueError("template is missing the taste marker")
    body = tpl.replace(MARKER, data).replace("__TITLE__", html.escape(page_title(graph)))
    part = ""
    if taste:
        from tastecal.report.axes_view import embed
        part = embed(taste, (graph.get("meta") or {}).get("language", "en"))
    body = body.replace(TASTE_MARKER, part)
    if fragment:
        return body
    head = STANDALONE_HEAD.replace('<html lang="en">', '<html lang="zh-CN">') if zh else STANDALONE_HEAD
    return head + body + STANDALONE_TAIL


def taste_beside(graph: dict, folder: str) -> Optional[dict]:
    """The taste calibration kept next to a report (taste_fit.json), read for the report: None when there is none
    or it cannot be read."""
    path = os.path.join(folder, TASTE_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            res = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(res, dict) or res.get("error"):
        return None
    from tastecal.taste.axes import enrich
    enrich(res, graph)                       # venue and authors, as the map has them
    return res


def write_report(graph: dict, path: str, fragment: bool = False, taste="auto") -> str:
    """`taste="auto"` takes the taste calibration next to the report, if there is one; a dict is used as given;
    None leaves the taste part out."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if taste == "auto":
        taste = taste_beside(graph, os.path.dirname(os.path.abspath(path)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(graph, fragment=fragment, taste=taste))
    return path
