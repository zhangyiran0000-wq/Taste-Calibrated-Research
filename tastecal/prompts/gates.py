"""Prompts for the gates (TASK names start with gates_).

The audit prompt reads one work's own text and never sees the reader's taste profile.
The taste prompt sees the idea (problem, move, insight) and what the gate read found, never the gate's verdict.
"""
from __future__ import annotations

from typing import Dict, List

from tastecal.prompts.lineage import SYSTEM, clip

GATES_SYSTEM = (SYSTEM + " Judge only the evidence in the text in front of you, not how well known a work might be. "
                "Papers are released when they beat their chosen baselines, so beating a baseline is not, by itself, "
                "evidence of anything: ask where the gain comes from.")

LEVER_MENU = """- cost-assumption: savings or speed-ups depend on a price, cost ratio or hardware figure the authors chose
- metric-trained: a component is trained on, or tuned to, the evaluation metric itself
- unequal-tuning: the method gets tuning, prompts, compute, data or search that the baselines did not get
- mismatched-setup: the compared rows differ in inputs, sensors, backbones, hardware or protocol
- small-or-saturated-benchmark: few test items, no variance reported, or a benchmark close to its ceiling
- missing-novelty-ablation: no experiment removes the new idea while keeping everything else
- other: anything else that could produce the number without the stated idea"""


def gates_audit(title: str, date: str, card_text: str, text: str, basis: str) -> str:
    return f"""TASK: gates_audit
Read one research work from its own text, carefully, the way a demanding reviewer would.

Work: {title} (first released {date or 'unknown date'})
Summary:
{card_text}

Text ({basis}, possibly truncated):
{clip(text, 45000)}

Answer in this order.

0. CLAIM VS DELIVERY. State the headline claim: what the title and abstract say the work solves or achieves.
   Words in the title count. If the title promises a property (for example that the method improves itself, adapts
   online, refines iteratively, is guaranteed, or generalises), check that this property is what the experiments show
   producing the gain.
   - "delivered": the experiments show the claimed thing, and the gain comes from it.
   - "partial": shown, but not fully. Say which kind in "partial_kind":
       "narrower"   = shown, but only in a narrower setting than claimed (fewer tasks, one robot, one dataset);
       "unisolated" = the gain is shown, but no experiment shows that the claimed component is what produces it.
   - "not": the claimed property is not realised, or the gain comes from something else. Then say what the work
     REALLY delivered, in plain words.

1. REASON. Does the work explain WHY its method should work, in a way that also says when it would not?
   - "proof": a derivation or guarantee.
   - "mechanism": a causal explanation that the paper ties to a condition under which it would NOT help. A causal
     story with no such condition is an "analogy" at best.
   - "analogy": justified only by resemblance to another method or field, or by a story the paper never bounds.
   - "none": no explanation beyond "it works in our experiments".
   An ablation showing that a component helps is evidence, not a reason. Set "fails_when_stated" to true only if the
   paper itself says when the method would fail or not help, and copy that sentence WORD FOR WORD from the text into
   "fails_when" (it is checked against the text; a paraphrase or a sentence you inferred counts as not stated).

2. ROBUSTNESS AND LEVERS. Do the gains repeat across benchmarks, settings, model sizes or data, against fair baselines?
   - "repeats", "single" (one benchmark or setting, or differences within noise), or "unclear".
   Then go through the levers that could produce the number without the stated idea:
{LEVER_MENU}
   For each lever you list, give its "status":
     "present"    = the text shows it (say where in "where": a table, section or quoted phrase);
     "controlled" = the paper rules it out (equal tuning, matched inputs, an ablation); say where;
     "suspected"  = possible, but the text neither shows nor rules it out.
   Only list levers you have looked for. Do not mark a lever "present" without a "where".

3. NEXT CHECK. The cheapest check that would confirm or kill the idea: a second prediction its reason makes, or the
   ablation that removes the novelty while keeping everything else.

4. CHECKS. Go through the experiments once more:
   - numbers: do the headline numbers in the abstract and introduction match the paper's own tables? "match",
     "mismatch" (say which) or "not checked" (no tables in the text you have). For a mismatch, set
     "numbers_severity": "headline" when the main claimed result is not backed by the tables, "minor" when only a
     secondary figure, rounding or a side remark is off.
   - fair_baselines: did the baselines get the same data, inputs, compute and tuning as the method? "yes", "no", "unclear".
   - novelty_ablation: is there an experiment that removes ONLY the new idea and keeps everything else? "yes" or "no".
   - code: "released" (give the URL), "promised", "none" or "unknown".
   - claims: the 2-4 main claims, each judged against the paper's own experiments: "supported", "partial",
     "unsupported" or "untested", with where the evidence is.
   - fairness_notes: what a careful reviewer would flag about how the comparisons were set up.

Use only the text. If it is too thin to answer a question, say so in that question's note and choose "partial",
"none", "unclear" or "not checked" rather than guessing.

Point to the text. "delivery_evidence" must name where (a table, figure, section or quoted phrase) and say what it
shows; "robustness_note" must name what was tested (which benchmarks, settings or scales) and what was not; each
lever's note must say where it shows. Write "" when you cannot point to the text. A judgement without a pointer is
not used to hide a work.

Return {{"claimed": "...", "delivery": "delivered|partial|not", "partial_kind": "narrower|unisolated|",
"delivered": "what it actually shows, one sentence",
"delivery_evidence": "where in the text, and why", "reason_type": "proof|mechanism|analogy|none",
"reason": "the why in one sentence, or 'none given'", "fails_when": "the paper's own sentence, copied exactly, or ''",
"fails_when_stated": true, "robustness": "repeats|single|unclear", "robustness_note": "one sentence",
"levers": [{{"lever": "cost-assumption", "status": "present|controlled|suspected", "where": "Table 3", "note": "one line"}}],
"check_next": "one sentence",
"checks": {{"numbers": "match|mismatch|not checked", "numbers_severity": "headline|minor|", "numbers_note": "...",
            "fair_baselines": "yes|no|unclear",
            "baselines_note": "...", "novelty_ablation": "yes|no", "ablation_note": "...",
            "code": "released|promised|none|unknown", "code_note": "URL or ''"}},
"claims": [{{"claim": "...", "support": "supported|partial|unsupported|untested", "evidence": "where and why"}}],
"fairness_notes": ["..."]}}"""


def gates_taste(profile: str, rows: List[Dict[str, str]]) -> str:
    listing = "\n".join(f"[{r['id']}] {r['short']}: starts from {clip(r.get('inherits', ''), 220)}; "
                        f"move: {clip(r.get('move', ''), 260)}; insight: {clip(r.get('insight', ''), 200)}"
                        + (f"\n    found in the paper: {clip(r['evidence'], 700)}" if r.get("evidence") else "")
                        for r in rows)
    return f"""TASK: gates_taste
A reader described what they find worth reading. Where the profile lists papers they liked or disliked, use those
as anchors: a work close to a liked paper scores high, one close to a disliked paper scores low.
---
{clip(profile, 4000)}
---
For each work below, score from 0 to 1 how much this reader would want to read it. Use the reader's own criteria:
for what they say about ideas and problems, look at the problem and the move; for what they say about evidence
(for example gains that come from tuning, mismatched baselines, missing ablations, untested big claims), look at
what a careful reading found in the paper, when given. Do not reward a work for being well known.

Works:
{listing}

Return {{"<id>": {{"score": 0.0, "why": "one line, in terms of the reader's profile"}}, ...}}"""
