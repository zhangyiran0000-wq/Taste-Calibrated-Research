"""Prompts for the attention-vs-contribution audit (TASK names start with audit_).

The contribution prompts only ever see a *blind* evidence pack: no title, authors,
venue, awards or citation counts, and the work's own name replaced by an alias.
"""
from __future__ import annotations

import json
from typing import List

from tastecal.prompts.lineage import SYSTEM, clip

AUDIT_SYSTEM = (SYSTEM + " When judging contribution, ignore how famous or widely cited a work might be; "
                "judge only what the evidence in front of you shows.")

ROLE_MENU = """- builds_on: adopts, extends or is directly inspired by its method or idea
- contrasts: engages with its claim or limitation (disagrees, fixes, re-evaluates)
- baseline: only a comparison target or a row in a results table
- uses: uses its code, data, benchmark or model as a tool
- mentions: listed in passing (related work, "e.g. [1, 2, 3]")"""


def citation_roles(rows: List[str]) -> str:
    listing = "\n".join(f"[{i + 1}] {clip(t, 360)}" for i, t in enumerate(rows))
    return f"""TASK: audit_citation_roles
Each sentence below comes from a later paper that cites a work referred to as [TARGET].
Classify what the citing paper does with [TARGET]:
{ROLE_MENU}

Sentences:
{listing}

Return a JSON array: [{{"i": 1, "role": "builds_on"}}, ...]"""


def claims_check(card_text: str, text: str) -> str:
    return f"""TASK: audit_claims
Below is a summary of a research paper and its text (possibly truncated).

Summary:
{card_text}

Text:
{clip(text, 14000)}

1. List the 2-4 main claims the paper makes about its own contribution.
2. For each, judge whether the paper's OWN experiments support it:
   "supported" (clear, fair evidence), "partial" (small gains, single benchmark, missing ablation for the claimed component,
   unequal baselines), "unsupported" (evidence contradicts or does not test it), or "untested".
3. List fairness notes a careful reviewer would raise (extra inputs or sensors vs baselines, privileged information such as
   ego status, different backbones or training data, metric or protocol differences, no variance reported, no closed-loop test).

Return {{"claims": [{{"claim": "...", "support": "...", "evidence": "where and why"}}], "fairness_notes": ["..."]}}"""


def mechanism(card_text: str) -> str:
    return f"""TASK: audit_mechanism
{card_text}

Describe the core idea of this work as a mechanism in one or two sentences, WITHOUT using its name or acronyms,
and write 2 keyword search queries that would find EARLIER papers that may already have had the same idea.
Return {{"mechanism": "...", "queries": ["...", "..."]}}"""


def precedents(mech: str, date: str, cands: List[dict]) -> str:
    rows = "\n".join(f"[{c['id']}] {c['title']} ({c.get('year') or '?'})\n  {clip(c.get('abstract', ''), 500)}" for c in cands)
    return f"""TASK: audit_precedents
A work first released in {date or 'unknown date'} has this core mechanism:
{mech}

Which of these earlier works already had the same idea?
{rows}

For each, return {{"id": "...", "overlap": "same idea" | "partial" | "different", "note": "one line on what overlaps"}}.
Return a JSON array."""


def contribution_blind(pack_text: str) -> str:
    return f"""TASK: audit_contribution
You are scoring how much a research work contributed to its field. You see an anonymous evidence pack.
Do not try to identify the work; famous or obscure, judge only the evidence.

Score each from 0 to 1:
- novelty: is the core idea new compared with the earlier work listed? (1 = clearly new, 0 = same idea already published)
- significance: does it open, solve or reframe a problem others care about? (problems it opened or solved, what later work did with it)
- evidence: do its own experiments support its claims fairly? (fair baselines, ablations for the claimed component, more than one
  benchmark, survives the later evidence listed)
- uptake: the SHARE and DEPTH of later papers that build on it or engage with it, not how many cite it. Use 0.5 if it is too recent
  to judge.
Judge by the yardstick for its type: benchmarks, datasets and tools by whether they are used; analyses and critiques by whether they
changed what others did; surveys by orientation value; methods by whether others build on them.
score: your overall judgement, roughly 0.3 novelty + 0.3 significance + 0.2 evidence + 0.2 uptake, adjusted for type.

Evidence pack:
{pack_text}

Return {{"type": "method|analysis|benchmark|dataset|tool|survey|application|system", "novelty": 0.0, "significance": 0.0,
"evidence": 0.0, "uptake": 0.0, "score": 0.0, "rationale": "2-3 sentences that cite specific evidence"}}"""


def advocate(pack_text: str) -> str:
    return f"""TASK: audit_advocate
Make the strongest honest case that this work makes a real, lasting contribution that is easy to undervalue.
Use ONLY the evidence pack; cite specific items. Concede what you cannot defend. At most 160 words.

Evidence pack:
{pack_text}

Return {{"case": "...", "strongest_evidence": ["...", "..."]}}"""


def critic(pack_text: str) -> str:
    return f"""TASK: audit_critic
Make the strongest honest case that this work adds little: its idea already existed (redundant), its gains do not come from
its stated idea or do not hold up (hollow), it moves a known method to a new setting without finding anything new (derivative),
or later work does not build on it (inert). Use ONLY the evidence pack; cite specific items. Concede strengths you cannot
dispute. At most 160 words.

Evidence pack:
{pack_text}

Return {{"case": "...", "strongest_evidence": ["...", "..."]}}"""


def judge(pack_text: str, adv: dict, crit: dict) -> str:
    return f"""TASK: audit_judge
You are a careful, neutral judge. Two reviewers argued from the same anonymous evidence pack. Weigh their arguments against
the evidence itself (an argument not backed by the pack counts for nothing) and decide how substantial the work's contribution is.

Evidence pack:
{pack_text}

Advocate:
{json.dumps(adv, ensure_ascii=False)}

Critic:
{json.dumps(crit, ensure_ascii=False)}

Return {{"verdict": "substantial" | "modest" | "negligible", "confidence": "high" | "medium" | "low",
"reasons": ["2-4 short reasons tied to evidence"], "would_change": "what evidence would change your verdict"}}"""


def attention_check(facts: str) -> str:
    return f"""TASK: audit_attention
A blind review found that this work makes a substantial contribution, and its counts looked low next to
nearby works. Decide whether it really is under-noticed, using the counts below and what you know of its field.
A work cited hundreds of times, or widely known in its field, is not under-noticed even if the works around it
are cited more.

{facts}

Return {{"verdict": "under-noticed" | "fairly noticed" | "well noticed", "why": "one or two sentences"}}"""
