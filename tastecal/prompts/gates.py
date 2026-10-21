"""Prompts for the gates (TASK names start with gates_).

The audit prompt reads one work's own text and never sees the reader's taste profile.
"""
from __future__ import annotations

from typing import Dict, List

from tastecal.prompts.lineage import SYSTEM, clip

GATES_SYSTEM = (SYSTEM + " Judge only the evidence in the text in front of you, not how well known a work might be. "
                "Papers are released when they beat their chosen baselines, so beating a baseline is not, by itself, "
                "evidence of anything: ask where the gain comes from.")

LEVER_MENU = """- cost-assumption: savings or speed-ups depend on a price, cost ratio or hardware figure the authors chose
- metric-trained: a component is trained or tuned to predict or maximise the benchmark's own scoring function (for
  example a learned scorer that imitates the evaluator, or selection on the test metric). Ordinary training on the
  task's usual loss is NOT this lever, even when the loss resembles the metric
- unequal-tuning: the method gets tuning, prompts, compute, data or search that the baselines did not get
- mismatched-setup: the method got inputs, sensors, a backbone, data, hardware or a protocol that the compared
  baselines did not, AND that difference is not the paper's own contribution. A difference that IS the new idea is
  what is being tested, not a lever
- small-or-saturated-benchmark: few test items, no variance reported, or a benchmark close to its ceiling
- missing-novelty-ablation: no experiment removes the new idea while keeping everything else
- other: anything else that could produce the number without the stated idea"""


def gates_audit(title: str, date: str, card_text: str, text: str, basis: str, coverage: str = "") -> str:
    return f"""TASK: gates_audit
Read one research work from its own text, carefully, the way a demanding reviewer would.

Work: {title} (first released {date or 'unknown date'})
Summary:
{card_text}

Text ({basis}):
{clip(text, 66000)}
{coverage}

Answer in this order.

A. EVALUATION FIT. Before looking at any number, decide what the evaluation could possibly show.
   - "property": the property or capability the work claims to add, quoted from the text ("property_quote": a phrase
     of at least five words, copied word for word; it is checked against the text).
   - "shown_by": the metrics and the test setting used to show it.
   - "can_show": would those numbers look different if the claimed property were absent? "yes", "partly" or "no",
     with one sentence in "fit_why". "no" means the metric would score a method the same with or without the
     property, or the test setting removes the conditions under which the property matters. "yes" means the property
     changes the measured outcome directly. Reason from this paper's own claim and setup only.
   - "kind": "method", "testing" (it generates tests, attacks or scenarios for another system), "benchmark",
     "analysis" or "other".
   - "threat_model" (testing work only): what the tester knows or can access about the system under test (its plan,
     gradients, internals, or only queries). Information the tester uses by design is part of its threat model:
     against non-adversarial baselines (replayed or cooperative behaviour), which are lower bounds, it is not a lever.
     Against other test or attack methods, a difference in access IS a lever ("mismatched-setup") when the paper
     claims to beat them; name both threat models in its note.
   - If two compared methods pursue the same objective and differ only in how they solve it, say so in "fit_why".

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
   Only list levers you have looked for. Do not mark a lever "present" without a "where", and copy into "quote" the
   exact words from the text that show it (at least five words; it is checked against the text, and a lever whose
   quote is not found does not count).

3. WHAT TO CHECK WHEN READING. The one place in this paper a reader should look to confirm or doubt the idea (a
   table, an ablation, a setting, a sentence), and what to look for there. Do not propose new experiments.

4. CHECKS. Go through the experiments once more:
   - numbers: do the headline numbers in the abstract and introduction match the paper's own tables? "match",
     "mismatch" (say which) or "not checked" (no tables in the text you have). For a mismatch, set
     "numbers_severity": "headline" when the main claimed result is not backed by the tables, "minor" when only a
     secondary figure, rounding or a side remark is off.
   - fair_baselines: did the baselines get the same data, inputs, compute and tuning as the method? "yes", "no", "unclear".
   - novelty_ablation: is there an experiment that removes ONLY the new idea and keeps everything else? "yes", "no",
     or "unknown" when the supplied text omits sections or appendices where the experiment could be reported.
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

Return {{"eval_fit": {{"property": "...", "property_quote": "exact words", "shown_by": "...", "can_show": "yes|partly|no",
"fit_why": "one sentence", "kind": "method|testing|benchmark|analysis|other", "threat_model": "... or ''"}},
"claimed": "...", "delivery": "delivered|partial|not", "partial_kind": "narrower|unisolated|",
"delivered": "what it actually shows, one sentence",
"delivery_evidence": "where in the text, and why", "reason_type": "proof|mechanism|analogy|none",
"reason": "the why in one sentence, or 'none given'", "fails_when": "the paper's own sentence, copied exactly, or ''",
"fails_when_stated": true, "robustness": "repeats|single|unclear", "robustness_note": "one sentence",
"levers": [{{"lever": "cost-assumption", "status": "present|controlled|suspected", "where": "Table 3", "quote": "exact words",
"note": "one line"}}],
"check_next": "one sentence",
"checks": {{"numbers": "match|mismatch|not checked", "numbers_severity": "headline|minor|", "numbers_note": "...",
            "fair_baselines": "yes|no|unclear",
            "baselines_note": "...", "novelty_ablation": "yes|no|unknown", "ablation_note": "...",
            "code": "released|promised|none|unknown", "code_note": "URL or ''"}},
"claims": [{{"claim": "...", "support": "supported|partial|unsupported|untested", "evidence": "where and why"}}],
"fairness_notes": ["..."]}}"""


