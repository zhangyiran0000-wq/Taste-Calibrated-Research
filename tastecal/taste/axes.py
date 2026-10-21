"""Fitting the reader's taste: your indicators, your scores, and the field's attention (design: the project's
claude/taste-calibration-design.md).

Step 1, your scores, a hard constraint. Each paper is measured on your indicators (the general ones, rewritten in
your terms, plus those your reasons add): step functions 0, 0.2, ..., 1.0 whose levels are conditions checkable in
the paper, never what you like and never how the field received it. Every indicator counts the same: the score is the
average level, put on your scale by yours ~ a * s + b (fit_scale). There are no weights to fit, so the loop works on
the clauses alone while any rated paper is off by more than FIT_TOL or any pair is out of order (a paper that resists
TRIES changes in a row gives way to the next one off). The worst miss is set against the rated paper predicted
closest to it but scored far apart, the model proposes one general change (rewrite a rubric, add or take out an
indicator, or a reading note applied to every paper), and it is kept only if your scores are reproduced more closely
and no pair you scored 0.3 apart changes order. Your scores are never judged: a miss means the clauses are not yet right.

Step 2, every paper towards y = x. Every other method paper on the map of the last YEARS years, and a sample
(RANDOM_SHARE of them) drawn at random from papers citing the map's works, is measured on the same indicators and set
against how much the field attends to it (attention.py): citations a year on a normal scale, no citation at -3 sigma
and Attention Is All You Need at +3 sigma. The objective is these papers' distance from y = x; your scores are the
constraint: each rated paper within FIT_TOL of your score (or within step 1's miss, if that was larger) and no pair
you scored GAP apart out of order. The scoring itself is fitted to it: a weighted sum of the levels, weights >= 0,
starting from every clause counting the same (fit_weights). The field may also rewrite or annotate a clause or add up
to FIELD_NEW of its own; each change is proposed from one half of the papers and kept only if the other half comes
closer, under weights fitted without it.

Then: the papers off y = x, high on your line and little attended, or much attended and low on your line, for each
measure of attention; the best and the most off on your line; every indicator with its share and source (general,
your reasons, learned, from the field).
Tools, datasets, surveys, benchmarks and concept works (definitions, taxonomies, terminology) are never scored:
they are listed by name only.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date
from statistics import mean, median
from typing import Dict, List, Optional, Tuple

from tastecal.prompts import axes as P

log = logging.getLogger("tastecal.fit")

DEFAULTS = {
    "en": [{"name": "Novelty", "rubric": "0 = a known method applied unchanged; 1 = a known idea renamed or given a new theoretical label; 2 = a small change to a known method; 3 = a new combination of known parts; 4 = a new kind of approach to a known problem; 5 = a new general architecture, paradigm or problem that can replace the prevailing approach, shown on more than one task or setting"},
           {"name": "Soundness", "rubric": "0 = no reason given for why it works; 1 = only an analogy, or a theory's name borrowed with none of that theory's computation in the procedure; 2 = a mechanism is described, but the training or procedure does not guarantee it (for example iterating is claimed to improve results with nothing that enforces it); 3 = a mechanism the procedure does enforce, not checked; 4 = an experiment isolates the central mechanism the paper credits for its gain (not a side component); 5 = as 4, and the conditions where it fails are stated"},
           {"name": "Validity", "rubric": "0 = no quantitative test of the claimed property; 1 = only a proxy that cannot show it (for example open-loop averages for a claim about closed-loop driving); 2 = a test that removes the hard part (for example other agents that replay logs and do not react); 3 = a direct test in one setting; 4 = direct tests in several settings with per-case results; 5 = as 4, plus failure cases and variance"},
           {"name": "Practicality", "rubric": "0 = needs resources or inputs that real systems do not have (for example ground truth at test time); 1 = strong assumptions, no runtime reported; 2 = runs offline only, high cost; 3 = runs with moderate cost, code released; 4 = runs in real time or at the scale of real use; 5 = shown working on a real system or real data at scale"}],
    "zh": [{"name": "创新性", "rubric": "0 = 原样套用已知方法；1 = 已知想法换个名字或套上新的理论名称；2 = 对已知方法做小改动；3 = 已有部件的新组合；4 = 对已知问题提出新一类做法；5 = 提出新的通用结构、新范式或新问题，可以取代现有主流做法，并在不止一个任务或设定上展示"},
           {"name": "合理性", "rubric": "0 = 没说为什么有效；1 = 只有类比，或借用某个理论的名称，流程里却没有该理论的核心计算；2 = 描述了机制，但训练或流程并不保证它成立（比如声称反复迭代能逐步改进，却没有任何约束保证）；3 = 流程确实保证了机制，但没有验证；4 = 有实验单独隔离出论文声称带来提升的核心机制（不是某个附属部件）；5 = 在 4 的基础上写明在什么条件下失效"},
           {"name": "有效性", "rubric": "0 = 没有对主张性质的定量测试；1 = 只有测不出该性质的替代指标（比如主张关于闭环驾驶，却只给开环均值）；2 = 测试去掉了真正难的部分（比如他车只回放日志、不作反应）；3 = 在一个设定下直接测了该性质；4 = 在多个设定下直接测，并给出分情况结果；5 = 在 4 的基础上给出失败案例和方差"},
           {"name": "落地可能性", "rubric": "0 = 需要真实系统拿不到的输入或资源（比如测试时用真值）；1 = 假设很强，没有报告运行开销；2 = 只能离线运行，开销大；3 = 开销中等，代码公开；4 = 能实时运行或达到实际使用的规模；5 = 已在真实系统或大规模真实数据上验证"}],
}
BATCH = 4                 # papers per call when every indicator is measured
BATCH_ONE = 8             # papers per call when a single indicator is measured
MAX_SIDE = 14             # your rated papers measured side by side, one indicator at a time, up to this many per call
REFS = 5                  # your rated papers shown as the standard when the others are measured
MIN_NOTES = 1200          # an audit excerpt shorter than this is not enough to measure a rated paper on
YEARS = 10                # papers you have not rated: only those of the last ten years are compared (your own are kept)
RANDOM_SHARE = 0.15       # papers drawn at random, as a share of the map's papers compared
WORKERS = 4               # model calls in flight at once when measuring many papers
GAP = 0.3                  # rated papers this far apart must be predicted in the same order
FAR = 0.15                 # a paper you have not rated is off y = x beyond this (plus its bars and twice the noise)
YOUNG = 12                 # months: a paper younger than this is drawn but never listed off y = x (too few citations yet)
MAX_ROUNDS = 15
TRIES = 2                  # changes tried for one rated paper in a row before the loop turns to the next one off
FIT_TOL = 0.1              # your rated papers: the clauses must give each one its score within this
LAM_FIT = 0.03             # light ridge, relative to the levels' spread: the line reproduces your scores
MAX_INDICATORS = 8        # never more than max(4, rated papers - 2): with as many indicators as papers, anything fits
MIN_INDICATORS = 3         # the loop may take out a clause, never below this
MAX_SLOPE = 2.0            # the average level is put on your scale by at most twice its spread: when your rated papers'
                           # average levels bunch together, a steeper line would turn small differences into large ones
                           # and push other papers to 0 or 1; the clauses must spread them instead
PREFERENCE = re.compile(r"\b(readers?|tastes?|prefer\w*|favou?rite|likes?)\b|读者|使用者|喜欢|偏好|品味|审美|口味|欣赏|看重", re.I)
# how the field received a paper: never part of a clause, since the field's attention is the axis the score is set against
RECEPTION = re.compile(
    r"\b(cited\b|citations?\b|citation counts?|highly cited|citing papers|widely (used|adopted|cited)|adopted by|taken up by|"
    r"(used|followed|built on|extended) by (later|other|subsequent|many)|(later|subsequent|follow-?up) (works?|papers?|studies|research)|"
    r"influential|high[- ]impact|impactful|famous|well[- ]known|renowned|prestigious|popular\w*|top[- ]tier|"
    r"(top|major|prestigious) (venues?|conferences?|journals?|labs?|groups?|institutions?)|github stars?)|"
    r"被引|引用量|引用数|引用次数|高引|被(后续|后来|其他|大量|广泛|许多|很多)[^，。；;,]{0,6}(沿用|采用|引用|使用|跟进|借鉴)|后续工作|后续研究|"
    r"后来的工作|广泛(沿用|采用|使用)|影响力|知名|著名|名气|顶会|顶刊|热门|关注度", re.I)
LAMBDAS = (0.03, 0.1, 0.3, 1.0)       # relative to the data's own spread (fit_line): at most half the slope is shrunk away
NOT_METHODS = ("tool", "dataset", "survey", "benchmark", "concept")
NOTE_CAP = 600            # a reading note the loop adds to a clause: at most this long, cut at the end of a sentence
SENTENCE_END = re.compile(r"[.!?](?=\s|$)|[。！？]")


def whole_note(text: str, cap: int = NOTE_CAP) -> str:
    """`text` in one line, at most `cap` characters, ending where a sentence ends: a note cut mid-sentence ("... If")
    reads as a different rule. Without a sentence end in reach, it ends at the last whole word."""
    text = " ".join(str(text or "").split())
    if len(text) <= cap:
        return text
    ends = [m.end() for m in SENTENCE_END.finditer(text) if m.end() <= cap]
    if ends:
        return text[:ends[-1]]
    cut = text[:cap]
    space = cut.rfind(" ")
    return (cut[:space] if space > cap // 2 else cut).rstrip(" ,;:")


def _mended(note: str) -> str:
    """A reading note saved by an older fit, which cut notes at NOTE_CAP characters wherever that fell: the part up to
    its last whole sentence. Shorter notes, and notes that end a sentence, are kept as they are."""
    note = " ".join(str(note or "").split())
    if len(note) < NOTE_CAP or SENTENCE_END.search(note[-1:] + " "):
        return note
    ends = [m.end() for m in SENTENCE_END.finditer(note)]
    return note[:ends[-1]] if ends else note
BAND = 0.5                # off the diagonal: your rank and the field's differ by more than half the list
CJK = re.compile(r"[㐀-鿿]")


# ----------------------------------------------------------------------------- what a work is, and its notes
def _scrub(text: str, names: List[str]) -> str:
    repl = "这项工作" if CJK.search(text or "") else "this work"
    for nm in sorted({x for x in names if x and len(x) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(nm), repl, text, flags=re.I)
    return text


def _line(label: str, value) -> str:
    value = " ".join(str(value or "").split())
    return f"{label}: {value}" if value else ""


def notes(node: dict, short: bool = False) -> str:
    """What the full-text reading found in a work (claims, what is shown, the evaluation, the reason, the levers),
    without its names. The notes carry facts about the paper, not anyone's verdict, and nothing about how the field
    received it: that is the other axis of the fit."""
    c = node.get("card") or {}
    g = node.get("gates") or {}
    ev = (node.get("assessment") or {}).get("evidence") or {}
    fit = g.get("eval_fit") or ev.get("eval_fit") or {}
    ck = g.get("checks") or {}
    rows = [_line("Starts from", c.get("inherits")), _line("Move", c.get("move")), _line("Insight", c.get("insight"))]
    if not short:
        rows += [_line("Claims", g.get("claimed")),
                 _line("Delivers", f"{g.get('delivery', '')}{' (' + g['partial_kind'] + ')' if g.get('partial_kind') else ''}: {g.get('delivered', '')}"),
                 _line("Where the text shows it", g.get("delivery_evidence")),
                 _line("Reason given", f"{g.get('reason_type', '')}: {g.get('reason', '')}"),
                 _line("When it would not work", g.get("fails_when") or ("not stated" if g.get("fails_when_stated") is False else "")),
                 _line("Gains", f"{g.get('robustness', '')}: {g.get('robustness_note', '')}"),
                 _line("Evaluation", f"can show the property: {fit.get('can_show', '')}. {fit.get('shown_by', '')} {fit.get('fit_why', '')}" if fit else ""),
                 _line("Checks", "; ".join(f"{k}: {ck.get(k)}" for k in ("numbers", "fair_baselines", "novelty_ablation", "code") if ck.get(k))),
                 _line("Baselines", ck.get("baselines_note")), _line("Ablation", ck.get("ablation_note"))]
        for lv in (g.get("levers") or [])[:4]:
            if lv.get("status") == "present" and lv.get("note"):
                rows.append(_line(f"Lever ({lv.get('lever', '')})", lv["note"]))
    else:
        rows += [_line("Delivers", g.get("delivered")), _line("Evaluation", fit.get("fit_why") if fit else "")]
    text = "\n".join(r for r in rows if r)
    return _scrub(text, [node.get("title", ""), node.get("short", "")])[:2200 if short else 4600]


def _type_text(title: str, node: Optional[dict], fallback: str = "") -> str:
    """What a work claims and shows, for telling concept works from methods (the title is kept: this is not a score)."""
    g = (node or {}).get("gates") or {}
    fit = g.get("eval_fit") or {}
    bits = [title, _line("Claims", g.get("claimed")), _line("Delivers", g.get("delivered")),
            _line("Evaluation", fit.get("property") or fit.get("fit_why")), _line("Checks", (g.get("checks") or {}).get("numbers_note"))]
    text = "\n".join(b for b in bits if b)
    return (text if len(text) > len(title) + 20 else f"{title}\n{fallback}")[:900]


def concept_works(llm, items: List[Tuple[str, str]]) -> set:
    """The ids of the concept works among (id, text): definitions, a taxonomy, terminology, or a process described in
    words, with no method that runs and nothing tested. They are not scored, like surveys: every clause about
    evidence would put them at the bottom, and their citations come from the field using their words."""
    out = set()
    for i in range(0, len(items), 25):
        chunk = dict(items[i:i + 25])
        res = llm.json(P.SYSTEM, P.concepts(chunk))
        out |= {str(x) for x in ((res or {}).get("concept") if isinstance(res, dict) else None) or [] if str(x) in chunk}
    return out


def readable(node: dict) -> bool:
    return (node.get("gates") or {}).get("basis") == "full text" and node.get("kind", "paper") == "paper"


TYPE_WORDS = [("survey", re.compile(r"\b(survey|review|overview)\b", re.I)),
              ("benchmark", re.compile(r"\bbenchmark", re.I)), ("dataset", re.compile(r"\bdataset\b", re.I)),
              ("tool", re.compile(r"\b(simulator|toolkit|platform|library)\b", re.I))]


def work_type(node: dict) -> str:
    """"tool", "dataset", "survey", "benchmark", "concept" or "method": the fit's own finding (concept works, see
    concept_works), then the audit's type, then the reader's kind of evaluation, then the title. Only method papers
    are scored."""
    if node.get("fit_type"):
        return node["fit_type"]
    t = ((node.get("assessment") or {}).get("contribution") or {}).get("type")
    if t in NOT_METHODS:
        return t
    if ((node.get("gates") or {}).get("eval_fit") or {}).get("kind") == "benchmark":
        return "benchmark"
    if t:
        return "method"
    for name, rx in TYPE_WORDS:
        if rx.search(node.get("title") or ""):
            return name
    return "method"


def is_method(node: dict) -> bool:
    return work_type(node) not in NOT_METHODS


def find_node(nodes: List[dict], ref: str) -> Optional[dict]:
    """A work named by its short name ("STRIVE") or by the start of its title."""
    norm = lambda s: re.sub(r"[^a-z0-9㐀-鿿]+", "", (s or "").lower())  # noqa: E731
    key = norm(ref)
    if len(key) < 3:
        return None
    exact = [n for n in nodes if norm(n.get("short")) == key]
    if len(exact) == 1:
        return exact[0]
    starts = [n for n in nodes if len(key) >= 6 and norm(n.get("title")).startswith(key)]
    return starts[0] if len(starts) == 1 else None


def parse_rated(text: str) -> List[dict]:
    """Ratings pasted as lines: "title or short name | score | reason" (the reason may be left out)."""
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in re.split(r"\s*[|｜]\s*", line.strip().lstrip("-*0123456789. "))]
        if len(parts) < 2 or not parts[0]:
            continue
        try:
            score = max(0.0, min(1.0, float(parts[1])))
        except ValueError:
            continue
        out.append({"ref": parts[0], "score": score, "comment": " | ".join(parts[2:]).strip()})
    return out


def read_entries(data) -> List[dict]:
    """Ratings as data (from JSON or YAML): a list of {"paper", "score", "reason"} (also "title" or "ref" for the
    paper, "comment" for the reason), or {"papers": [...]}. Entries without a paper or a score are skipped."""
    if isinstance(data, dict):
        data = data.get("papers") or data.get("rated") or data.get("ratings") or []
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        ref = " ".join(str(e.get("paper") or e.get("title") or e.get("ref") or "").split())
        try:
            score = max(0.0, min(1.0, float(e.get("score"))))
        except (TypeError, ValueError):
            continue
        if ref:
            out.append({"ref": ref, "score": score, "comment": " ".join(str(e.get("reason") or e.get("comment") or "").split())})
    return out


def read_table(path: str) -> List[dict]:
    """Ratings from a .json or .yaml file (a list of paper, score, reason; YAML needs PyYAML), a spreadsheet (.xlsx,
    read without extra packages), a .csv, or a text file of "title | score | reason" lines. Spreadsheet columns:
    paper, score, reason; a header row is skipped."""
    import csv
    import json
    import zipfile
    import xml.etree.ElementTree as ET
    low = path.lower()
    rows: List[List[str]] = []
    if low.endswith(".json"):
        with open(path, "r", encoding="utf-8-sig") as f:
            return read_entries(json.load(f))
    if low.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            raise SystemExit(f"{path}: reading YAML needs PyYAML (pip install pyyaml); or save the ratings as .json")
        with open(path, "r", encoding="utf-8-sig") as f:
            return read_entries(yaml.safe_load(f))
    if low.endswith(".xlsx"):
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                    shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
            sheet = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
            for row in ET.fromstring(z.read(sheet)).iter("{%s}row" % ns["m"]):
                cells = {}
                for c in row.findall("m:c", ns):
                    col = re.sub(r"\d", "", c.get("r", "")) or str(len(cells))
                    v = c.find("m:v", ns)
                    if c.get("t") == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif c.get("t") == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter("{%s}t" % ns["m"]))
                    else:
                        val = v.text if v is not None else ""
                    cells[col] = val
                rows.append([cells[k] for k in sorted(cells, key=lambda k: (len(k), k))])
    elif low.endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.reader(f)]
    else:
        with open(path, "r", encoding="utf-8") as f:
            return parse_rated(f.read())
    out = []
    for r in rows:
        if len(r) < 2 or not str(r[0]).strip():
            continue
        try:
            score = max(0.0, min(1.0, float(str(r[1]).strip())))
        except ValueError:
            continue                                   # the header, or a row without a score
        out.append({"ref": " ".join(str(r[0]).split()), "score": score,
                    "comment": " ".join(str(r[2]).split()).strip('"') if len(r) > 2 and r[2] else ""})
    return out


def read_rated(rated: List[dict], cfg, llm, http, source, graph: dict) -> Tuple[List[dict], List[dict]]:
    """Rated papers that are not in this run, read the way the run read its own papers: found through Semantic
    Scholar, their full text from the papers folder, arXiv or an open-access copy, then the same reading notes.
    Returns (nodes read in full, papers that could not be: not found, or no full text, with the file name to use)."""
    from tastecal.judge.gates import Gatekeeper
    from tastecal.sources.fulltext import suggested_name
    keeper = Gatekeeper(cfg, llm, http)
    done, missing = [], []
    have, other = rated_works(graph, rated)
    have_refs = {h["ref"] for h in have} | {o["ref"] for o in other if o.get("node")}
    for i, r in enumerate(rated):
        if r["ref"] in have_refs:
            continue
        try:
            item = source.resolve(r["ref"])
        except Exception as e:  # not found, rate limited
            missing.append({"ref": r["ref"], "why": f"not found ({str(e)[:80]})"})
            continue
        node = {"id": f"rated-{i + 1}", "title": item.title, "short": "", "kind": "paper", "date": item.sort_date,
                "url": item.url, "card": {}, "ref": r["ref"]}
        if not is_method(node):  # a tool, dataset, survey or benchmark by its title: listed, never scored, so not read
            done.append(node)
            continue
        log.info("reading your rated paper: %s", item.title)
        ans = keeper.gate(node, item)
        if not ans or ans.get("basis") != "full text":
            missing.append({"ref": r["ref"], "title": item.title, "why": "no full text",
                            "file": suggested_name(node, item)})
            continue
        node["gates"] = ans
        done.append(node)
    return done, missing


def recent(node: dict, today: str, years: int = YEARS) -> bool:
    """Published within the last `years` years (0: any year). A paper without a date is kept."""
    y = re.match(r"(\d{4})", str(node.get("date") or node.get("year") or ""))
    return not years or not y or not today or int(y.group(1)) >= int(today[:4]) - years


def draw_sample(graph: dict, source, n: int, exclude: List[str] = (), anchors: int = 6, years: int = YEARS) -> list:
    """Works drawn at random from the map's neighbourhood: papers citing a few method papers on the map (not their
    references, which bring in general tools from other fields), of the last `years` years, taken uniformly, not by
    how much they are cited (the map itself grows towards cited work, so on its own it hides the little-cited corner).
    Returns up to 2n S2 items, in a fixed random order (seeded by the run)."""
    import random
    from tastecal.core.model import title_similarity
    seed = (graph.get("meta") or {}).get("seed_ref") or (graph.get("meta") or {}).get("seed") or "tastecal"
    rng = random.Random(seed)
    nodes = [nd for nd in graph.get("nodes", []) if is_method(nd) and (nd.get("ids") or {}).get("s2")]
    rng.shuffle(nodes)
    taken = [nd.get("title", "") for nd in graph.get("nodes", [])] + list(exclude)
    pool, seen = [], set()
    today = str((graph.get("meta") or {}).get("generated_at") or "")[:10] or date.today().isoformat()
    for nd in nodes[:anchors]:
        try:                                     # a lookup that fails leaves this anchor out, never the whole draw
            item = source.by_id(nd["ids"]["s2"])
            citing = (source.forward(item, nd["id"]) or []) if item else []
        except Exception as e:
            log.info("random draw: no citing papers for %s (%s)", nd.get("title", "")[:60], e)
            continue
        for c in citing:
            it = c.item
            key = it.ids.get("s2") or it.title
            if key in seen or not is_method({"title": it.title}) or not recent({"date": it.date, "year": it.year}, today, years):
                continue
            seen.add(key)
            if any(title_similarity(it.title, t) > 0.85 for t in taken if t):
                continue
            pool.append(it)
    pool.sort(key=lambda it: it.ids.get("s2") or it.title)      # the same draw on every run, whatever the source order
    rng.shuffle(pool)
    return pool[:2 * n]


def on_topic(llm, graph: dict, items: list) -> list:
    """The drawn works that work on the map's own problem (the seed's), not on a neighbouring task that only cites
    the map's works for a part. One short call on titles and abstracts, before anything is read in full."""
    if not items:
        return items
    seed = next((n for n in graph.get("nodes", []) if n.get("role") == "seed"), None) or {}
    card = seed.get("card") or {}
    problem = " ".join(x for x in (seed.get("title") or (graph.get("meta") or {}).get("seed_ref") or "",
                                   card.get("inherits", ""), card.get("move", "")) if x)[:900]
    threads = [t.get("name") or t.get("title") or "" for t in graph.get("threads") or []]
    works = {f"d{i}": f"{it.title}\n{(it.abstract or '')[:500]}" for i, it in enumerate(items)}
    res = llm.json(P.SYSTEM, P.topic(problem, threads, works))
    keep = {str(k) for k in ((res or {}).get("keep") if isinstance(res, dict) else None) or []}
    out = [it for i, it in enumerate(items) if f"d{i}" in keep]
    log.info("drawn papers on the map's own problem: %d of %d", len(out), len(items))
    return out


def read_items(items: list, cfg, llm, http, prefix: str, n: int) -> Tuple[List[dict], int]:
    """Read works in full, the way the run reads its own, until n have a full-text reading (abstract-only works are
    not scored). Returns (nodes, how many had no full text)."""
    from tastecal.judge.gates import Gatekeeper
    keeper = Gatekeeper(cfg, llm, http)

    def read(pair):
        i, item = pair
        node = {"id": f"{prefix}-{i + 1}", "title": item.title, "short": "", "kind": "paper", "date": item.sort_date,
                "year": item.year, "url": item.url, "card": {}, "ids": dict(item.ids), "citations": item.citations,
                "sample": prefix}
        ans = keeper.gate(node, item)
        if ans and ans.get("basis") == "full text":
            node["gates"] = ans
            return node
        return None
    got = _parallel(read, list(enumerate(items)), f"{prefix} papers read")
    done = [g for g in got if g]
    return done[:n], sum(1 for g in got if not g)


def rated_works(graph: dict, rated: List[dict], extra: Optional[List[dict]] = None) -> Tuple[List[dict], List[dict]]:
    """The rated papers that can be measured: a method paper read in full on the map, one of the rated papers
    read in full for this fit (`extra`), or one the audit read in full. Returns (usable, not used)."""
    from tastecal.core.model import title_similarity
    nodes = [n for n in graph.get("nodes", []) if readable(n)] + [n for n in (extra or []) if readable(n) or not is_method(n)]
    cal = [a for a in (((graph.get("audit") or {}).get("calibration") or {}).get("anchors") or [])]
    usable, skipped = [], []
    for i, r in enumerate(rated):
        ref = r.get("ref") or r.get("title") or ""
        node = (next((n for n in nodes if n.get("ref") == ref), None)
                or next((n for n in nodes if title_similarity(n.get("title", ""), ref) > 0.85), None) or find_node(nodes, ref))
        base = {"key": f"R{i + 1}", "ref": ref, "yours": float(r["score"]), "comment": r.get("comment", "")}
        if node and not is_method(node):
            skipped.append(dict(base, why="not a method paper", type=work_type(node), node=node["id"], title=node["title"]))
            continue
        if node:
            usable.append(dict(base, title=node["title"], node=node["id"], notes=notes(node),
                               summary=notes(node, short=True)[:700]))
            continue
        row = next((a for a in cal if title_similarity(a.get("title") or a.get("ref") or "", ref) > 0.85), None)
        ev = re.split(r"You see \d+% of the main text", " ".join(str((row or {}).get("evidence") or "").split()))[0].strip()
        if row and row.get("basis") == "full text" and len(ev) >= MIN_NOTES:
            usable.append(dict(base, title=row.get("title") or ref, node="", notes=_scrub(ev, [row.get("title") or ref])[:2500],
                               summary=ev[:700]))
        else:                                # a short excerpt says too little to measure on: read it in full instead
            skipped.append(dict(base, why="no full-text reading of it in this run"))
    # the same paper rated twice (a profile, then a ratings file): the later rating stands
    def last(rows: List[dict]) -> List[dict]:
        seen, out = set(), []
        for r in reversed(rows):
            k = r.get("node") or re.sub(r"\W+", "", (r.get("title") or r["ref"]).lower())
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out[::-1]
    return last(usable), last(skipped)


# ----------------------------------------------------------------------------- measuring
def _level(x) -> Optional[float]:
    """Levels 0-5 become 0, 0.2, ..., 1.0."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(min(5.0, max(0.0, round(v))) / 5, 1)


def clause_problem(text: str, names: List[str]) -> str:
    """Why an indicator's wording is not allowed, or "": every level must be a condition on the paper, never what
    the reader likes, and never a paper's name."""
    if PREFERENCE.search(text or ""):
        return "speaks of what the reader likes, not of the paper"
    if RECEPTION.search(text or ""):
        return "speaks of how the field received the paper, not of the paper"
    low = (text or "").lower()
    hit = next((n for n in names if n and len(n) >= 4 and n.lower() in low), "")
    return f"names a paper ({hit})" if hit else ""


def paper_names(graph: dict, rated: List[dict]) -> List[str]:
    out = {n.get("short", "") for n in graph.get("nodes", [])}
    out |= {re.split(r"[:：]", r.get("title") or r.get("ref") or "")[0].strip() for r in rated}
    return sorted(x for x in out if x and len(x) >= 4 and not CJK.search(x))


def _parallel(fn, jobs: list, label: str = "") -> list:
    """fn over jobs, WORKERS at a time, results in the order of the jobs; progress logged when there are many."""
    if len(jobs) <= 1:
        return [fn(j) for j in jobs]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(jobs))) as pool:
        futures = {pool.submit(fn, j): i for i, j in enumerate(jobs)}
        for done, f in enumerate(as_completed(futures), 1):
            out[futures[f]] = f.result()
            if label and len(jobs) > 2:
                log.info("%s: %d of %d", label, done, len(jobs))
    return out


def measure(llm, inds: List[dict], works: Dict[str, str], reverse: bool = False, check: str = "",
            label: str = "", refs: List[tuple] = (), size: Optional[int] = None) -> Dict[str, dict]:
    """{id: {"x": {indicator: 0..1 or None}, "basis": {indicator: text}}}. `refs`: works already measured,
    (summary, {indicator: level 0-5}), shown as the standard to apply; `size`: works per call."""
    names = [d["name"] for d in inds]
    out: Dict[str, dict] = {}
    items = list(works.items())
    size = size or (BATCH if len(inds) > 1 else BATCH_ONE)
    batches = [dict(items[i:i + size]) for i in range(0, len(items), size)]
    answers = _parallel(lambda batch: llm.json(P.SYSTEM, P.score(inds, batch, reverse=reverse, check=check, refs=refs)),
                        batches, label)
    for batch, res in zip(batches, answers):
        for row in (res.get("works") if isinstance(res, dict) else []) or []:
            if not isinstance(row, dict) or row.get("id") not in batch:
                continue
            lv = row.get("levels") or {}
            out[row["id"]] = {"x": {n: _level((lv.get(n) or {}).get("level")) for n in names},
                              "basis": {n: _basis(lv.get(n) or {}) for n in names}}
    return out


def _basis(cell: dict) -> str:
    """What meets the level, and what the work lacks for the next one up."""
    b = str(cell.get("basis") or "").strip()
    nh = str(cell.get("not_higher") or "").strip()
    if nh and nh.lower() not in ("top", "n/a", "none", "-"):
        b = f"{b} — {nh}" if b else nh
    return b[:360]


def measure_side_by_side(llm, inds: List[dict], works: Dict[str, str], reverse: bool = False, label: str = "",
                         refs: List[tuple] = ()) -> Dict[str, dict]:
    """One indicator at a time, every work in the same call, so the model sets them against each other (levels
    given one paper at a time crowd in the middle). One call per indicator (two when there are many works)."""
    out: Dict[str, dict] = {wid: {"x": {}, "basis": {}} for wid in works}
    size = max(1, min(len(works), MAX_SIDE))
    got = _parallel(lambda d: measure(llm, [d], works, reverse=reverse, refs=refs, size=size), list(inds), label)
    for d, res in zip(inds, got):
        for wid, row in res.items():
            if wid in out:
                out[wid]["x"][d["name"]] = row["x"].get(d["name"])
                out[wid]["basis"][d["name"]] = row["basis"].get(d["name"], "")
    return {wid: v for wid, v in out.items() if v["x"]}


# ----------------------------------------------------------------------------- the line
def _matrix(rows: List[dict], names: List[str]) -> List[List[float]]:
    """Missing levels take the indicator's mean over the rows (0.5 when none)."""
    means = {}
    for n in names:
        got = [r["x"].get(n) for r in rows if r["x"].get(n) is not None]
        means[n] = mean(got) if got else 0.5
    return [[r["x"].get(n) if r["x"].get(n) is not None else means[n] for n in names] for r in rows]


def fit_line(X: List[List[float]], y: List[float], lam: float, wts: Optional[List[float]] = None) -> Tuple[List[float], float]:
    """Ridge regression with non-negative weights (more of an indicator never lowers the score), by coordinate
    descent on centred data; `wts` weighs the rows (default 1 each). Returns (w, b)."""
    n, k = len(X), len(X[0]) if X else 0
    if n == 0:
        return [], 0.5
    wt = list(wts) if wts else [1.0] * n
    tot = sum(wt) or 1.0
    mx = [sum(wt[i] * X[i][j] for i in range(n)) / tot for j in range(k)]
    my = sum(wt[i] * y[i] for i in range(n)) / tot
    Xc = [[X[i][j] - mx[j] for j in range(k)] for i in range(n)]
    r = [y[i] - my for i in range(n)]                       # residual of the current w (all zero to start)
    energy = [sum(wt[i] * Xc[i][j] ** 2 for i in range(n)) for j in range(k)]
    scale = (sum(energy) / k) if k and sum(energy) > 0 else 1.0     # the penalty is relative to how spread the levels are
    den = [energy[j] + lam * scale for j in range(k)]
    w = [0.0] * k
    for _ in range(400):
        moved = 0.0
        for j in range(k):
            if den[j] <= 0:
                continue
            rho = sum(wt[i] * Xc[i][j] * (r[i] + Xc[i][j] * w[j]) for i in range(n))
            new = max(0.0, rho / den[j])
            d = new - w[j]
            if d:
                for i in range(n):
                    r[i] -= Xc[i][j] * d
                w[j] = new
                moved = max(moved, abs(d))
        if moved < 1e-7:
            break
    b = my - sum(w[j] * mx[j] for j in range(k))
    return [round(v, 4) for v in w], round(b, 4)


def fit_scale(X: List[List[float]], y: List[float], lam: float = 0.0, wts: Optional[List[float]] = None) -> Tuple[List[float], float]:
    """Every clause counts the same. The score is the average level, s = mean_k x_k, put on your scale by a line
    yours = a * s + b (a >= 0, weighted least squares; `lam` is unused). Only the clauses themselves are optimized:
    there are no weights to fit, just your scale and offset. Returns (w, b) with every w_k = a / k, so it plugs in
    wherever a weighted sum is used."""
    n, k = len(X), len(X[0]) if X else 0
    if n == 0 or k == 0:
        return [0.0] * k, 0.5
    wt = list(wts) if wts else [1.0] * n
    tot = sum(wt) or 1.0
    s_ = [sum(r) / k for r in X]
    ms = sum(a * v for a, v in zip(wt, s_)) / tot
    my = sum(a * v for a, v in zip(wt, y)) / tot
    var = sum(a * (v - ms) ** 2 for a, v in zip(wt, s_))
    slope = max(0.0, sum(a * (v - ms) * (t - my) for a, v, t in zip(wt, s_, y)) / var) if var > 0 else 0.0
    slope = min(slope, MAX_SLOPE)            # a steeper line would only stretch small differences in level
    return [round(slope / k, 4)] * k, round(my - slope * ms, 4)


def predict(x: List[float], w: List[float], b: float) -> float:
    return min(1.0, max(0.0, b + sum(a * c for a, c in zip(x, w))))


def loo(X: List[List[float]], y: List[float], lam: float, extra: Optional[tuple] = None) -> List[float]:
    """Each rated paper predicted by the line fitted to all the others (and to the `extra` rows, (X, y, weights),
    which are always in)."""
    ex_X, ex_y, ex_w = extra if extra else ([], [], [])
    out = []
    for i in range(len(X)):
        Xi, yi = X[:i] + X[i + 1:] + ex_X, y[:i] + y[i + 1:] + ex_y
        w, b = fit_scale(Xi, yi, lam, [1.0] * (len(X) - 1) + list(ex_w))
        out.append(predict(X[i], w, b))
    return out


def best_lambda(X: List[List[float]], y: List[float], extra: Optional[tuple] = None) -> float:
    if len(X) < 3:
        return LAMBDAS[-1]
    return min(LAMBDAS, key=lambda lam: mean(abs(p - t) for p, t in zip(loo(X, y, lam, extra), y)))


def order_errors(y: List[float], pred: List[float]) -> List[Tuple[int, int]]:
    """Pairs the reader scored >= GAP apart that the predictions put the other way round (or level)."""
    out = []
    for i in range(len(y)):
        for j in range(i + 1, len(y)):
            if abs(y[i] - y[j]) >= GAP - 1e-9 and (pred[i] - pred[j]) * (y[i] - y[j]) <= 0:
                out.append((i, j))
    return out


def evaluate(rows: List[dict], names: List[str], extra: Optional[tuple] = None, lam: Optional[float] = None) -> dict:
    """Your scores are a hard constraint: the objective is how closely the clauses reproduce them (the line fitted to
    all your rated papers, lightly regularised). Leave-one-out predictions are kept only to report how well the
    clauses would carry over to a paper they were not fitted on."""
    X, y = _matrix(rows, names), [r["yours"] for r in rows]
    lam = LAM_FIT if lam is None else lam
    ex_X, ex_y, ex_w = extra if extra else ([], [], [])
    w, b = fit_scale(X + ex_X, y + ex_y, lam, [1.0] * len(X) + list(ex_w))
    pred = [predict(x, w, b) for x in X]
    errs = [abs(p - t) for p, t in zip(pred, y)]
    pred_loo = loo(X, y, lam, extra)
    return {"lam": lam, "pred": pred, "err": errs, "mae": mean(errs) if errs else 0.0, "max": max(errs) if errs else 0.0,
            "order": order_errors(y, pred), "loo": pred_loo,
            "loo_mae": mean(abs(p - t) for p, t in zip(pred_loo, y)) if y else 0.0}


# ----------------------------------------------------------------------------- the loop
def _fixed(llm, text: str, names: List[str]) -> Tuple[str, str]:
    """(text, why refused): a refused clause or note is sent back once to be rewritten; "" when it still fails."""
    bad = clause_problem(text, list(names))
    if not bad or not text.strip():
        return text, bad
    res = llm.json(P.SYSTEM, P.fix_clause(text, bad))
    new = " ".join(str((res or {}).get("text") or "").split()) if isinstance(res, dict) else ""
    again = clause_problem(new, list(names)) if new else bad
    if again:
        return "", again
    log.info("a clause was refused (%s) and rewritten", bad)
    return new, ""


def _say(inds: List[dict], en: str, zh: str) -> str:
    return zh if any(CJK.search(d["name"]) for d in inds) else en


def _apply(inds: List[dict], e: dict, cap: int = MAX_INDICATORS, names: List[str] = ()) -> Tuple[Optional[List[dict]], List[str], str]:
    """(new indicators, names to re-measure on every rated paper, a one-line description). None when the change is
    not allowed: too many indicators, or wording that is not a condition on the paper."""
    kind = (e or {}).get("type")
    rubric = " ".join(str((e or {}).get("rubric") or "").split())
    name = " ".join(str((e or {}).get("name") or "").split())[:40]
    if clause_problem(f"{name} {rubric}", list(names)):
        return None, [], ""
    if kind == "remove":
        try:
            k = int(e.get("line")) - 1
        except (TypeError, ValueError):
            return None, [], ""
        if 0 <= k < len(inds) and len(inds) > MIN_INDICATORS:
            return inds[:k] + inds[k + 1:], [], _say(inds, "remove", "去掉") + f" {inds[k]['name']}"
        return None, [], ""
    if kind == "add" and rubric and name and name not in [d["name"] for d in inds] and len(inds) < cap:
        return inds + [{"name": name, "rubric": rubric, "from": "learned"}], [name], _say(inds, "add", "新增") + f" {name}: {rubric}"
    if kind == "rewrite" and rubric:
        try:
            k = int(e.get("line")) - 1
        except (TypeError, ValueError):
            return None, [], ""
        if 0 <= k < len(inds):
            new_name = name if name and name not in [d["name"] for j, d in enumerate(inds) if j != k] else inds[k]["name"]
            new = inds[:k] + [{"name": new_name, "rubric": rubric, "from": "learned"}] + inds[k + 1:]
            return new, [new_name], _say(inds, "rewrite", "改写") + f" {inds[k]['name']}: {rubric}"
    return None, [], ""


def _set_reads(r: dict, name: str, first, second=None, basis: str = "") -> None:
    """A rated paper's level on one clause from its reads: the first, the second (in the other order) when there is
    one, and their average, which is what the fit uses: the model's wobble from one read to the next about halves."""
    r.setdefault("x1", {})[name] = first
    if second is None:
        r.setdefault("x2", {}).pop(name, None)
    else:
        r.setdefault("x2", {})[name] = second
    vals = [v for v in (first, second) if v is not None]
    r["x"][name] = round(sum(vals) / len(vals), 3) if vals else None
    r["basis"][name] = basis


def _drop(r: dict, name: str) -> None:
    for k in ("x", "x1", "x2", "basis"):
        (r.get(k) or {}).pop(name, None)


def _copy(r: dict) -> dict:
    return dict(r, x=dict(r["x"]), basis=dict(r["basis"]), x1=dict(r.get("x1") or {}), x2=dict(r.get("x2") or {}))


def _read_twice(llm, inds: List[dict], rated: List[dict], label: str = "") -> None:
    """Your rated papers measured on these clauses twice, side by side, the second time in the other order; each
    level is the average of the two reads (the second read was always made, for the noise: now it is used)."""
    works = {r["key"]: r["notes"] for r in rated}
    one = measure_side_by_side(llm, inds, works, label=label)
    two = measure_side_by_side(llm, inds, works, reverse=True, label=(label + ", in the other order") if label else "")
    for r in rated:
        g1, g2 = one.get(r["key"]) or {}, two.get(r["key"]) or {}
        for d in inds:
            n = d["name"]
            _set_reads(r, n, (g1.get("x") or {}).get(n), (g2.get("x") or {}).get(n), (g1.get("basis") or {}).get(n, ""))


def calibrate(llm, rated: List[dict], inds: List[dict], max_rounds: int = MAX_ROUNDS, margin: float = 0.003,
              names_banned: List[str] = ()) -> dict:
    """The loop on the rated papers. `rated` rows carry "notes", "yours", "comment", "summary"; they get "x"."""
    cap = min(MAX_INDICATORS, max(4, len(rated) - 2))
    works = {r["key"]: r["notes"] for r in rated}
    log.info("measuring your %d rated papers on %d indicators, side by side, twice (in both orders)", len(rated), len(inds))
    for r in rated:
        r["x"], r["basis"], r["x1"], r["x2"] = {}, {}, {}, {}
    _read_twice(llm, inds, rated, label="indicators measured on your papers")
    names = [d["name"] for d in inds]
    cur = evaluate(rated, names)
    history, fails, settled, failed_on = [], 0, set(), {}
    for rnd in range(1, max_rounds + 1):
        if len(rated) < 3:
            break
        order_keys = {k for pair in cur["order"] for k in pair}
        missed = [i for i in range(len(rated)) if rated[i]["key"] not in settled and
                  (cur["err"][i] > FIT_TOL or i in order_keys)]
        if not missed:                       # every rated paper reproduced within FIT_TOL
            break
        # the worst miss first; a paper that resisted TRIES changes in a row gives way to the next one, so one
        # paper the clauses cannot reach does not end the loop while others are still off
        cand = [i for i in missed if failed_on.get(rated[i]["key"], 0) < TRIES]
        if not cand:
            break
        t = max(cand, key=lambda i: cur["err"][i])
        others = [j for j in range(len(rated)) if j != t]
        c = max(others, key=lambda j: abs(rated[j]["yours"] - rated[t]["yours"]) - abs(cur["pred"][j] - cur["pred"][t]))
        show = lambda i: dict(rated[i], pred=cur["pred"][i], levels={n: (None if rated[i]["x"].get(n) is None else  # noqa: E731
                                                                         round(5 * rated[i]["x"][n])) for n in names})
        tried = [h["change"] for h in history if h.get("change")]
        log.info("round %d of at most %d: improving the indicators (your scores reproduced within %.3f on average, worst %.3f)",
                 rnd, max_rounds, cur["mae"], cur["max"])
        e = llm.json(P.SYSTEM, P.edit(inds, show(t), show(c), tried))
        e = e if isinstance(e, dict) else {}
        step = {"round": rnd, "target": rated[t]["key"], "contrast": rated[c]["key"], "type": e.get("type", ""),
                "why": str(e.get("why") or "")[:400], "accepted": False, "mae_before": round(cur["mae"], 3)}
        trial = [_copy(r) for r in rated]
        new_inds = inds
        if e.get("type") == "misread" and e.get("name") in names:
            # a reading note on the indicator, applied to every paper: never a fix to one paper's level, which
            # could pull any paper onto the line and would leave the map papers read another way
            note = whole_note(e.get("check"))
            note, bad = _fixed(llm, note, names_banned) if note else ("", "no note")
            note = whole_note(note)
            desc = (_say(inds, f"reading note for {e['name']}", f"{e['name']}的读法") + f": {note}")[:300]
            if bad or desc in tried:
                step["note"] = f"not allowed: {bad}" if bad else "repeated"
                history.append(step)
                fails += 1
                failed_on[rated[t]["key"]] = failed_on.get(rated[t]["key"], 0) + 1
                continue
            step["change"] = desc
            new_inds = [dict(d, how=list(d.get("how") or []) + [note]) if d["name"] == e["name"] else d for d in inds]
            _read_twice(llm, [d for d in new_inds if d["name"] == e["name"]], trial)
        else:
            if e.get("rubric") and clause_problem(f"{e.get('name', '')} {e['rubric']}", list(names_banned)):
                e["rubric"] = _fixed(llm, str(e["rubric"]), names_banned)[0] or e["rubric"]
            new_inds, remeasure, desc = _apply(inds, e, cap, names_banned)
            if new_inds is None or desc in tried:
                bad = clause_problem(f"{e.get('name', '')} {e.get('rubric', '')}", list(names_banned))
                step["note"] = ("no general change proposed" if e.get("type") in ("none", "") else
                                f"not allowed: {bad}" if bad else "too many indicators, unusable or repeated")
                if e.get("type") == "none":
                    settled.add(rated[t]["key"])
                history.append(step)
                fails += 1
                failed_on[rated[t]["key"]] = failed_on.get(rated[t]["key"], 0) + 1
                continue
            step["change"] = desc[:300]
            old_name = None if e.get("type") == "add" else inds[int(e.get("line")) - 1]["name"]
            for r in trial:
                if old_name and (not remeasure or old_name != remeasure[0]):   # taken out, or renamed
                    _drop(r, old_name)
            if remeasure:
                _read_twice(llm, [d for d in new_inds if d["name"] in remeasure], trial)
        new_names = [d["name"] for d in new_inds]
        nxt = evaluate(trial, new_names)
        others_before = mean(cur["err"][j] for j in others)
        others_after = mean(nxt["err"][j] for j in others)
        beyond = lambda ev: sum(1 for x in ev["err"] if x > FIT_TOL)  # noqa: E731
        closer = (nxt["mae"] < cur["mae"] - margin or                      # closer to your scores on average,
                  (nxt["mae"] <= cur["mae"] and (beyond(nxt) < beyond(cur) or nxt["max"] < cur["max"] - 0.02)))
        ok = closer and others_after <= others_before + 0.01 and len(nxt["order"]) <= len(cur["order"])  # or fewer missed
        step.update(accepted=ok, mae_after=round(nxt["mae"], 3), order_before=len(cur["order"]), order_after=len(nxt["order"]))
        history.append(step)
        log.info("round %d: %s, %s (distance from your scores %.3f -> %.3f)", rnd, step.get("change", "")[:80],
                 "kept" if ok else "not kept", step["mae_before"], step["mae_after"])
        if ok:
            inds, names, cur, fails = new_inds, new_names, nxt, 0
            failed_on.pop(rated[t]["key"], None)
            for r, tr in zip(rated, trial):
                r.update(x=tr["x"], basis=tr["basis"], x1=tr["x1"], x2=tr["x2"])
        else:
            fails += 1
            failed_on[rated[t]["key"]] = failed_on.get(rated[t]["key"], 0) + 1
    return {"indicators": inds, "eval": cur, "history": history, "unexplained": sorted(settled)}


# ----------------------------------------------------------------------------- the whole procedure
def start_indicators(llm, rated: List[dict], language: str = "en", names_banned: List[str] = ()) -> List[dict]:
    """The general indicators, rewritten in the reader's terms, plus what the reader's reasons add. Wording that is
    not a condition on the paper is refused: a refused general indicator falls back to its general wording, a
    refused extra one is dropped."""
    defaults = DEFAULTS["zh" if str(language).lower().startswith("zh") else "en"]
    cap = min(MAX_INDICATORS, max(4, len(rated) - 2))
    res = llm.json(P.SYSTEM, P.indicators(defaults, rated, extra=max(0, min(3, cap - len(defaults)))))
    out = []
    for d in (res.get("indicators") if isinstance(res, dict) else []) or []:
        if not (isinstance(d, dict) and d.get("name") and d.get("rubric")) or d["name"] in [x["name"] for x in out]:
            continue
        row = {"name": " ".join(str(d["name"]).split())[:40], "rubric": " ".join(str(d["rubric"]).split()),
               "from": d.get("from") if d.get("from") in ("default", "reasons") else "reasons"}
        bad = clause_problem(f"{row['name']} {row['rubric']}", list(names_banned))
        if bad and not clause_problem(row["name"], list(names_banned)):
            row["rubric"], bad = _fixed(llm, row["rubric"], names_banned)
        if bad:
            base = next((x for x in defaults if x["name"] == row["name"]), None)
            log.info("indicator %s refused (%s)%s", row["name"], bad, "; general wording kept" if base else "")
            if base:
                out.append(dict(base, **{"from": "default"}))
            continue
        out.append(row)
    for base in defaults:                         # every general indicator stays
        if base["name"] not in [x["name"] for x in out]:
            out.insert(0, dict(base, **{"from": "default"}))
    return out[:cap]


# ----------------------------------------------------------------------------- the field: attention against the score
FIELD_ROUNDS = 6
FIELD_NEW = 2              # indicators the field may add, beyond those your scores ended with
MIN_FIELD = 8              # fewer papers with the attention measure than this: no fit to the field
MARGIN = 0.005             # a clause change is kept only if the checking half comes this much closer to y = x
RIDGE = 0.03               # the weights are pulled lightly towards every clause counting the same (relative to the
                           # levels' spread), so a weight the papers do not decide stays where step 1 left it
ORDER_EPS = 1e-3           # pairs you scored GAP apart keep at least this much between them


def _half(pid: str) -> int:
    """A paper's half, fixed by its id: one half proposes changes, the other checks them."""
    import hashlib
    return int(hashlib.md5(pid.encode("utf-8")).hexdigest(), 16) % 2


def _rows_x(rows: List[dict], rated: List[dict], names: List[str]) -> List[List[float]]:
    return [_matrix([{"x": r["x"]}] + rated, names)[0] for r in rows]


def _raw(x: List[float], w: List[float], b: float) -> float:
    return b + sum(a * c for a, c in zip(x, w))


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _solve(M: List[List[float]], v: List[float]) -> Optional[List[float]]:
    """M x = v by Gaussian elimination with partial pivoting; None when M is singular."""
    n = len(v)
    A = [list(M[i]) + [v[i]] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-15:
            return None
        A[c], A[p] = A[p], A[c]
        piv, row_c = A[c][c], A[c]
        for r in range(c + 1, n):
            f = A[r][c] / piv
            if f:
                row_r = A[r]
                for k in range(c, n + 1):
                    row_r[k] -= f * row_c[k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (A[r][n] - sum(A[r][k] * x[k] for k in range(r + 1, n))) / A[r][r]
    return x


def _span_basis(rows: List[List[float]]) -> List[List[float]]:
    """An orthonormal basis of the span of `rows` (Gram-Schmidt)."""
    Q: List[List[float]] = []
    for row in rows:
        r = _residual(row, Q)
        nr = math.sqrt(_dot(r, r))
        if nr > 1e-12:
            Q.append([v / nr for v in r])
    return Q


def _residual(row: List[float], Q: List[List[float]]) -> List[float]:
    r = list(row)
    for q in Q:
        c = _dot(r, q)
        r = [a - c * b for a, b in zip(r, q)]
    return r


def qp(H: List[List[float]], g: List[float], G: List[List[float]], h: List[float], z0: List[float],
       iters: int = 400) -> List[float]:
    """Minimise 1/2 z'Hz + g'z subject to G z >= h, starting from a z0 that meets every constraint (primal active
    set). H is positive definite, so the minimum is unique; every step keeps the constraints, so even if the method
    stops early the point returned meets them and is no worse than z0. The working set only ever holds independent
    constraints: one that depends on them cannot block a step that keeps them (it is held too), so it is never added;
    with n of them the point is a vertex and only the multipliers are left to check."""
    n, m = len(z0), len(G)
    z = list(z0)
    W: List[int] = []
    Q: List[List[float]] = []
    for _ in range(iters):
        q = [_dot(H[i], z) + g[i] for i in range(n)]
        k = len(W)
        # [H  -G_W'; G_W  d I] [p; lam] = [-q; 0]; the tiny d is only a safeguard
        K = [list(H[i]) + [-G[j][i] for j in W] for i in range(n)]
        K += [list(G[j]) + [1e-13 if jj == ii else 0.0 for jj in range(k)] for ii, j in enumerate(W)]
        sol = _solve(K, [-x for x in q] + [0.0] * k)
        if sol is None:
            break
        p, lam = sol[:n], sol[n:]
        if k >= n:
            p = [0.0] * n                        # a vertex: no direction keeps every working constraint
        if max(abs(x) for x in p) < 1e-7 * max(1.0, max(abs(x) for x in z)):
            if not W or min(lam) >= -1e-10:
                return z
            W.pop(min(range(k), key=lambda j: lam[j]))     # the constraint that holds the point back least
            Q = _span_basis([G[j] for j in W])
            continue
        steps = []
        for j in range(m):
            if j in W:
                continue
            d = _dot(G[j], p)
            if d < -1e-14:
                steps.append((max(0.0, (h[j] - _dot(G[j], z)) / d), j))
        alpha, block = 1.0, None
        for step, j in sorted(steps):
            if step >= 1.0:
                break
            r = _residual(G[j], Q)
            if math.sqrt(_dot(r, r)) > 1e-9 * max(1.0, math.sqrt(_dot(G[j], G[j]))):
                alpha, block = step, j
                break
        z = [a + alpha * c for a, c in zip(z, p)]
        if block is not None:
            W.append(block)
            Q = _span_basis([G[j] for j in W])
    return z


def _meets(z: List[float], G: List[List[float]], h: List[float], eps: float = 1e-7) -> bool:
    return all(_dot(row, z) >= hj - eps for row, hj in zip(G, h))


def tolerances(Xr: List[List[float]], yr: List[float], w: List[float], b: float) -> List[float]:
    """How far each rated paper may be from your score while the papers are brought towards y = x: FIT_TOL, or its
    miss under the line (w, b) when that is already larger (step 1's line, every clause counting the same: no paper
    is ever left further from your score than step 1 left it)."""
    return [max(FIT_TOL, abs(predict(x, w, b) - y)) for x, y in zip(Xr, yr)]


def constraints(Xr: List[List[float]], yr: List[float], tol: List[float], k: int,
                start: List[float], ref: Optional[List[float]] = None) -> Tuple[List[List[float]], List[float]]:
    """Your scores as linear constraints G z >= h on z = (w_1 .. w_k, b): each rated paper's score within its
    tolerance of yours (a side the clipping to 0..1 already meets is left out: above 1 the score is 1), every pair you
    scored GAP apart in your order (a pair step 1 already had the wrong way round may not get worse: as with a miss
    beyond FIT_TOL, step 2 never leaves your scores worse than step 1 did; `ref`, step 1's raw scores of your papers,
    says which way each pair was, else `start`), the weights >= 0 and their sum at most MAX_SLOPE."""
    G: List[List[float]] = []
    h: List[float] = []
    for j in range(k):
        G.append([1.0 if i == j else 0.0 for i in range(k)] + [0.0])
        h.append(0.0)
    G.append([-1.0] * k + [0.0])
    h.append(-max(MAX_SLOPE, sum(start[:k])))   # the start's own sum may round a hair above the cap
    for x, y, t in zip(Xr, yr, tol):
        a = list(x) + [1.0]
        if y - t > 0:
            G.append(a)
            h.append(y - t)
        if y + t < 1:
            G.append([-c for c in a])
            h.append(-(y + t))
    for i in range(len(yr)):
        for j in range(len(yr)):
            if yr[i] - yr[j] >= GAP - 1e-9:
                d = [p - q for p, q in zip(Xr[i], Xr[j])] + [0.0]
                if not any(abs(v) > 1e-12 for v in d):
                    continue                     # the same levels: no weights can order them, nothing to hold
                gap = (ref[i] - ref[j]) if ref is not None else _dot(d, start)
                G.append(d)
                h.append(min(ORDER_EPS, gap))
    return G, h


def _with_b(Xr: List[List[float]], yr: List[float], tol: List[float], w: List[float]) -> Optional[float]:
    """An intercept that puts every rated paper within its tolerance with these weights, or None."""
    lo, hi = -1e9, 1e9
    for x, y, t in zip(Xr, yr, tol):
        s = _dot(x, w)
        if y - t > 0:
            lo = max(lo, y - t - s)
        if y + t < 1:
            hi = min(hi, y + t - s)
    if lo > hi:
        return None
    b = mean(y - _dot(x, w) for x, y in zip(Xr, yr)) if yr else 0.5
    return min(hi, max(lo, b))


def _phase1(G: List[List[float]], h: List[float], k: int, guess: List[float]) -> Optional[List[float]]:
    """A point that meets every constraint, found from `guess` when it does not (the textbook first phase): minimise
    t^2 over (z, t) with G z + t >= h + d on your papers' rows (d a hair, so a tiny leftover t still meets them),
    w >= 0 and the slope cap kept as they are (the guess meets those), and z pulled faintly towards the guess. A
    point that meets them exists when the minimum t is within d; the constraints themselves decide. None otherwise."""
    n, m0, d = k + 1, k + 1, 1e-6
    G2 = [list(row) + [0.0] for row in G[:m0]] + [list(row) + [1.0] for row in G[m0:]] + [[0.0] * n + [1.0]]
    h2 = list(h[:m0]) + [hj + d for hj in h[m0:]] + [0.0]
    z0 = list(guess) + [max([0.0] + [h2[j] - _dot(G[j], guess) for j in range(m0, len(G))]) + 1e-9]
    if not _meets(z0, G2, h2):
        return None
    eps = 1e-8
    H = [[(2 * eps if i < n else 2.0) if i == j else 0.0 for j in range(n + 1)] for i in range(n + 1)]
    g = [-2 * eps * v for v in guess] + [0.0]
    z = qp(H, g, G2, h2, z0)
    return z[:n] if _meets(z[:n], G, h) else None


def fit_weights(Xr: List[List[float]], yr: List[float], tol: List[float], Xc: List[List[float]], tc: List[float],
                wc: List[float], center: Tuple[List[float], float],
                starts: List[Tuple[List[float], float]], order: Optional[List[float]] = None
                ) -> Optional[Tuple[List[float], float]]:
    """How every paper is scored: b + sum_k w_k x_k (clipped to 0..1), w_k >= 0. The objective is y = x: the papers
    you have not rated, as close to their attention as possible (sum of reliability * (score - attention)^2). The
    constraint is your scores: each rated paper within its tolerance of your score and every pair you scored GAP
    apart kept in order (constraints). The weights are pulled lightly towards `center`, every clause counting the
    same, so those the papers do not decide stay there. `order`: step 1's raw scores of your papers, which say which
    way each pair was (default: under `center`). `starts`: points to begin from, the first that meets the constraints is used; when none does, one
    is searched for (_phase1). None only when no point meets your scores."""
    k = len(center[0])
    ref = list(center[0]) + [center[1]]
    G, h = constraints(Xr, yr, tol, k, ref, order)
    start = None
    for w_s, b_s in starts:
        if w_s is None or b_s is None or len(w_s) != k:
            continue
        z = list(w_s) + [b_s]
        if _meets(z, G, h):
            start = z
            break
    if start is None:
        start = _phase1(G, h, k, ref)
    if start is None:
        return None
    if not Xc:
        return start[:k], start[k]
    n = k + 1
    tot = sum(wc) or 1.0
    mk = [sum(a * x[j] for a, x in zip(wc, Xc)) / tot for j in range(k)]
    energy = sum(a * (x[j] - mk[j]) ** 2 for a, x in zip(wc, Xc) for j in range(k)) / k
    mu = RIDGE * (energy if energy > 0 else tot)
    zc = list(center[0]) + [center[1]]
    pull = [mu if j < k else mu * 1e-4 for j in range(n)]     # the intercept is free (a touch keeps H positive definite)
    rows = [list(x) + [1.0] for x in Xc]

    def build(keep: List[int]):
        H = [[0.0] * n for _ in range(n)]
        g = [0.0] * n
        for c in keep:
            a, row, t = wc[c], rows[c], tc[c]
            for i in range(n):
                g[i] -= 2 * a * t * row[i]
                ai = 2 * a * row[i]
                Hi = H[i]
                for j in range(n):
                    Hi[j] += ai * row[j]
        for j in range(n):
            H[j][j] += 2 * pull[j]
            g[j] -= 2 * pull[j] * zc[j]
        return H, g

    def drawn(z: List[float]) -> float:
        """The objective on the scores as drawn, clipped to 0..1, with the pull towards every clause counting the same."""
        return (sum(a * (min(1.0, max(0.0, _dot(row, z))) - t) ** 2 for a, row, t in zip(wc, rows, tc))
                + sum(p * (v - c) ** 2 for p, v, c in zip(pull, z, zc)))
    H, g = build(list(range(len(rows))))
    z = qp(H, g, G, h, start)
    if not _meets(z, G, h, 1e-6) or drawn(z) > drawn(start) + 1e-12:
        log.warning("the weights could not be fitted towards y = x (the solver did not settle); kept where they started")
        z = start
    # a paper whose score is past 0 or 1 is drawn at the end, so moving it further out costs nothing: fit again without
    # those papers' raw distance, and keep the result while the objective on the scores as drawn goes down
    for _ in range(4):
        past = {c for c, row in enumerate(rows) if not 0.0 <= _dot(row, z) <= 1.0}
        if not past:
            break
        H2, g2 = build([c for c in range(len(rows)) if c not in past])
        z2 = qp(H2, g2, G, h, z)
        if not _meets(z2, G, h, 1e-6) or drawn(z2) >= drawn(z) - 1e-12:
            break
        z = z2
    return [max(0.0, v) for v in z[:k]], z[k]


def _dist(preds: Dict[str, float], targets: Dict[str, float], wts: Dict[str, float], ids: List[str]) -> float:
    """Distance from y = x, straight up or down on the chart (scores as drawn, 0..1), root mean square, each paper
    weighted by how reliable its attention is: the quantity the weights are fitted to, so what is fitted, kept and
    reported is one number."""
    tot = sum(wts[i] for i in ids)
    return math.sqrt(sum(wts[i] * (preds[i] - targets[i]) ** 2 for i in ids) / tot) if tot else 0.0


def toward_line(rated: List[dict], cands: List[dict], names: List[str], tol: List[float], targets: Dict[str, float],
                wts: Dict[str, float], prev: Optional[List[float]] = None, s1: Optional[List[float]] = None) -> Optional[dict]:
    """Every paper scored by one set of weights, fitted towards y = x within your scores (fit_weights). How close it
    gets, measured honestly: each half of the papers under the weights fitted to the other half only, so a paper's
    own attention never decides whether a change counts as an improvement. `prev`: the weights so far, one more point
    to start from. Returns {"w", "b", "pred_c", "pred_r", "err", "mae", "order", "dist", "err_A", "err_B"}, or None
    when your scores can no longer be met."""
    Xr, yr = _matrix(rated, names), [r["yours"] for r in rated]
    xc = {c["id"]: x for c, x in zip(cands, _rows_x(cands, rated, names))}
    half = {c["id"]: c["half"] for c in cands}
    w_eq, b_eq = fit_scale(Xr, yr)
    starts = [(w_eq, b_eq), (w_eq, _with_b(Xr, yr, tol, w_eq))]
    if prev is not None and len(prev) == len(names):
        starts.append((prev, _with_b(Xr, yr, tol, prev)))
    ids = [c["id"] for c in cands if c["id"] in targets]

    def fit(sub: List[str]):
        return fit_weights(Xr, yr, tol, [xc[i] for i in sub], [targets[i] for i in sub], [wts[i] for i in sub],
                           (w_eq, b_eq), starts, s1)
    full = fit(ids)
    if full is None:
        return None
    w, b = full
    other = {hf: fit([i for i in ids if half[i] != hf]) or full for hf in (0, 1)}
    pred_c = {i: predict(x, w, b) for i, x in xc.items()}
    pred_r = [predict(x, w, b) for x in Xr]
    errs = [abs(p - t) for p, t in zip(pred_r, yr)]

    def err(hf: int) -> float:
        sub = [i for i in ids if half[i] == hf]
        return _dist({i: predict(xc[i], *other[hf]) for i in sub}, targets, wts, sub)
    # the proposing half (0) as scored by weights fitted to it alone: what the model is shown and the paper it is
    # asked about are chosen from these, so the checking half has no say in the proposal
    own0 = {i: predict(xc[i], *other[1]) for i in ids if half[i] == 0}
    return {"w": w, "b": b, "pred_c": pred_c, "pred_r": pred_r, "err": errs, "mae": mean(errs) if errs else 0.0,
            "order": order_errors(yr, pred_r), "dist": _dist(pred_c, targets, wts, ids), "err_A": err(0), "err_B": err(1),
            "own0": own0}


def _state(cur: dict) -> dict:
    return {"dist": round(cur["dist"], 3), "err_A": round(cur["err_A"], 3), "err_B": round(cur["err_B"], 3),
            "mae": round(cur["mae"], 3)}


def _field_change(inds: List[dict], e: dict, cap: int, banned: List[str], tried: List[str], added: int, llm=None):
    """(new indicators, the indicator to measure again, a description, why it is refused or "")."""
    names = [d["name"] for d in inds]
    if llm is not None and e.get("rubric") and clause_problem(f"{e.get('name', '')} {e['rubric']}", list(banned)):
        e["rubric"] = _fixed(llm, str(e["rubric"]), banned)[0] or e["rubric"]
    if e.get("type") == "misread" and e.get("name") in names:
        note = whole_note(e.get("check"))
        note, bad = _fixed(llm, note, banned) if (note and llm is not None) else (note, clause_problem(note, list(banned)) if note else "no note")
        note = whole_note(note)
        desc = (_say(inds, f"reading note for {e['name']} (from the field)", f"{e['name']}的读法（来自领域）") + f": {note}")[:300]
        if bad or desc in tried:
            return None, "", desc, (f"not allowed: {bad}" if bad else "repeated")
        new = [dict(d, how=list(d.get("how") or []) + [note], how_from=list(d.get("how_from") or ["you"] * len(d.get("how") or [])) + ["field"])
               if d["name"] == e["name"] else d for d in inds]
        return new, e["name"], desc, ""
    if e.get("type") == "remove":          # a clause the papers do not need gets no weight; it is never taken out
        return None, "", "", "the field may not take out a clause"
    if e.get("type") == "add" and added >= FIELD_NEW:
        return None, "", "", "the field may add at most %d indicators" % FIELD_NEW
    new, remeasure, desc = _apply(inds, e, cap, banned)
    desc = desc + _say(inds, " (from the field)", "（来自领域）") if desc else desc
    if new is None or desc[:300] in tried:
        bad = clause_problem(f"{e.get('name', '')} {e.get('rubric', '')}", list(banned))
        return None, "", desc, ("no general change proposed" if e.get("type") in ("none", "") else
                                f"not allowed: {bad}" if bad else "repeated" if new is not None else
                                "too many indicators or unusable")
    new = [dict(d, **{"from": "field"}) if d["name"] == remeasure[0] else d for d in new]
    return new, remeasure[0], desc, ""


def _att_txt(c: dict, metric: str, pos: dict) -> str:
    m = c.get("m") or {}
    if metric == "cumulative" and m.get("scale") == "log" and m.get("cumulative") is not None:
        return (f"{m['cumulative']:.1f} citations a year" +
                (f", {m['citations']} in all" if m.get("citations") is not None else ""))
    if metric == "cumulative" and m.get("cumulative") is not None:
        return f"ranked {100 * m['cumulative']:.0f}% of the way up among the works seen in this run"
    return f"ranked {100 * pos.get('rank', 0.5):.0f}% of the way up among these papers by {metric} attention"


def field_phase(llm, rated: List[dict], cands: List[dict], inds: List[dict], ev1: dict, metric: str,
                banned: List[str], max_rounds: int = FIELD_ROUNDS, anchors: Optional[Dict[str, list]] = None,
                top: Optional[Dict[str, float]] = None) -> dict:
    """Bring every paper you have not rated towards y = x: its score (the clauses' levels, weighted) against the
    field's attention (attention.position). The objective is the papers' distance from y = x; your scores are the
    constraint: each rated paper stays within FIT_TOL of your score (or within step 1's miss, if that was larger) and
    no pair you scored GAP apart changes order.
    Two levers. The weights: fitted to the objective directly (fit_weights), starting from every clause counting the
    same. The clauses: the field may rewrite or annotate one, or add up to FIELD_NEW of its own; a change is proposed
    from one half of the papers and kept only if, with the weights fitted again, the other half comes closer to y = x
    under weights fitted without it. What stays far from y = x is a real difference of taste."""
    from tastecal.taste import attention as A
    names = [d["name"] for d in inds]
    cap = len(inds) + FIELD_NEW
    Xr, yr = _matrix(rated, names), [r["yours"] for r in rated]
    w0, b0 = fit_scale(Xr, yr)                               # step 1's line: every clause counts the same
    tol = tolerances(Xr, yr, w0, b0)
    s1 = [_raw(x, w0, b0) for x in Xr]                       # and its scores: which way each pair was
    s0 = {c["id"]: predict(x, w0, b0) for c, x in zip(cands, _rows_x(cands, rated, names))}
    pos = A.position([{"id": c["id"], "m": c["m"]} for c in cands], metric, s0, (anchors or {}).get(metric, []),
                     (top or {}).get(metric))
    tg = [c for c in cands if c["id"] in pos]
    if len(tg) < MIN_FIELD:
        return {"skipped": f"{len(tg)} papers with this attention measure (at least {MIN_FIELD} are needed)",
                "indicators": inds, "metric": metric}
    targets = {c["id"]: pos[c["id"]]["x"] for c in tg}
    wts = {c["id"]: (c["m"] or {}).get("rel", 1.0) for c in tg}
    log.info("fitting every paper towards y = x (%s) on %d papers you have not rated", metric, len(tg))
    equal = {"dist": round(_dist(s0, targets, wts, list(targets)), 3), "mae": round(ev1["mae"], 3)}
    cur = toward_line(rated, cands, names, tol, targets, wts, s1=s1)
    if cur is None:                       # cannot happen: step 1's line meets the tolerances by construction
        return {"skipped": "your scores could not be met", "indicators": inds, "metric": metric}
    fitted = _state(cur)
    log.info("weights fitted: distance from y = x %.3f -> %.3f, your scores within %.3f on average",
             equal["dist"], cur["dist"], cur["mae"])
    history, added = [], 0
    failed_on: Dict[str, int] = {}
    if min(sum(1 for c in tg if c["half"] == hf) for hf in (0, 1)) < 2:
        log.info("too few papers in one half to propose and check clause changes: the weights alone are fitted")
        max_rounds = 0
    for rnd in range(1, max_rounds + 1):
        half_a = [c for c in tg if c["half"] == 0]
        own = cur["own0"]                        # the proposing half, scored by weights fitted to it alone
        resid = {c["id"]: own[c["id"]] - targets[c["id"]] for c in half_a}
        # the paper furthest from y = x first; one the model finds nothing to change for, or that resisted TRIES
        # changes in a row, gives way to the next one (as in the first loop)
        open_ = [c for c in half_a if failed_on.get(c["id"], 0) < TRIES]
        if not open_:
            break
        t = max(open_, key=lambda c: wts[c["id"]] * abs(resid[c["id"]]))
        c2 = max((c for c in half_a if c is not t),
                 key=lambda c: abs(targets[c["id"]] - targets[t["id"]]) - abs(own[c["id"]] - own[t["id"]]))
        show = lambda c: {"pred": own[c["id"]], "target": targets[c["id"]], "summary": c["summary"],  # noqa: E731
                          "attention_txt": _att_txt(c, metric, pos.get(c["id"], {})),
                          "levels": {n: (None if c["x"].get(n) is None else round(5 * c["x"][n])) for n in names}}
        tried = [h["change"] for h in history if h.get("change")]
        log.info("field round %d of at most %d (checking half, distance from y = x: %.3f)", rnd, max_rounds, cur["err_B"])
        e = llm.json(P.SYSTEM, P.field_edit(inds, show(t), show(c2), tried))
        e = e if isinstance(e, dict) else {}
        step = {"phase": "field", "round": rnd, "target": t["id"], "contrast": c2["id"], "type": e.get("type", ""),
                "why": str(e.get("why") or "")[:400], "accepted": False, "err_before": round(cur["err_B"], 3),
                "mae_before": round(cur["mae"], 3)}
        new_inds, name, desc, refused = _field_change(inds, e, cap, banned, tried, added, llm)
        if refused:
            step["note"] = refused
            history.append(step)
            failed_on[t["id"]] = TRIES if e.get("type") in ("none", "") else failed_on.get(t["id"], 0) + 1
            continue
        step["change"] = desc[:300]
        new_names = [d["name"] for d in new_inds]
        one = [d for d in new_inds if d["name"] == name]
        old_name = None
        if e.get("type") == "rewrite":
            try:
                old_name = inds[int(e.get("line")) - 1]["name"]
            except (TypeError, ValueError, IndexError):
                old_name = None

        # measured as in the rest of the fit: your papers twice, side by side, in both orders; the other papers in
        # batches with a few of yours (on the changed clause too) as the standard
        trial_r = [_copy(r) for r in rated]
        for r in trial_r:
            if old_name and old_name != name:
                _drop(r, old_name)
        _read_twice(llm, one, trial_r, label="the change measured on your papers")
        same = not (old_name and old_name != name)       # the clause keeps its name: a paper the reply leaves out
        for r, tr in zip(rated, trial_r):                 # keeps the level it had
            if same and tr["x"].get(name) is None and r["x"].get(name) is not None:
                for k_ in ("x", "x1", "x2", "basis"):
                    if name in (r.get(k_) or {}):
                        tr[k_][name] = r[k_][name]
        got = measure(llm, one, {c["id"]: c["notes"] for c in cands}, label="papers measured on the change (batches)",
                      refs=_refs(trial_r, new_names))
        trial_c = []
        for c in cands:
            c2_ = _copy(c)
            if not same:
                _drop(c2_, old_name)
            g_ = got.get(c["id"]) or {}
            v_ = (g_.get("x") or {}).get(name)
            if v_ is not None or not same:
                c2_["x"][name] = v_
                c2_["basis"][name] = (g_.get("basis") or {}).get(name, "")
            trial_c.append(c2_)
        w_of = dict(zip(names, cur["w"]))
        if old_name and old_name != name:
            w_of[name] = w_of.get(old_name, 0.0)
        nxt = toward_line(trial_r, trial_c, new_names, tol, targets, wts, prev=[w_of.get(n, 0.0) for n in new_names], s1=s1)
        if nxt is None:
            step.update(note="your scores could no longer be met", err_after=None)
            history.append(step)
            log.info("field round %d: %s, not kept (your scores could no longer be met)", rnd, desc[:80])
            failed_on[t["id"]] = failed_on.get(t["id"], 0) + 1
            continue
        # the checking half must come closer; the proposing half may not get worse (each under weights fitted
        # without it)
        ok = (nxt["err_B"] < cur["err_B"] - MARGIN and nxt["err_A"] <= cur["err_A"] + 1e-9
              and len(nxt["order"]) <= len(cur["order"]))      # and no pair you ordered turned round
        step.update(accepted=ok, err_after=round(nxt["err_B"], 3), mae_after=round(nxt["mae"], 3))
        history.append(step)
        log.info("field round %d: %s, %s (checking half %.3f -> %.3f)", rnd, desc[:80], "kept" if ok else "not kept",
                 cur["err_B"], nxt["err_B"])
        if ok:
            inds, names, cur = new_inds, new_names, nxt
            added += 1 if e.get("type") == "add" else 0
            for r, tr in zip(rated, trial_r):
                r.update(x=tr["x"], basis=tr["basis"], x1=tr["x1"], x2=tr["x2"])
            for c, tc in zip(cands, trial_c):
                c["x"], c["basis"] = tc["x"], tc["basis"]
            failed_on.pop(t["id"], None)
        else:
            failed_on[t["id"]] = failed_on.get(t["id"], 0) + 1
    return {"indicators": inds, "history": history, "field_names": [d["name"] for d in inds if d.get("from") == "field"],
            "targets": targets, "weights": wts, "tol": tol, "s1": s1, "lam": ev1["lam"], "metric": metric, "papers": len(tg),
            "equal": equal, "start": fitted, "end": _state(cur), "pos": pos, "w_end": dict(zip(names, cur["w"]))}


def confidence(errs: List[float], order: int, tol: float = FIT_TOL) -> dict:
    """How far to trust the chart, as numbers, not a verdict (no threshold would hold as the rated papers grow): how
    far the clauses miss your own scores, root mean square ("rms": the larger, the less the clauses hold your taste and
    the less the chart can be trusted), the worst miss, how many miss by more than the loop's tolerance, and pairs
    out of order."""
    n = len(errs)
    rms = math.sqrt(mean(e * e for e in errs)) if errs else 0.0
    return {"rms": round(rms, 3), "worst": round(max(errs) if errs else 0.0, 3), "n": n,
            "beyond": sum(1 for e in errs if e > tol + 1e-3), "order": order}


def _refs(rated: List[dict], names: List[str], k: int = REFS) -> List[tuple]:
    """A few of your rated papers, spread over your scores, with their measured levels: the standard the others are
    measured against. Your scores themselves are never shown."""
    rows = sorted(rated, key=lambda r: r["yours"])
    if len(rows) > k:
        rows = [rows[round(i * (len(rows) - 1) / (k - 1))] for i in range(k)]
    return [(r["summary"], {n: (None if r["x"].get(n) is None else round(5 * r["x"][n])) for n in names}) for r in rows]


def views(cands: List[dict], preds: Dict[str, float], unsure: Dict[str, float], far: float,
          anchors: Optional[Dict[str, list]] = None, top: Optional[Dict[str, float]] = None,
          fixed: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
    """Each attention measure against your score: every paper's attention on your scale (with its bar), and the
    papers off y = x by more than the allowed distance plus their two bars: above it, high on your line and little
    attended ("gem"); below it, much attended and low on your line ("hyped"). Sorted by how far beyond. A paper under
    YOUNG months old is never listed: its citations say too little yet ("young")."""
    from tastecal.taste import attention as A
    out = {}
    for metric in A.METRICS:
        if fixed and metric in fixed:           # the positions the fit aimed at (by rank, they depend on the scores)
            pos = {c["id"]: fixed[metric][c["id"]] for c in cands if c["id"] in fixed[metric]}
        else:
            pos = A.position([{"id": c["id"], "m": c.get("m") or {}} for c in cands], metric, preds,
                             (anchors or {}).get(metric, []), (top or {}).get(metric))
        if len(pos) < 4:
            continue
        gem, hyped = {}, {}
        age = {c["id"]: (c.get("m") or {}).get("months") for c in cands}
        young = [i for i in pos if age.get(i) is not None and age[i] < YOUNG]
        for i, q in pos.items():
            if i in young:
                continue
            gap = preds[i] - q["x"]
            allowed = far + (q["hi"] - q["lo"]) / 2 + unsure.get(i, 0) / 2
            if gap > allowed:
                gem[i] = gap - allowed
            elif -gap > allowed:
                hyped[i] = -gap - allowed
        out[metric] = {"pos": pos, "gem": sorted(gem, key=lambda i: -gem[i]), "hyped": sorted(hyped, key=lambda i: -hyped[i]),
                       "far": far, "n": len(pos), "young": young}
    return out


def saved_clauses(path: str, language: str) -> Optional[dict]:
    """The clauses a previous fit ended with, for this language: {"indicators", "saved", "from", "trust"} or None."""
    import json
    import os
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.warning("could not read the saved clauses in %s: %s", path, e)
        return None
    got = (data or {}).get(_lang_key(language))
    if not (isinstance(got, dict) and got.get("indicators")):
        return None
    # notes an older fit cut in the middle of a sentence end at their last whole sentence
    got["indicators"] = [dict(d, how=[_mended(h) for h in d["how"]]) if isinstance(d, dict) and isinstance(d.get("how"), list)
                         else d for d in got["indicators"]]
    return got


def save_clauses(path: str, language: str, res: dict, source: str = "") -> None:
    """Keep the clauses this fit ended with, per language, as the start of the next fit (on any map): your taste does
    not change with the map, so what one run learned is not thrown away by the next."""
    import json
    import os
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except (OSError, ValueError):
            data = {}
    keep = ("name", "rubric", "from", "how", "how_from")
    data[_lang_key(language)] = {
        "indicators": [{k: d[k] for k in keep if k in d} for d in res.get("indicators") or []],
        "saved": date.today().isoformat(), "from": source,
        "trust": (res.get("confidence") or {}).get("rms"), "rated": len(res.get("rated") or [])}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _lang_key(language: str) -> str:
    return "zh" if str(language or "").lower().startswith("zh") else "en"


def run(llm, graph: dict, rated_in: List[dict], works: Optional[List[str]] = None,
        extra: Optional[List[dict]] = None, attention: Optional[Dict[str, dict]] = None,
        sample: Optional[List[dict]] = None, years: int = YEARS, start: Optional[dict] = None,
        anchor: Optional[dict] = None) -> dict:
    """`extra`: rated papers outside the run, already read in full (read_rated). `attention`: raw counts per node
    id (attention.fetch); without it the run's own attention percentile is used where there is one. `sample`: works
    drawn at random from the neighbourhood and read in full, compared alongside the map's (they are not chosen by
    how much they are cited). `anchor`: raw counts of Attention Is All You Need (attention.ANCHOR_NODE), the top of the
    attention scale."""
    from tastecal.taste import attention as A
    language = (graph.get("meta") or {}).get("language", "en")
    as_of = str((graph.get("meta") or {}).get("generated_at") or "")[:10] or date.today().isoformat()
    rated, skipped = rated_works(graph, rated_in, extra)
    # concept works (definitions, taxonomies, terminology) are not scored, like surveys: found once for your rated
    # papers and the papers to compare
    by_node = {n["id"]: n for n in list(graph.get("nodes", [])) + list(extra or [])}
    rated_nodes = {r["node"] for r in rated if r["node"]}
    from tastecal.core.model import title_similarity
    rated_titles = [t for t in [r.get("title") for r in rated] + [s_.get("title") or s_.get("ref") for s_ in skipped] if t]

    def yours(n: dict) -> bool:
        """One of your rated papers, under whatever id the map or the sample gives it: never compared as a paper you
        have not rated (it would be pulled towards y = x, away from your own score)."""
        return n["id"] in rated_nodes or any(title_similarity(n.get("title", ""), t) > 0.85 for t in rated_titles)
    pool = [n for n in graph.get("nodes", []) if readable(n) and not yours(n) and is_method(n)]
    if works:
        pool = [n for n in pool if n["id"] in set(works)]
    drawn_in = [n for n in (sample or []) if readable(n) and is_method(n) and not yours(n)
                and n["id"] not in {p["id"] for p in pool}]
    items = ([("rated:" + str(r["key"]), _type_text(r["title"], by_node.get(r["node"]), r.get("summary") or r.get("notes", "")[:600]))
              for r in rated] + [(n["id"], _type_text(n.get("title", ""), n)) for n in pool + drawn_in])
    concept = concept_works(llm, items) if items else set()
    for r in [r for r in rated if "rated:" + str(r["key"]) in concept]:
        rated.remove(r)
        skipped.append({"key": r["key"], "ref": r.get("ref") or r["title"], "yours": r["yours"], "comment": r.get("comment", ""),
                        "why": "not a method paper", "type": "concept", "node": r["node"], "title": r["title"]})
    if concept:
        log.info("not scored, concept works (definitions, taxonomies, terminology): %d", len(concept))
    if len(rated) < 3:
        return {"error": "at least three rated papers with a full-text reading are needed", "skipped": skipped}
    banned = paper_names(graph, rated)
    inds0 = []
    if start:                                    # where the last fit ended: the clauses carry over from map to map
        for d in start.get("indicators") or []:
            if not (isinstance(d, dict) and d.get("name") and d.get("rubric")):
                continue
            d = dict(d)
            if clause_problem(f"{d['name']} {d['rubric']}", banned):       # names a paper of this map: rewrite once
                d["rubric"] = _fixed(llm, d["rubric"], banned)[0]
                if not d["rubric"]:
                    continue
            inds0.append(d)
        if inds0:
            log.info("starting from the %d clauses saved on %s (from %s)", len(inds0), start.get("saved", "?"),
                     start.get("from") or "an earlier fit")
    if not inds0:
        log.info("writing the indicators from your %d rated papers and their reasons", len(rated))
        inds0 = start_indicators(llm, rated, language, banned)
    cal = calibrate(llm, rated, inds0, names_banned=banned)
    inds, ev1 = cal["indicators"], cal["eval"]
    names = [d["name"] for d in inds]

    # the papers you have not rated: every method paper on the map read in full, and the random sample
    pool = [n for n in graph.get("nodes", []) if readable(n) and n["id"] not in rated_nodes]
    if works:
        pool = [n for n in pool if n["id"] in set(works)]
    pool = [dict(n, fit_type="concept") if n["id"] in concept else n for n in pool]
    others = [n for n in pool if not is_method(n)]
    pool = [n for n in pool if not yours(n)]
    old = [n for n in pool if is_method(n) and not recent(n, as_of, years)]
    pool = [n for n in pool if is_method(n) and recent(n, as_of, years)]
    drawn = [dict(n, sample="random") for n in drawn_in if n["id"] not in concept and recent(n, as_of, years)]
    pool += drawn
    log.info("measuring %d papers you have not rated on your indicators (%d drawn at random)", len(pool), len(drawn))
    got = measure(llm, inds, {n["id"]: notes(n) for n in pool}, label="papers measured (batches)", refs=_refs(rated, names))
    cands = []
    for n in pool:
        g_ = got.get(n["id"])
        if not g_:
            continue
        cands.append({"id": n["id"], "node": n, "notes": notes(n), "summary": notes(n, short=True)[:700],
                      "x": dict(g_["x"]), "basis": dict(g_["basis"]), "half": _half(n["id"]),
                      "m": A.measures(n, (attention or {}).get(n["id"]), as_of)})
    # your rated papers' attention: never used for their own place (on y = x at your score). The scale's top end is
    # Attention Is All You Need (+3 sigma; no citation is -3 sigma), looked up in every run (`anchor`, or one of your
    # rated papers when it is that paper); without it, the most attended paper known
    rated_m = {r["key"]: A.measures(by_node.get(r["node"]) or {"date": ""}, (attention or {}).get(r["node"]), as_of)
               for r in rated if r.get("node")}
    anchor_m = A.measures(A.ANCHOR_NODE, anchor, as_of) if anchor else None
    if anchor_m is None:
        from tastecal.core.model import title_similarity
        same = [k for k, r in ((r["key"], r) for r in rated) if title_similarity(r["title"], A.ANCHOR_TITLE) >= 0.9]
        anchor_m = rated_m.get(same[0]) if same else None
    att_source = (A.unify([c["m"] for c in cands], list(rated_m.values()) + ([anchor_m] if anchor_m else []))
                  if cands else "")
    titles = {r["key"]: r["title"] for r in rated}
    anchors, tops, top_of = _anchoring([(titles[k], m) for k, m in rated_m.items()], cands, anchor_m, att_source)
    if cands and att_source == "citations a year" and A.FIT_METRIC not in tops:
        log.warning("%s could not be looked up: the most cited paper known (%s) is the top of the attention scale",
                    A.ANCHOR_TITLE, top_of.get(A.FIT_METRIC, "?"))

    # the field: every paper as close to y = x as your scores allow
    field = (field_phase(llm, rated, cands, inds, ev1, A.FIT_METRIC, banned, anchors=anchors, top=tops) if cands
             else {"skipped": "no papers", "indicators": inds})
    inds = field["indicators"]
    names = [d["name"] for d in inds]
    once = [d for d in inds if any(d["name"] not in (r.get("x2") or {}) for r in rated)]
    if once:                                     # a clause the field changed: your papers read on it a second time
        log.info("measuring your rated papers a second time on %d clauses the field changed", len(once))
        again = measure_side_by_side(llm, once, {r["key"]: r["notes"] for r in rated}, reverse=True,
                                     label="clauses measured again on your papers")
        for r in rated:
            for d in once:
                n = d["name"]
                _set_reads(r, n, (r.get("x1") or {}).get(n), ((again.get(r["key"]) or {}).get("x") or {}).get(n),
                           r["basis"].get(n, ""))
    for r in rated:                              # what the page shows of your papers: attention, venue, authors
        r["m"] = rated_m.get(r["key"])
        n_ = by_node.get(r.get("node")) or {}
        r.update({k: n_[k] for k in ("venue", "authors", "year") if n_.get(k)})
    sc = _score(rated, cands, inds, field, field.get("lam", ev1["lam"]))
    map_rows, w, b, combined = sc["map_rows"], sc["w"], sc["b"], sc["combined"]
    map_rows.sort(key=lambda r: -r["pred"])
    k = max(3, round(len(map_rows) * 0.1))
    ends = map_rows[:k] + (map_rows[-k:] if len(map_rows) > k else [])
    by_c = {c["id"]: c for c in cands}

    # the works at both ends are measured again next to the rated paper with the closest profile, so each condition
    # is applied to both the same way; a work whose levels change is re-predicted
    def closest(r: dict) -> dict:
        return min(rated, key=lambda q: sum((_matrix([{"x": r["x"]}] + rated, names)[0][j] - _matrix([q] + rated, names)[0][j]) ** 2
                                            for j in range(len(names))))

    def again_next_to(r: dict):
        ref = closest(r)
        ref_levels = {n: (None if ref["x"].get(n) is None else round(5 * ref["x"][n])) for n in names}
        return ref, llm.json(P.SYSTEM, P.consistent(inds, "REF", ref["notes"], ref_levels, r["id"], by_c[r["id"]]["notes"]))
    if ends:
        log.info("measuring the %d papers at both ends again, next to the rated paper closest to each", len(ends))
    for r, (ref, res2) in zip(ends, _parallel(again_next_to, ends, "papers at the ends re-measured")):
        lv = ((res2.get("works") or [{}])[0].get("levels") if isinstance(res2, dict) and res2.get("works") else {}) or {}
        new_x = {n: _level((lv.get(n) or {}).get("level")) for n in names}
        if any(v is not None for v in new_x.values()):
            changed = [n for n in names if new_x.get(n) is not None and r["x"].get(n) is not None
                       and abs(new_x[n] - r["x"][n]) > 0.25]
            r["recheck"] = {"against": ref["title"], "changed": changed}
            if changed:
                r["x"] = {n: (new_x[n] if new_x.get(n) is not None else r["x"].get(n)) for n in names}
                r["basis"].update({n: str((lv.get(n) or {}).get("basis") or "")[:260] for n in changed})
                xm = _matrix([{"x": r["x"]}] + rated, names)[0]
                r["pred"], r["s"] = round(predict(xm, w, b), 3), combined(xm)
    fin = _finish(sc, field, inds, anchors, tops, top_of, att_source)
    rated_names = {s["node"]: s for s in skipped if s.get("node")}
    other_rows = [{"id": n["id"], "short": n.get("short", ""), "title": n.get("title", ""), "type": work_type(n),
                   "yours": (rated_names.get(n["id"]) or {}).get("yours")} for n in others]
    for s in skipped:
        if s.get("node") and s["node"] not in {o["id"] for o in other_rows}:
            other_rows.append({"id": s["node"], "short": "", "title": s.get("title") or s["ref"], "type": s["type"], "yours": s["yours"]})
    return enrich({"indicators": inds, "start": inds0, "started_from": (start or {}).get("saved") if start and inds0 else "",
                   "history": cal["history"] + field.get("history", []), "unexplained": cal["unexplained"],
                   **_tallied(sc, fin), "others": other_rows,
                   "skipped": [s for s in skipped if not s.get("node")],
                   "as_of": as_of, "fit_metric": A.FIT_METRIC,
                   "sampled": len(drawn), "years": years, "attention_source": att_source, "attention_anchor": top_of if cands else {},
                   "older": [{"id": n["id"], "title": n.get("title", ""), "date": n.get("date", "")} for n in old]}, graph)


def _anchoring(rated_ms: List[Tuple[str, dict]], cands: List[dict], anchor_m: Optional[dict],
               att_source: str) -> Tuple[Dict[str, list], Dict[str, float], Dict[str, str]]:
    """The attention scale's top end for each measure: the landmark's count (Attention Is All You Need) when known,
    else the most attended paper known (your rated papers included). Returns (anchors: your papers' counts, tops: the
    landmark's counts, top_of: the title at the top end, for the page)."""
    from tastecal.taste import attention as A
    anchors = {mt: [m.get(mt) for _, m in rated_ms if m.get(mt) is not None] for mt in A.METRICS}
    tops = {mt: anchor_m.get(mt) for mt in A.METRICS if anchor_m and anchor_m.get(mt)}
    top_of = {}
    for mt in A.METRICS:
        if mt == A.FIT_METRIC and att_source != "citations a year":
            continue                             # the run's own percentile, by rank: no top end to name
        if mt in tops:
            top_of[mt] = A.ANCHOR_TITLE
            continue
        pool_ = [(m.get(mt), t) for t, m in rated_ms if m.get(mt) is not None]
        pool_ += [(c["m"].get(mt), c["node"].get("title", "")) for c in cands if c["m"].get(mt) is not None]
        if pool_:
            top_of[mt] = max(pool_, key=lambda t: t[0])[1]
    return anchors, tops, top_of


def _counts_again(m: dict, att: dict) -> dict:
    """A paper's measures as a result from before 2026-10-20 stored them, made whole again: citations a year from its
    citations and age, and the two percentiles under their own names (unify then picks one measure for all)."""
    m = dict(m)
    if m.get("rate") is None:
        cites = m.get("citations") if m.get("citations") is not None else (att or {}).get("citations")
        if cites is not None:
            m["rate"] = round(cites / max(0.5, (m["months"] if m.get("months") is not None else 12) / 12), 3)
    if "pct_field" not in m and "pct_run" not in m and m.get("scale") is None:
        src = m.get("source") or ""
        m["pct_field"] = m.get("cumulative") if "OpenAlex" in src else None
        m["pct_run"] = m.get("cumulative") if "run" in src else (att or {}).get("pct")
    return m


def _score(rated: List[dict], cands: List[dict], inds: List[dict], field: dict, lam: float) -> dict:
    """Step 2's scoring from levels already measured (run, refit): the weights fitted towards y = x within your scores
    (or every clause counting the same when there is nothing to fit to), each rated paper's and each other paper's
    score, the bars, the noise, and the rows the page shows."""
    names = [d["name"] for d in inds]
    X, y = _matrix(rated, names), [r["yours"] for r in rated]
    targets, wts = field.get("targets") or {}, field.get("weights") or {}
    xc = {c["id"]: x for c, x in zip(cands, _rows_x(cands, rated, names))}
    tg = [c["id"] for c in cands if c["id"] in targets]
    w_eq, b_eq = fit_scale(X, y, lam)
    got, fallback, tol = None, "", [FIT_TOL] * len(X)
    rows_c = t_c = w_c = s1 = None
    if tg:
        # the weights fitted towards y = x within your scores, held exactly as step 2 held them. Your papers' second
        # reading of a clause the field changed may move them a little; the start is then step 1's kind of line or the
        # weights step 2 ended with, whichever still meets your scores (else one is searched for)
        rows_c, t_c, w_c = [xc[i] for i in tg], [targets[i] for i in tg], [wts[i] for i in tg]
        tol, s1 = list(field["tol"]), list(field["s1"])
        w_f = [(field.get("w_end") or {}).get(n, 0.0) for n in names]
        got = fit_weights(X, y, tol, rows_c, t_c, w_c, (w_eq, b_eq),
                          [(w_eq, b_eq), (w_eq, _with_b(X, y, tol, w_eq)), (w_f, _with_b(X, y, tol, w_f))], s1)
        if got is None:
            fallback = "your scores could not be met after your papers were read a second time"
            log.warning("%s: every clause counts the same, as in step 1", fallback)
    if got is not None:
        w, b = got
        variants = []                            # each rated paper left out: how much the weights rest on it
        for i in range(len(X)):
            Xi, yi, ti = X[:i] + X[i + 1:], y[:i] + y[i + 1:], tol[:i] + tol[i + 1:]
            we, be = fit_scale(Xi, yi, lam)      # the full fit meets these constraints, so it is a start that works
            variants.append(fit_weights(Xi, yi, ti, rows_c, t_c, w_c, (we, be), [(w, b)], s1[:i] + s1[i + 1:]) or (w, b))
    else:                                        # nothing to fit to: every clause counts the same
        w, b = w_eq, b_eq
        variants = [fit_scale(X[:i] + X[i + 1:], y[:i] + y[i + 1:], lam) for i in range(len(X))]
    pred_r = [predict(x, w, b) for x in X]
    errs = [abs(p - t) for p, t in zip(pred_r, y)]
    ev = {"lam": lam, "pred": pred_r, "err": errs, "mae": mean(errs) if errs else 0.0, "order": order_errors(y, pred_r),
          "max": max(errs) if errs else 0.0}
    loo_r = [predict(X[i], *variants[i]) for i in range(len(X))]
    preds = {i: predict(x, w, b) for i, x in xc.items()}
    conf = confidence(list(ev["err"]), len(ev["order"]))

    def spread_of(x: List[float]) -> float:
        """The width of a paper's score bar: how much its score moves when one rated paper is left out, combined with
        how far the clauses miss your own scores on average (they cannot score another paper more precisely than
        they reproduce yours), so a poorer fit widens every bar and fewer papers count as off the line."""
        vs = [predict(x, wv, bv) for wv, bv in variants]
        half = (max(vs) - min(vs)) / 2 if vs else 0.0
        return 2 * math.sqrt(half * half + conf["rms"] ** 2)

    # noise: how far one read is from the other on your rated papers. Their levels average the two reads; the noise
    # is that of a single read, which is what the papers you have not rated get
    p1 = [predict(x, w, b) for x in _matrix([{"x": r.get("x1") or r["x"]} for r in rated], names)]
    p2 = [predict(x, w, b) for x in _matrix([{"x": r.get("x2") or r["x"]} for r in rated], names)]
    noise = max(0.02, round(math.sqrt(mean((a - c) ** 2 for a, c in zip(p1, p2))) / math.sqrt(2), 3))
    far = max(FAR, round(2 * noise, 3))

    # the weights, read as shares of a combined score s (summing to 1) and a line: score = a * s + b
    a_ = sum(w)
    shares = [round(c / a_, 4) for c in w] if a_ > 0 else [round(1 / len(w), 4)] * len(w)
    share_of = lambda coefs: [c / sum(coefs) if sum(coefs) > 0 else 0.0 for c in coefs]  # noqa: E731
    spread = [share_of(wv) for wv, _ in variants]
    weights = [{"name": d["name"], "rubric": d["rubric"], "from": d.get("from", ""), "share": shares[k], "w": round(w[k], 4),
                "low": round(min(sp[k] for sp in spread), 3), "high": round(max(sp[k] for sp in spread), 3)}
               for k, d in enumerate(inds)]
    combined = lambda x: round(sum(sh * v for sh, v in zip(shares, x)), 3)  # noqa: E731

    rated_rows = []
    for i, r in enumerate(rated):                # your scores are the constraint: shown with how well the clauses reproduce them
        contrib = sorted(((names[k], round(w[k] * X[i][k], 3)) for k in range(len(names))), key=lambda t: -t[1])
        rated_rows.append({"key": r["key"], "title": r["title"], "node": r["node"], "yours": r["yours"],
                           "comment": r.get("comment", ""), "pred": round(ev["pred"][i], 3), "fit": round(predict(X[i], w, b), 3),
                           "loo": round(loo_r[i], 3), "s": combined(X[i]), "x": r["x"], "x1": r.get("x1") or {}, "x2": r.get("x2") or {},
                           "basis": r["basis"], "contrib": contrib, "side": "", "m": r.get("m"),
                           "allowed": round(tol[i] if got is not None else FIT_TOL, 4),
                           **{k: r[k] for k in ("venue", "authors", "year") if r.get(k)}})
    map_rows = []
    for c, x in zip(cands, _rows_x(cands, rated, names)):
        n = c["node"]
        row = {"id": c["id"], "short": n.get("short", ""), "title": n.get("title", ""), "date": n.get("date", ""),
               "pred": round(preds[c["id"]], 3), "s": combined(x), "unsure": round(spread_of(x), 3),
               "x": c["x"], "basis": c["basis"], "sample": n.get("sample", ""), "half": c["half"],
               "m": c["m"], "attention": c["m"].get("cumulative"),
               "att": {k: att_of(n).get(k) for k in ("citations", "citations_per_year", "lower_bound", "basis")}}
        if c.get("recheck"):
            row["recheck"] = c["recheck"]
        map_rows.append(row)
    return {"w": w, "b": b, "fitted": got is not None, "fallback": fallback, "ev": ev, "loo_r": loo_r, "y": y,
            "conf": conf, "noise": noise, "far": far, "weights": weights, "a": a_, "combined": combined, "lam": lam,
            "rated_rows": rated_rows, "map_rows": map_rows, "targets": targets, "wts": wts, "tg": tg}


def _finish(sc: dict, field: dict, inds: List[dict], anchors: Dict[str, list], tops: Dict[str, float],
            top_of: Dict[str, str], att_source: str) -> dict:
    """The page's lists from the scores: the best and the most off on your line, each measure of attention against
    your score, how the counts were put on 0 to 1, and how close the papers came to y = x."""
    from tastecal.taste import attention as A
    map_rows = sc["map_rows"]
    map_rows.sort(key=lambda r: -r["pred"])
    k = max(3, round(len(map_rows) * 0.1))
    for r in map_rows:
        r.pop("class", None)
    for r in map_rows[:k]:
        r["class"] = "best"
    for r in map_rows[-k:] if len(map_rows) > k else []:
        r["class"] = "off"
    vw = views([{"id": r["id"], "m": r["m"]} for r in map_rows], {r["id"]: r["pred"] for r in map_rows},
               {r["id"]: r["unsure"] for r in map_rows}, sc["far"], anchors, tops,
               fixed={A.FIT_METRIC: field["pos"]} if field.get("pos") else None)
    att_scale = {}                               # how counts were put on 0 to 1, for the page: median and top end
    for mt in A.METRICS:
        if mt == A.FIT_METRIC and att_source != "citations a year":
            continue
        s_ = A.scale([{"m": r["m"]} for r in map_rows], mt, anchors.get(mt, []), tops.get(mt))
        if s_:
            att_scale[mt] = {"median": s_["median"], "top": s_["top"], "top_title": top_of.get(mt, ""), "lo": s_["lo"]}
    field_info = {k_: v for k_, v in field.items() if k_ not in ("indicators", "targets", "weights", "pos", "w_end")}
    tg, targets, wts = sc["tg"], sc["targets"], sc["wts"]
    if tg:                                       # where the papers ended up, with the scoring as used (after the re-check)
        final_p = {r["id"]: r["pred"] for r in map_rows}
        field_info["final"] = {"dist": round(_dist(final_p, targets, wts, tg), 3), "mae": round(sc["ev"]["mae"], 3)}
    if sc["fallback"]:
        field_info["fallback"] = sc["fallback"]
    field_info["field_names"] = [d["name"] for d in inds if d.get("from") == "field"]
    field_info["share"] = round(sum(wt["share"] for wt in sc["weights"] if wt["name"] in field_info["field_names"]), 3)
    return {"views": vw, "attention_scale": att_scale, "field": field_info, "suggest": suggest(map_rows)}


def _tallied(sc: dict, fin: dict) -> dict:
    """The result's keys that come from the scoring (run and refit write the same ones)."""
    ev, y = sc["ev"], sc["y"]
    return {"weights": sc["weights"], "b": round(sc["b"], 4), "a": round(sc["a"], 4), "lambda": sc["lam"],
            "rated": sc["rated_rows"], "mae": round(ev["mae"], 3), "order_errors": len(ev["order"]),
            "max_err": round(ev.get("max", 0.0), 3),
            "loo_mae": round(mean(abs(p - t) for p, t in zip(sc["loo_r"], y)), 3) if y else 0.0,
            "fit_tol": FIT_TOL, "confidence": sc["conf"], "noise": sc["noise"], "far": sc["far"], "map": sc["map_rows"],
            "suggest": fin["suggest"], "views": fin["views"], "field": fin["field"], "attention_scale": fin["attention_scale"]}


def refit(res: dict, graph: dict, anchor: Optional[dict] = None) -> dict:
    """Step 2's numbers again from a fit's own result, without a model call: the attention scale, the weights fitted
    towards y = x within your scores, every score, the bars and the page's lists. The clauses and every paper's levels
    are the ones the fit measured (with its re-checks); the field's clause changes are not tried again. `anchor`: raw
    counts of Attention Is All You Need, for a result that does not keep its count."""
    from tastecal.taste import attention as A
    inds = res["indicators"]
    names = [d["name"] for d in inds]
    keep = ("key", "title", "node", "yours", "comment", "m", "venue", "authors", "year")
    rated = [dict({k: r.get(k) for k in keep}, x=dict(r["x"]), x1=dict(r.get("x1") or {}), x2=dict(r.get("x2") or {}),
                  basis=dict(r.get("basis") or {})) for r in res["rated"]]
    by = {n["id"]: n for n in graph.get("nodes", [])}
    cands = []
    for r in res["map"]:
        n = dict(by.get(r["id"]) or {}, id=r["id"], short=r.get("short", ""), title=r.get("title", ""),
                 date=r.get("date", ""), sample=r.get("sample", ""))
        n["assessment"] = dict(n.get("assessment") or {}, attention=dict(att_of(n), **(r.get("att") or {})))
        cands.append({"id": r["id"], "x": dict(r["x"]), "basis": dict(r.get("basis") or {}), "node": n,
                      "half": r.get("half", _half(r["id"])), "m": _counts_again(r.get("m") or {}, r.get("att") or {}),
                      "recheck": r.get("recheck")})
    for r in rated:
        if r.get("m"):
            r["m"] = _counts_again(r["m"], {})
    as_of = res.get("as_of") or date.today().isoformat()
    anchor_m = A.measures(A.ANCHOR_NODE, anchor, as_of) if anchor else None
    rated_ms = [(r["title"], r["m"]) for r in rated if r.get("m")]
    if anchor_m is None:                         # the landmark among your rated papers
        from tastecal.core.model import title_similarity
        anchor_m = next((m for t, m in rated_ms if title_similarity(t, A.ANCHOR_TITLE) >= 0.9), None)
    att_source = A.unify([c["m"] for c in cands], [m for _, m in rated_ms] + ([anchor_m] if anchor_m else [])) if cands else ""
    anchors, tops, top_of = _anchoring(rated_ms, cands, anchor_m, att_source)
    old_scale = res.get("attention_scale") or {}
    for mt, v in old_scale.items():              # the landmark's count this result kept, when none is given
        if mt not in tops and v.get("top") and v.get("top_title") == A.ANCHOR_TITLE and (mt != A.FIT_METRIC or
                                                                                       att_source == "citations a year"):
            tops[mt], top_of[mt] = v["top"], A.ANCHOR_TITLE
    lam = res.get("lambda", LAM_FIT)
    old = res.get("field") or {}
    X, y = _matrix(rated, names), [r["yours"] for r in rated]
    w0, b0 = fit_scale(X, y)                     # step 1's kind of line on these levels
    if not old.get("tol") and any(h.get("phase") == "field" and h.get("accepted") for h in res.get("history") or []):
        log.warning("this result does not keep step 1's tolerances and the field changed a clause: they are taken "
                    "from the levels as they are now, which may differ a little")
    tol = list(old.get("tol") or tolerances(X, y, w0, b0))
    s1 = list(old.get("s1") or [_raw(x, w0, b0) for x in X])
    s0 = {c["id"]: predict(x, w0, b0) for c, x in zip(cands, _rows_x(cands, rated, names))}
    pos = A.position([{"id": c["id"], "m": c["m"]} for c in cands], A.FIT_METRIC, s0, anchors.get(A.FIT_METRIC, []),
                     tops.get(A.FIT_METRIC)) if cands else {}
    targets = {i: p["x"] for i, p in pos.items()}
    wts = {c["id"]: (c["m"] or {}).get("rel", 1.0) for c in cands if c["id"] in targets}
    keep_f = {k: v for k, v in old.items() if k not in ("final", "fallback", "skipped")}
    if len(targets) < MIN_FIELD:
        field = dict(keep_f, skipped=f"{len(targets)} papers with this attention measure (at least {MIN_FIELD} are needed)")
    else:
        w_prev = {wt["name"]: wt.get("w", 0.0) for wt in res.get("weights") or []}
        field = dict(keep_f, targets=targets, weights=wts, tol=tol, s1=s1, pos=pos, w_end=w_prev, lam=lam,
                     papers=len(targets), equal={"dist": round(_dist(s0, targets, wts, list(targets)), 3),
                                                 "mae": round(mean(abs(predict(x, w0, b0) - t) for x, t in zip(X, y)), 3)})
        cur = toward_line(rated, cands, names, tol, targets, wts, prev=[w_prev.get(n, 0.0) for n in names], s1=s1)
        if cur is not None:                      # the clause rounds are not run again: start and end are where it stands
            field["start"] = field["end"] = _state(cur)
    sc = _score(rated, cands, inds, field, lam)
    fin = _finish(sc, field, inds, anchors, tops, top_of, att_source)
    out = dict(res, **_tallied(sc, fin))
    out["attention_source"], out["attention_anchor"] = att_source, top_of
    out["refit"] = {"on": date.today().isoformat(),
                    "note": "the attention scale, the weights and the page recomputed from this result's levels; no model call"}
    for r in out["map"]:
        r.pop("threads", None)
        r.pop("role", None)
    return enrich(out, graph)


def enrich(res: dict, graph: dict) -> dict:
    """What the page takes from the map, so it draws papers the way the map does: each predicted paper's threads and
    role, and the threads in map order (a thread's colour follows its place in that order)."""
    res["threads"] = [{"id": t.get("id"), "name": t.get("name") or t.get("title") or t.get("id")} for t in graph.get("threads") or []]
    by = {n["id"]: n for n in graph.get("nodes", [])}
    for r in res.get("map") or []:
        n = by.get(r["id"]) or {}
        r.setdefault("threads", n.get("threads") or [])
        r.setdefault("role", n.get("role") or "")
        for k in ("venue", "authors", "year"):
            if n.get(k) and not r.get(k):
                r[k] = n[k]
    for r in res.get("rated") or []:
        n = by.get(r.get("node")) or {}
        for k in ("venue", "authors", "year"):
            if n.get(k) and not r.get(k):
                r[k] = n[k]
    meta = graph.get("meta") or {}
    res.setdefault("as_of", str(meta.get("generated_at") or "")[:10] or date.today().isoformat())
    res.setdefault("topic", str(meta.get("seed_ref") or meta.get("seed") or "").strip())
    # method papers on the map that could not be scored because only an abstract or a card could be read: each
    # with the file name its PDF should have in the papers folder
    from tastecal.sources.fulltext import suggested_name
    years = res.get("years") if isinstance(res.get("years"), int) else YEARS
    yours = {r.get("node") for r in res.get("rated") or []}
    res["unread_map"] = [{"id": n["id"], "short": n.get("short") or "", "title": n.get("title") or "",
                          "date": n.get("date") or "", "file": suggested_name(n)}
                         for n in graph.get("nodes", [])
                         if n.get("kind", "paper") == "paper" and not n.get("borrowed") and not readable(n)
                         and n["id"] not in yours and is_method(n) and recent(n, res["as_of"], years)]
    return res


def att_of(node: dict) -> dict:
    return ((node.get("assessment") or {}).get("attention") or {})


def corners(rows: List[dict], today: str = "") -> dict:  # older results only (no "views")
    """Your line against the field, on one scale. The predicted score is on your scale and attention is a citation
    percentile, so neither is compared by value: each paper gets its rank among these papers on both (0 lowest, 1
    highest), and the line is y = x, the field ranking a paper where your clauses do. A paper is off the line when the
    two ranks differ by more than BAND, the end of its uncertainty bar nearest the line included: below it, high on
    your line and little cited ("gem"); above it, much cited and low on your line ("hyped"). Papers under a year old
    (too few citations yet) and those whose citation counts are not trusted are drawn but never put off the line.
    Returns {"band", "pos": {id: {"x", "lo", "hi", "y"}}, "gem", "hyped", "new"}, the lists sorted by distance."""
    from tastecal.judge.audit import months_between

    def young(r: dict) -> bool:
        return bool(today) and bool(r.get("date")) and months_between(r["date"], today) < 12
    have = [r for r in rows if r.get("attention") is not None]
    out = {"band": BAND, "pos": {}, "gem": [], "hyped": [], "new": [r["id"] for r in have if young(r)]}
    if len(have) < 4:
        return out
    xs, ys = [r["pred"] for r in have], [r["attention"] for r in have]
    rank = lambda vals, v: (sum(u < v for u in vals) + 0.5 * sum(u == v for u in vals)) / len(vals)  # noqa: E731
    for r in have:
        half = (r.get("unsure") or 0) / 2
        out["pos"][r["id"]] = {"x": round(rank(xs, r["pred"]), 3), "lo": round(rank(xs, r["pred"] - half), 3),
                               "hi": round(rank(xs, r["pred"] + half), 3), "y": round(rank(ys, r["attention"]), 3)}
    ok = [r for r in have if not (r.get("att") or {}).get("lower_bound") and not young(r)]
    below = {r["id"]: out["pos"][r["id"]]["lo"] - out["pos"][r["id"]]["y"] for r in ok}
    above = {r["id"]: out["pos"][r["id"]]["y"] - out["pos"][r["id"]]["hi"] for r in ok}
    out["gem"] = sorted([i for i, d in below.items() if d > BAND], key=lambda i: -below[i])
    out["hyped"] = sorted([i for i, d in above.items() if d > BAND], key=lambda i: -above[i])
    return out


def suggest(rows: List[dict], k: int = 8) -> List[str]:
    """Works worth rating next: where the leave-one-out lines disagree most, plus the two ends."""
    if not rows:
        return []
    picks = [r["id"] for r in sorted(rows, key=lambda r: -r["unsure"])[: k - 2]]
    for r in (rows[0], rows[-1]):
        if r["id"] not in picks:
            picks.append(r["id"])
    return picks[:k]
