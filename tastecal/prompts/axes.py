"""Prompts for fitting the reader's taste (taste/axes.py). The model measures each work on the reader's own indicators,
written in the reader's terms; it never gives a verdict of its own on a work. Every prompt starts with a TASK line."""
from __future__ import annotations

from typing import Dict, List

SYSTEM = ("You read research papers from notes taken on their full text and measure them against a reader's own "
          "criteria. You answer with JSON only. You never invent facts that are not in the notes, and you never give "
          "your own opinion of a paper's quality. When you write in Chinese, a reader's taste is 审美, never 品味.")


def _ind_lines(indicators: List[dict]) -> str:
    """Each indicator with its rubric, and the reading notes the loop added to it (applied to every paper)."""
    return "\n".join(f"{i + 1}. {x['name']}: {x['rubric']}" + "".join(f"\n   How to read it: {h}" for h in x.get("how") or [])
                     for i, x in enumerate(indicators))


def indicators(defaults: List[dict], rated: List[dict], extra: int = 3) -> str:
    """Write the reader's indicators: the defaults, sharpened in the reader's terms, plus what the reasons add."""
    rows = "\n".join(f"- score {r['yours']:.2f}: \"{r.get('comment') or '(no reason)'}\"" for r in rated)
    base = "\n".join(f"- {d['name']}: {d['rubric']}" for d in defaults)
    return f"""TASK: fit_indicators
A reader scored some papers from 0 to 1 and gave reasons. Write down the indicators this reader judges by, each as a
step function with six levels, 0 to 5, so that someone else could measure any paper the way this reader would.

Every level must be a concrete condition that can be checked against a paper: what it does, what it shows, what it
reports. For example "0 = only open-loop averages; 1 = closed loop, but the other agents replay logs; ...". A level
must never say what the reader likes, values or prefers, must never name a paper, a method or an author, and must
never speak of how the field received the paper (citations, later work taking it up, fame, venue): only what can be
checked in the paper itself. The rated papers may come from several fields: write every level as a condition that
applies to a paper of any field; a field-specific example may follow in parentheses.

Start from these general indicators. Keep each one, but where the reader's reasons say more about it, rewrite its
rubric in the reader's terms (for example, what the reader counts as valid evaluation):
{base}

Then add at most {extra} indicators that the reasons use and the list above does not cover.

The reader's scores and reasons:
{rows}

Return JSON: {{"indicators": [{{"name": "short name", "rubric": "0 = ...; 1 = ...; 2 = ...; 3 = ...; 4 = ...; 5 = ...", "from": "default|reasons"}}]}}"""


def score(inds: List[dict], works: Dict[str, str], reverse: bool = False, check: str = "",
          refs: List[tuple] = ()) -> str:
    """Measure each work on each indicator. `reverse` lists works and indicators the other way round (a second
    read for the noise); `check` points at what to read carefully; `refs` are works already measured, (summary,
    {indicator: level}), shown so that every condition is applied the same way."""
    items = list(works.items())
    if reverse:
        items = list(reversed(items))
    order = list(reversed(inds)) if reverse else inds
    rows = "\n\n".join(f"[{wid}]\n{text}" for wid, text in items)
    extra = f"\nRead carefully before measuring: {check}\n" if check else ""
    names = {d["name"] for d in inds}
    ref_txt = ""
    if refs:
        ref_txt = "Works already measured, for reference (apply every condition to the works below exactly as it was applied to these):\n" + \
            "\n".join(f"- levels: {'; '.join(f'{k} {v}' for k, v in lv.items() if k in names and v is not None)}. What it is: {summary}"
                      for summary, lv in refs) + "\n\n"
    compare = ("Several works are listed: compare them with each other on each indicator; where two works differ on what "
               "an indicator asks, their levels must differ.\n" if len(items) > 1 else "")
    return f"""TASK: fit_score
Measure each work below on each of a reader's indicators, by the reader's rubric. Do not judge the work in any other
way: no overall verdict, no standards of your own.
For each work and indicator: find the highest level whose condition the work meets, quote or point to what in the
notes meets it ("basis", one sentence), say what the work lacks for the next level up ("not_higher", one short
sentence, or "top"), then give the level, from 0 to 5. There is no default level: a work that only claims something
without showing it does not meet the condition. Use "n/a" only when the indicator cannot apply to this kind of work.
{compare}{extra}
{ref_txt}Indicators:
{_ind_lines(order)}

Works:
{rows}

Return JSON: {{"works": [{{"id": "...", "levels": {{"<indicator name>": {{"basis": "...", "not_higher": "...", "level": 3}}}}}}]}}
Use the indicator names exactly as written."""


def consistent(inds: List[dict], ref_id: str, ref_text: str, ref_levels: Dict[str, int], work_id: str, work_text: str) -> str:
    """Measure a work again next to a rated paper with a similar profile, so each condition is applied to both the
    same way."""
    lv = "; ".join(f"{k} {v}" for k, v in ref_levels.items())
    return f"""TASK: fit_score
Measure work [{work_id}] on each indicator. Work [{ref_id}] was already measured: {lv}. Apply every condition to
[{work_id}] exactly as it was applied to [{ref_id}]: if the two works do the same thing, they get the same level. Do
not judge the work in any other way.
For each indicator: find the highest level whose condition the work meets, point to what in the notes meets it
("basis", one sentence), then give that level, from 0 to 5.

Indicators:
{_ind_lines(inds)}

Already measured, for reference:
[{ref_id}]
{ref_text}

Works:
[{work_id}]
{work_text}

Return JSON: {{"works": [{{"id": "{work_id}", "levels": {{"<indicator name>": {{"basis": "...", "level": 3}}}}}}]}}"""


def edit(inds: List[dict], target: dict, contrast: dict, tried: List[str] = ()) -> str:
    """One change to the indicators so that the fitted line predicts the reader's score of the target better."""
    def show(p: dict) -> str:
        lv = "; ".join(f"{k} {v}" for k, v in p["levels"].items())
        return (f"The reader scored it {p['yours']:.2f} because: \"{p.get('comment') or '(no reason given)'}\". "
                f"The indicators, as measured, predict {p['pred']:.2f}. Measured levels: {lv}.\n"
                f"What it is: {p['summary']}")
    tried_txt = ("Changes already tried that did not help (propose something different):\n" +
                 "\n".join(f"- {t}" for t in tried) + "\n\n") if tried else ""
    return f"""TASK: fit_edit
A reader's taste is modelled as the average of these indicators' levels: every indicator counts the same, and only a
scale and an offset are fitted to the reader's scores. So everything the reader values must be in the wording of the
indicators, and an indicator the reader's scores do not reward pulls the average the wrong way:
{_ind_lines(inds)}

Paper A. {show(target)}

Paper B. {show(contrast)}

The model gets A wrong. Propose ONE change that would let the average of the indicators tell A and B apart the way
the reader did. The change must follow from the reader's reasons. It must be general: never name A, B or any paper. Every
level must be a concrete condition that can be checked against a paper (what it does, shows or reports), never what
the reader likes or values, and never how the field received it (citations, later work, fame, venue). It must apply
to a paper of any field (a field-specific example may follow in parentheses).
{tried_txt}Choose "type":
- "rewrite": replace the rubric of indicator number "line" with "rubric" (keep its name, or give a new "name");
- "add": a new indicator, with "name" and "rubric" (0 = ...; 1 = ...; 2 = ...; 3 = ...; 4 = ...; 5 = ...);
- "misread": an indicator is being read wrongly; give its "name" and, in "check", a reading note for it: what to
  look for in a paper before giving a level, in at most 80 words. The note is added to the indicator and every paper
  is measured again with it, so it must be general: no paper's name, nothing about the reader;
- "remove": take out indicator number "line", when it measures something the reader's reasons never judge by and
  it only moves the average away from the reader's scores;
- "none": no general indicator separates them; say why in "why".
Return JSON: {{"type": "...", "line": 0, "name": "...", "rubric": "...", "check": "...", "why": "..."}}"""


def field_edit(inds: List[dict], target: dict, contrast: dict, tried: List[str] = ()) -> str:
    """One change to the indicators so that the score of a paper the reader has not rated comes closer to the field's
    attention to it (y = x), without saying anything about how the field received it."""
    def show(p: dict) -> str:
        lv = "; ".join(f"{k} {v}" for k, v in p["levels"].items())
        return (f"The indicators score it {p['pred']:.2f}; the field's attention puts it at {p['target']:.2f} on the "
                f"same 0-1 scale ({p['attention_txt']}). Measured levels: {lv}.\nWhat it is: {p['summary']}")
    tried_txt = ("Changes already tried that did not help (propose something different):\n" +
                 "\n".join(f"- {t}" for t in tried) + "\n\n") if tried else ""
    return f"""TASK: fit_field_edit
A reader's taste is modelled as a weighted sum of these indicators' levels. The weights are fitted so that every
paper's score comes as close as possible to the field's attention, while the papers the reader scored keep the
reader's scores:
{_ind_lines(inds)}

Two papers the reader has not scored:

Paper A. {show(target)}

Paper B. {show(contrast)}

The indicators and the field disagree on A. Is there something in the papers themselves, that the indicators miss or
misread, which would explain the field's view? Propose ONE change only if it is a general condition that can be
checked in any paper (what it does, shows or reports). It must never mention citations, later work taking a paper up,
fame, venue or authors, never what a reader likes, and never name A, B or any paper. The reader's own scores stay
fixed: a change that would contradict them is rejected. If the papers themselves do not explain the field's view
(it may be fame, timing or fashion), choose "none": the reader's standards and the field's then really differ.
{tried_txt}Choose "type":
- "rewrite": replace the rubric of indicator number "line" with "rubric" (keep its name, or give a new "name");
- "add": a new indicator, with "name" and "rubric" (0 = ...; 1 = ...; 2 = ...; 3 = ...; 4 = ...; 5 = ...);
- "misread": an indicator is being read wrongly; give its "name" and, in "check", a general reading note for it, in
  at most 80 words;
- "none": nothing in the papers explains it; say why in "why".
Return JSON: {{"type": "...", "line": 0, "name": "...", "rubric": "...", "check": "...", "why": "..."}}"""


def topic(problem: str, threads: List[str], works: Dict[str, str]) -> str:
    """Which drawn works are on the map's own problem."""
    rows = "\n\n".join(f"[{wid}]\n{text}" for wid, text in works.items())
    th = "; ".join(t for t in threads if t)
    return f"""TASK: fit_topic
A map of research on one problem. The paper the map started from:
{problem}
{("The map's threads: " + th) if th else ""}

For each paper below (title and abstract), say whether it works on the same problem: it addresses that problem or one
of its parts directly. A paper on a neighbouring task that only uses or cites this kind of work for a component (a
different task, a perception or prediction model, a general tool) does not count.

Papers:
{rows}

Return JSON: {{"keep": ["<id of each paper on the same problem>"]}} (an empty list when there is none)."""


def concepts(works: Dict[str, str]) -> str:
    """Which works are concept works (definitions, a taxonomy, terminology, a process described in words): they are
    not scored, like surveys."""
    rows = "\n\n".join(f"[{wid}]\n{text}" for wid, text in works.items())
    return f"""TASK: fit_types
For each work below, say whether its main contribution is a concept work: definitions, a taxonomy, a terminology, or
a process or framework described in words, with no method, model or algorithm that is run and no experiment that
tests it (an example worked by hand is not a test). A work that proposes something that runs and is tested is not a
concept work, however general its framing.

Works:
{rows}

Return JSON: {{"concept": ["<id of each concept work>"]}} (an empty list when there is none)."""


def fix_clause(text: str, problem: str) -> str:
    """Rewrite a refused clause, rubric or reading note so that it passes, keeping its meaning."""
    return f"""TASK: fit_fix
This text, written for a reader's indicators of research papers, was refused because it {problem}:

{text}

Rewrite it so that every condition can be checked in the paper itself (what it does, shows or reports): never what a
reader likes, never how the field received the paper (citations, later work taking it up, fame, venue), never the
name of a paper. Keep everything else, including the level numbers and their order.
Return JSON: {{"text": "..."}}"""
