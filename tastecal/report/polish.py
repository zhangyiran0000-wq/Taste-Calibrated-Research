"""Plain language: the writing rules every reader-facing prompt carries, a lint that finds sentences
breaking them, and a polish pass that rewrites only the flagged text.

The lint is deliberately simple and language-aware:
  long sentence      more than 28 words (English) or 55 characters (Chinese)
  too many papers    more than 3 works named in one sentence ([[id]] links or known short names)
  hype word          words that praise instead of inform ("novel", "remarkable", "革命性" ...)

The polish pass keeps every [[id]] link and every number. A rewrite that drops one is thrown away
and the original text stays.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("tastecal.polish")

MAX_WORDS = 28          # English words per sentence
MAX_CHARS_ZH = 55       # Chinese characters (Latin words count as one) per sentence
MAX_WORKS = 3           # works named per sentence

RULES_EN = """Write for a reader who is new to the field. Plain language:
- One idea per sentence, at most 25 words. Split long sentences.
- Name at most three works in one sentence. If more belong, say "several works" and name the clearest two or three.
- No stacked adjectives and no praise words (novel, remarkable, groundbreaking, comprehensive, crucial, powerful).
  Say what a work does and what it found.
- Prefer verbs: "X fixes Y's slow decoding", not "X provides a solution to the decoding efficiency issue of Y".
- Explain a technical term in a few words the first time it appears.
- Keep numbers, method names and [[id]] links exactly as given."""

RULES_ZH = """面向刚入门的读者，用平实的语言：
- 一句话只讲一件事，每句不超过 40 个字；长句拆开。
- 一句话里最多点名三项工作；更多时写“若干工作”，只点名最清楚的两三项。
- 不堆形容词，不用夸饰词（开创性、革命性、卓越、全面、极其重要）。说清它做了什么、发现了什么。
- 多用动词：写“X 解决了 Y 解码慢的问题”，不写“X 为 Y 的解码效率问题提供了解决方案”。
- 专业术语第一次出现时，用几个字解释。
- 数字、方法名和 [[id]] 链接保持原样。"""

HYPE_EN = ("novel", "remarkable", "groundbreaking", "ground-breaking", "revolutionary", "comprehensive", "crucial",
           "powerful", "unprecedented", "cutting-edge", "state-of-the-art", "seminal", "elegant", "impressive",
           "significantly", "dramatically", "vastly", "paradigm-shifting")
HYPE_ZH = ("开创性", "革命性", "卓越", "极其", "极大地", "全面地", "里程碑", "颠覆", "惊人", "非常重要", "至关重要", "前所未有")

CJK = re.compile(r"[㐀-鿿豈-﫿]")
LINK = re.compile(r"\[\[([^\]]+)\]\]")
NUM = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*%?")
ABBREV = re.compile(r"\b(et al|e\.g|i\.e|vs|cf|Fig|Figs|Tab|Sec|Eq|No|approx)\.", re.I)


def is_zh(lang: str) -> bool:
    return (lang or "").lower().startswith("zh")


def rules(lang: str = "en") -> str:
    return RULES_ZH if is_zh(lang) else RULES_EN


def system_note(lang: str = "en") -> str:
    """Appended to every system prompt: the language and the plain-language rules."""
    if is_zh(lang):
        head = ("Write every reader-facing text value in Simplified Chinese (简体中文). Keep paper titles, method names, "
                "author names and verbatim quotes in their original language. This overrides any earlier instruction "
                "about the output language. JSON keys and enum values stay in English.")
    else:
        head = "Write every reader-facing text value in English."
    return head + "\n" + rules(lang)


def sentences(text: str) -> List[str]:
    """Split into sentences without breaking at "et al." or "Fig. 2" or decimals."""
    t = ABBREV.sub(lambda m: m.group(0).replace(".", "․"), text or "")
    parts = re.split(r"(?<=[。！？；!?;])\s*|(?<=\.)\s+(?=[A-Z0-9\[\(“\"‘])", t)
    return [p.replace("․", ".").strip() for p in parts if p and p.strip()]


def length(sentence: str) -> Tuple[int, str]:
    """(length, unit): CJK characters plus Latin words for Chinese, words for English."""
    s = LINK.sub(lambda m: "X", sentence)
    cjk = len(CJK.findall(s))
    if cjk >= 4:
        latin = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9.+\-/%]*", CJK.sub(" ", s)))
        return cjk + latin, "zh"
    return len(re.findall(r"\S+", s)), "en"


def works_named(sentence: str, shorts: Iterable[str] = ()) -> int:
    n = len(set(LINK.findall(sentence)))
    plain = LINK.sub(" ", sentence)
    for s in shorts:
        if len(s) >= 3 and re.search(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])", plain):
            n += 1
    return n


def lint(text: str, shorts: Iterable[str] = ()) -> List[str]:
    """Problems with one piece of text, as short labels ('long sentence (41 words)')."""
    out: List[str] = []
    shorts = list(shorts)
    for s in sentences(text):
        n, unit = length(s)
        if (unit == "en" and n > MAX_WORDS) or (unit == "zh" and n > MAX_CHARS_ZH):
            out.append(f"long sentence ({n} {'words' if unit == 'en' else 'characters'}): {s[:40]}…")
        w = works_named(s, shorts)
        if w > MAX_WORKS:
            out.append(f"{w} works named in one sentence: {s[:40]}…")
    low = (text or "").lower()
    for h in HYPE_EN:
        if re.search(r"(?<![a-z])" + re.escape(h) + r"(?![a-z])", low):
            out.append(f"praise word: {h}")
    for h in HYPE_ZH:
        if h in (text or ""):
            out.append(f"praise word: {h}")
    return out


# ----------------------------------------------------------------------------- the graph's text fields
def text_fields(g: dict) -> List[Tuple[str, Callable[[], str], Callable[[str], None]]]:
    """Every reader-facing text in the graph that the pipeline wrote, as (path, getter, setter)."""
    rows: List[Tuple[str, Callable[[], str], Callable[[str], None]]] = []

    def add(path: str, obj, key) -> None:
        if isinstance(obj, (dict, list)) and (isinstance(key, int) or key in obj) and isinstance(obj[key], str) and obj[key].strip():
            rows.append((path, lambda o=obj, k=key: o[k], lambda v, o=obj, k=key: o.__setitem__(k, v)))

    f = g.get("field") or {}
    for k in ("goal", "core_tension"):
        add(f"field.{k}", f, k)
    for name in ("enabling_insights", "external_drivers", "knock_on"):
        for i, x in enumerate(f.get(name) or []):
            add(f"field.{name}[{i}].text", x, "text")
    for i, _ in enumerate(f.get("open_problems") or []):
        add(f"field.open_problems[{i}]", f["open_problems"], i)
    for i, x in enumerate(f.get("driving_forces") or []):
        add(f"field.driving_forces[{i}].statement", x, "statement")
    for t in g.get("threads") or []:
        add(f"threads.{t.get('id')}.question", t, "question")
        add(f"threads.{t.get('id')}.status_note", t, "status_note")
        for j, r in enumerate((t.get("ladder") or {}).get("rungs") or []):
            add(f"threads.{t.get('id')}.ladder[{j}]", r, "text")
    for p in g.get("problems") or []:
        add(f"problems.{p.get('id')}", p, "text")
    for n in g.get("nodes") or []:
        c = n.get("card") or {}
        for k in ("inherits", "move", "insight", "summary"):
            add(f"nodes.{n.get('id')}.{k}", c, k)
        for j, _ in enumerate(c.get("leaves") or []):
            add(f"nodes.{n.get('id')}.leaves[{j}]", c["leaves"], j)
        gt = n.get("gates") or {}
        add(f"nodes.{n.get('id')}.gates.why", gt, "why")
        for j, _ in enumerate(gt.get("confounders") or []):
            add(f"nodes.{n.get('id')}.gates.confounders[{j}]", gt["confounders"], j)
        if isinstance(gt.get("fold_reason"), dict):
            add(f"nodes.{n.get('id')}.gates.fold_summary", gt["fold_reason"], "summary")
    for e in g.get("edges") or []:
        add(f"edges.{e.get('source')}->{e.get('target')}", e, "label")
    s = g.get("story") or {}
    for i, _ in enumerate(s.get("paragraphs") or []):
        add(f"story[{i}]", s["paragraphs"], i)
    o = g.get("outlook") or {}
    for i, x in enumerate(o.get("next_steps") or []):
        add(f"outlook.next_steps[{i}].text", x, "text")
        add(f"outlook.next_steps[{i}].settle", x, "settle")
    for i, x in enumerate(o.get("assumptions") or []):
        add(f"outlook.assumptions[{i}].text", x, "text")
        add(f"outlook.assumptions[{i}].if_broken", x, "if_broken")
    return rows


def shorts_of(g: dict) -> List[str]:
    return [n.get("short") for n in g.get("nodes") or [] if n.get("short")]


def lint_graph(g: dict) -> List[dict]:
    shorts = shorts_of(g)
    out = []
    for path, get, _ in text_fields(g):
        issues = lint(get(), shorts)
        if issues:
            out.append({"path": path, "text": get(), "issues": issues})
    return out


def report(g: dict) -> Dict[str, object]:
    rows = text_fields(g)
    flagged = lint_graph(g)
    return {"texts": len(rows), "flagged": len(flagged),
            "by_section": _count(r["path"].split(".")[0].split("[")[0] for r in flagged)}


def _count(xs: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


# ----------------------------------------------------------------------------- polish
def keeps_facts(old: str, new: str) -> bool:
    """A rewrite may reorder and split, but it must keep every [[id]] link and every number."""
    if not new or not new.strip():
        return False
    if set(LINK.findall(old)) != set(LINK.findall(new)):
        return False
    if not set(NUM.findall(old)) <= set(NUM.findall(new)):
        return False
    return len(new) <= max(60, int(len(old) * 1.35))


def polish(g: dict, llm, lang: str = "en", batch: int = 12, limit: Optional[int] = None) -> Dict[str, int]:
    """Rewrite the flagged texts in plain language. Returns counts; the graph is changed in place."""
    from tastecal.prompts import lineage as prompts
    shorts = shorts_of(g)
    todo = []
    for path, get, put in text_fields(g):
        issues = lint(get(), shorts)
        if issues:
            todo.append((path, get, put, issues))
    if limit is not None:
        todo = todo[:limit]
    rewritten = rejected = 0
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        rows = [{"k": f"t{j + 1}", "text": get(), "issues": issues} for j, (_, get, _, issues) in enumerate(part)]
        try:
            res = llm.json(prompts.SYSTEM, prompts.polish(rows, rules(lang)))
        except Exception as e:  # keep the originals
            log.warning("polish batch failed: %s", e)
            continue
        res = res if isinstance(res, dict) else {}
        for j, (path, get, put, _) in enumerate(part):
            new = res.get(f"t{j + 1}")
            if isinstance(new, str) and keeps_facts(get(), new):
                put(new.strip())
                rewritten += 1
            elif new:
                rejected += 1
                log.info("polish: kept the original %s (the rewrite lost a link or a number)", path)
    left = len(lint_graph(g))
    stats = {"flagged": len(todo), "rewritten": rewritten, "rejected": rejected, "still_flagged": left}
    g.setdefault("meta", {})["style"] = dict(stats, rules="plain language", language=lang)
    return stats
