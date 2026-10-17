"""graph.json → a single self-contained HTML report."""
from __future__ import annotations

import html
import json
import os
from typing import Optional

from tastecal.report.i18n_zh import is_zh, localize

TEMPLATE = os.path.join(os.path.dirname(__file__), "report.html")
MARKER = "/*__GRAPH_DATA__*/null"

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


def render_html(graph: dict, fragment: bool = False, template_path: Optional[str] = None) -> str:
    """`fragment=True` returns the page body only (for hosts that add their own skeleton)."""
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
    body = tpl.replace(MARKER, data).replace("__TITLE__", html.escape(page_title(graph)))
    if fragment:
        return body
    head = STANDALONE_HEAD.replace('<html lang="en">', '<html lang="zh-CN">') if zh else STANDALONE_HEAD
    return head + body + STANDALONE_TAIL


def write_report(graph: dict, path: str, fragment: bool = False) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(graph, fragment=fragment))
    return path
