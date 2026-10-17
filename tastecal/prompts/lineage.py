"""Every prompt the pipeline sends. Each starts with `TASK: <name>` so logs,
caches and test fakes can tell them apart."""
from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

from tastecal.core.model import RELATION_TYPES, Candidate, Card, Item, Node, Problem

SYSTEM = (
    "You reconstruct how a research field evolved. You think in problems: what problem a work "
    "inherits, what move it makes, and what limitations it leaves for others. You are concrete "
    "(mechanisms, numbers, named methods), plain-spoken, and you never assert anything the provided "
    "text does not support. Write in English. When asked for JSON, reply with JSON only."
)


def clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def relation_menu() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in RELATION_TYPES.items())


def card_block(item: Item, card: Optional[Card]) -> str:
    head = f"{item.title} ({item.year or '?'}, {item.kind})"
    if not card:
        return head + "\n  Abstract: " + clip(item.abstract, 700)
    leaves = "; ".join(card.leaves)
    return (f"{head}\n  Inherits: {card.inherits}\n  Move: {card.move}\n"
            f"  Insight: {card.insight}\n  Leaves: {leaves}")


# ---------------------------------------------------------------------------
def cards(items: List[Item], mentions: Dict[str, List[str]]) -> str:
    rows = []
    for it in items:
        said = mentions.get(it.id) or []
        said_txt = " | ".join(clip(s, 260) for s in said[:3])
        rows.append(
            f"[{it.id}] {it.title} ({it.date or it.year or '?'}, {it.kind}{', ' + it.venue if it.venue else ''})\n"
            f"Text: {clip(it.abstract, 1400) or '(no abstract available)'}\n"
            + (f"How other works describe it: {said_txt}\n" if said_txt else "")
        )
    return f"""TASK: cards
Reduce each item to a problem → move → limitation card. Use only the text given. If the text is thin, say less rather than guess.

For each item return an object with:
- "id": exactly as given
- "short": the 1-4 word name researchers use (e.g. "LoRA", "QLoRA", "Adapters"); for web items, a short descriptive name
- "inherits": the problem it starts from, one concrete sentence
- "move": what it does, one or two sentences, the mechanism rather than the marketing
- "insight": the idea that makes the move work, one sentence
- "leaves": 1-3 limitations or open questions it leaves (stated or clearly implied); each one sentence and specific enough to search for
- "summary": one plain-language sentence for someone new to the field
- "date_guess": "YYYY-MM" if the text states when it was published, else ""

Items:
{chr(10).join(rows)}
Return a JSON array with one object per item."""


def classify_links(anchor: Node, cands: List[Candidate], direction: str) -> str:
    if direction == "backward":
        how = ("Each candidate below is CITED BY the anchor. The sentences are where the anchor cites it. "
               "Keep a candidate if it supplied the problem, the limitation, or the insight that the anchor builds on, "
               "or if it is a direct competitor the anchor positions itself against.")
    else:
        how = ("Each candidate below CITES the anchor. The sentences are where the candidate cites the anchor. "
               "Keep a candidate if it fixes, extends, challenges, competes with, applies, or explains the anchor. "
               "Drop works that merely use the anchor as a tool or baseline without engaging its problem.")
    rows = []
    for c in cands:
        it = c.item
        ctx = "\n".join(f"    {i + 1}) {clip(s, 320)}" for i, s in enumerate(c.contexts[:3])) or "    (no sentences available)"
        rows.append(
            f"[{it.id}] {it.title} ({it.date or it.year or '?'}; citations: {it.citations if it.citations is not None else '?'}"
            f"{'; marked influential' if c.influential else ''}{'; intents: ' + ','.join(c.intents) if c.intents else ''})\n"
            f"  Abstract: {clip(it.abstract, 650) or '(none)'}\n  Citing sentences:\n{ctx}"
        )
    return f"""TASK: classify_links
We are growing a lineage graph that shows who solved whose problem.

Anchor:
{card_block(anchor.item, anchor.card)}

Direction: {direction.upper()}. {how}

Relation types, always read as "LATER work <type> EARLIER work":
{relation_menu()}
For dropped candidates use "uses" (tool, dataset, baseline) or "background" (generic citation).

For each candidate return:
{{"id": "...", "keep": true/false, "type": "...",
  "label": "one concrete sentence: what the later work does about the earlier work's problem",
  "problem": "the earlier work's problem or limitation, a short phrase",
  "evidence": "the most telling verbatim quote (<=200 chars) from the sentences or abstract, or empty",
  "confidence": "stated" if the text says it explicitly, otherwise "inferred",
  "strength": 0.0-1.0, how central the link is to the anchor's lineage}}

Candidates:
{chr(10).join(rows)}

Return a JSON array."""


def scope_check(scope: str, items: List[Item]) -> str:
    rows = "\n".join(
        f"[{it.id}] {it.title} ({it.date or it.year or '?'}, {it.kind}{', ' + it.venue if it.venue else ''})\n"
        f"  Text: {clip(it.abstract, 500) or '(none)'}" for it in items)
    return f"""TASK: scope_check
The map is limited to this field: {scope}

For each work below, decide whether it belongs to that field. It belongs when its own problem, data or evaluation is in the field. Surveys, benchmarks and analyses of the field belong, and so does a general method applied to the field's own problem. It does not belong when it is a general method or tool from another field that this field later borrowed, for example a generic diffusion model, a vision backbone, an optimizer or a language model, however famous it is here.

For each work return {{"id": exactly as given, "in_scope": true or false, "field": "its own field in 2-5 words"}}.

Works:
{rows}

Return a JSON array."""


def problem_queries(problems: List[Problem], field_hint: str, names: Dict[str, str]) -> str:
    rows = "\n".join(f"[{p.id}] {p.text} (raised by {', '.join(names.get(r, r) for r in p.raised_by) or '?'})"
                     for p in problems)
    return f"""TASK: problem_queries
Field context: {field_hint}

For each open problem, write 1-2 keyword-style search queries (4-8 words) that would find papers whose main contribution addresses it. Use the field's own vocabulary.

Problems:
{rows}

Return a JSON object mapping problem id to a list of queries, e.g. {{"P3": ["...", "..."]}}."""


def problem_matches(problem: Problem, raiser: Optional[Node], cands: List[Item]) -> str:
    rows = "\n".join(
        f"[{it.id}] {it.title} ({it.date or it.year or '?'}, {it.kind}; citations: {it.citations if it.citations is not None else '?'})\n"
        f"  Text: {clip(it.abstract, 650) or '(none)'}" for it in cands)
    raised = card_block(raiser.item, raiser.card) if raiser else "(unknown)"
    return f"""TASK: problem_matches
Open problem [{problem.id}]: {problem.text}
Raised by:
{raised}

The candidates below came from a keyword search. Keep only those whose main contribution tackles this problem.
Relation types, read as "LATER candidate <type> the work that raised the problem":
{relation_menu()}

For each candidate return {{"id", "keep", "type", "label" (one concrete sentence), "evidence" (verbatim quote <=200 chars or ""),
"confidence" ("stated" only if the text names the earlier work or this exact problem, else "inferred"), "strength" (0-1)}}.

Candidates:
{rows}

Return a JSON array."""


def ledger_update(ledger_rows: List[Problem], new_nodes: List[Node], names: Dict[str, str]) -> str:
    led = "\n".join(
        f"[{p.id}] {p.text} (raised by {', '.join(names.get(r, r) for r in p.raised_by) or '?'};"
        f" addressed by {', '.join(names.get(a, a) for a in p.addressed_by) or 'nobody yet'})"
        for p in ledger_rows) or "(empty)"
    items = "\n".join(
        f"[{n.item.id}] {n.card.short if n.card else n.item.title} ({n.item.year}): inherits: {n.card.inherits if n.card else ''}; "
        f"move: {n.card.move if n.card else ''}; leaves: {json.dumps(n.card.leaves if n.card else [])}"
        for n in new_nodes)
    return f"""TASK: ledger_update
We keep a ledger of problems. Limitations open entries; later works close them.

Current ledger:
{led}

New works:
{items}

For each new work return:
- "addresses": ids of ledger problems its move substantially tackles ([] if none)
- "leaves": one entry per limitation it leaves, either {{"same_as": "P4"}} when it is the same problem as an existing entry, or {{"new": "the problem restated in one general sentence"}}

Return a JSON object keyed by work id, e.g. {{"id": {{"addresses": ["P2"], "leaves": [{{"same_as": "P4"}}, {{"new": "..."}}]}}}}."""


def ledger_merge(open_problems: List[Problem], fresh: List[str]) -> str:
    rows = "\n".join(f"[{p.id}]{' (new)' if p.id in fresh else ''} {p.text}" for p in open_problems)
    return f"""TASK: ledger_merge
These are the open problems in a ledger of a research field. Several papers often raise the same problem in
different words. Group the entries that state the SAME underlying problem, so that solving one would solve the
others. Do not group problems that are merely related, or where one is a narrower case of the other.
Only return groups that contain at least one entry marked (new).

{rows}

Return {{"groups": [["P3", "P17"], ["P9", "P21", "P22"]]}} (an empty list when nothing repeats)."""


def works_block(nodes: Iterable[Node]) -> str:
    out = []
    for n in nodes:
        c = n.card
        if c:
            out.append(f"[{n.item.id}] {c.short} ({n.item.date or n.item.year}, {n.item.kind}): inherits: {c.inherits} "
                       f"| move: {c.move} | insight: {c.insight} | leaves: {'; '.join(c.leaves)}")
        else:
            out.append(f"[{n.item.id}] {n.item.title} ({n.item.year})")
    return "\n".join(out)


def problems_block(problems: List[Problem]) -> str:
    return "\n".join(f"[{p.id}] {p.text} — raised by {p.raised_by or '?'} — addressed by {p.addressed_by or 'nobody'}"
                     for p in problems)


def threads(seed: Node, nodes: List[Node], problems: List[Problem]) -> str:
    return f"""TASK: threads
Seed: [{seed.item.id}] {seed.item.title}

Group the problems below into 3-6 problem threads. A thread is one persistent question the field keeps working on
(e.g. "How do you fit fine-tuning of a huge model into GPU memory?"), not a method family.
Order threads so related ones sit next to each other, with the thread closest to the field's original motivation first.

Problems:
{problems_block(problems)}

Works:
{works_block(nodes)}

Return:
{{"threads": [{{"id": "T1", "name": "2-4 words", "question": "one sentence ending with ?",
               "problems": ["P1", ...], "status": "open" | "active" | "largely solved", "status_note": "one sentence"}}],
  "assign": {{"<work id>": ["T2", "T1"]}}}}
Every work gets at least one thread, primary first. The seed lists every thread it touches."""


def why_ladders(thread_rows: List[dict], nodes_by_id: Dict[str, Node], problems: Dict[str, Problem]) -> str:
    blocks = []
    for t in thread_rows:
        probs = "\n".join(f"    - {problems[p].text}" for p in t.get("problems", []) if p in problems)
        works = "\n".join(f"    - {nodes_by_id[w].card.short if nodes_by_id[w].card else nodes_by_id[w].item.title} "
                          f"({nodes_by_id[w].item.year}): {nodes_by_id[w].card.move if nodes_by_id[w].card else ''}"
                          for w in t.get("nodes", []) if w in nodes_by_id)
        blocks.append(f"[{t['id']}] {t['name']}: {t['question']}\n  Problems:\n{probs}\n  Works:\n{works}")
    return f"""TASK: why_ladders
For each thread, build a why-ladder a newcomer can follow. Start from the concrete symptom researchers ran into,
then ask "why is this hard?" again and again until you reach a root no single paper can change: a hardware or
physical limit, a mathematical fact, a property of data, an economic fact, or the field's goal itself.
Use 3-5 rungs. Each rung is one or two plain sentences, concrete (mechanisms and numbers from the works where available).

Threads:
{chr(10).join(blocks)}

Return {{"T1": {{"rungs": [{{"kind": "symptom", "text": "..."}}, {{"kind": "why", "text": "..."}}, {{"kind": "root", "text": "..."}}],
        "root_type": "hardware" | "math" | "data" | "goal" | "economics" | "other"}}, ...}}"""


def field(seed: Node, nodes: List[Node], thread_rows: List[dict], ladders: dict) -> str:
    th = []
    for t in thread_rows:
        lad = ladders.get(t["id"], {})
        rungs = " → ".join(r.get("text", "") for r in lad.get("rungs", []))
        th.append(f"[{t['id']}] {t['name']}: {t['question']}\n  Ladder ({lad.get('root_type', '?')}): {rungs}\n"
                  f"  Works: {', '.join(t.get('nodes', []))}")
    return f"""TASK: field
Seed: [{seed.item.id}] {seed.item.title}

Explain the mechanism behind this whole body of work for a newcomer. Use the threads and why-ladders.

Threads:
{chr(10).join(th)}

Works:
{works_block(nodes)}

Return:
{{"field": "the field's name in a few words",
  "goal": "what the field is ultimately trying to do, one sentence",
  "core_tension": "the trade-off every work moves along, one or two sentences",
  "enabling_insights": [{{"text": "a fact about the world that made progress possible", "nodes": ["ids that established it"]}}],
  "driving_forces": [{{"id": "F1", "name": "3-6 words", "statement": "2-3 sentences: the constraint, why it bites, which moves it allows",
                      "root_type": "hardware|math|data|goal|economics|other", "threads": ["T1"]}}],
  "external_drivers": [{{"text": "an event outside the papers that changed the pressure", "year": 2020, "nodes": []}}],
  "knock_on": [{{"from_thread": "T2", "to_thread": "T3", "via": "<work id>", "text": "how solving one problem created another"}}],
  "open_problems": ["one sentence each"],
  "roles": {{"<work id>": "foundation|driver|turning-point|improvement|branch|frontier|explainer"}}}}
Use 1-4 driving forces; merge threads whose ladders end at the same root. Every thread belongs to exactly one force.
Give a role to every work except the seed."""


def predict(field_obj: dict, cutoff: str) -> str:
    forces = "\n".join(f"- {f['name']}: {f['statement']}" for f in field_obj.get("driving_forces", []))
    return f"""TASK: predict
Field: {field_obj.get('field', '')}
Goal: {field_obj.get('goal', '')}
Core tension: {field_obj.get('core_tension', '')}
Driving forces:
{forces}

Knowing only the above, and only the state of the field up to {cutoff}, predict 4-6 concrete moves researchers would make next.
Return {{"predictions": ["one sentence each"]}}"""


def _early_block(nodes) -> str:
    out = []
    for n in nodes:
        c = n.card
        out.append(f"- {c.short if c else n.item.title} ({n.item.date or n.item.year}): "
                   + (f"move: {clip(c.move, 200)}; leaves: {clip('; '.join(c.leaves), 200)}" if c else clip(n.item.title, 120)))
    return "\n".join(out)


def early_forces(field_name: str, goal: str, early: List[Node], problems: List[Problem], cutoff: str) -> str:
    probs = "\n".join(f"- {p.text}" for p in problems[:60]) or "(none)"
    return f"""TASK: early_forces
Field: {field_name}
Goal: {goal}
Below are the works of this field up to {cutoff}, and the problems they left open. Use ONLY these; do not use
anything you know about later work.

Works up to {cutoff}:
{_early_block(early)}

Open problems at {cutoff}:
{probs}

Name 1-4 driving forces: lasting constraints (hardware, mathematics, data, economics, the field's goal) that
explain why the work moved the way it did up to {cutoff}.
Return {{"driving_forces": [{{"id": "F1", "name": "3-6 words", "statement": "2-3 sentences: the constraint, why it bites, which moves it allows"}}]}}"""


def predict_null(field_name: str, goal: str, early: List[Node], cutoff: str) -> str:
    return f"""TASK: predict_null
Field: {field_name}
Goal: {goal}
Works up to {cutoff}:
{_early_block(early)}

Knowing only these works, and only the state of the field up to {cutoff}, predict 4-6 concrete moves researchers
would make next.
Return {{"predictions": ["one sentence each"]}}"""


def check_blind(predictions: List[tuple], recent: List[Node], outside: List[dict]) -> str:
    preds = "\n".join(f"[{k}] {t}" for k, t in predictions)
    later = works_block(recent)
    extra = "\n".join(f"[{w['id']}] {w['title']} ({w['date']}): {clip(w.get('abstract', ''), 300)}" for w in outside)
    return f"""TASK: check_blind
Predictions about where a research field would go next:
{preds}

Later works:
{later}
{extra}

For each prediction:
- "matched": ids of later works that clearly realise it ([] if none). A work that is merely on the same topic
  does not realise a prediction.
- "evidence": for the best match, what in that work realises the prediction (one line), or "".
- "specificity": 1 = so broad that almost any later work would match ("models will get better"); 2 = names a
  direction; 3 = names a concrete method, setting or result that could have turned out false.

Return {{"predictions": [{{"id": "A1", "matched": ["ids"], "evidence": "...", "specificity": 2}}]}}"""


def check_predictions(predictions: List[str], recent: List[Node], all_nodes: List[Node], forces: List[dict]) -> str:
    preds = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(predictions))
    fs = "\n".join(f"[{f['id']}] {f['name']}: {f['statement']}" for f in forces)
    return f"""TASK: check_predictions
Predictions made from the driving forces alone:
{preds}

Recent works:
{works_block(recent)}

1) For each prediction, list the ids of recent works that realise it (or []).
2) Driving forces:
{fs}
List any work (from all works below) that does not fit any force, with one line on why.

All works:
{works_block(all_nodes)}

Return {{"predictions": [{{"text": "...", "matched": ["ids"]}}], "misfits": [{{"id": "...", "why": "..."}}]}}"""


def misfits(all_nodes: List[Node], forces: List[dict]) -> str:
    fs = "\n".join(f"[{f['id']}] {f['name']}: {f['statement']}" for f in forces)
    return f"""TASK: misfits
Driving forces of a research field:
{fs}

List any work below that does not fit any of these forces, with one line on why.

All works:
{works_block(all_nodes)}

Return {{"misfits": [{{"id": "...", "why": "..."}}]}}"""


def narrative(field_obj: dict, thread_rows: List[dict], nodes: List[Node]) -> str:
    forces = "\n".join(f"- {f['name']}: {f['statement']}" for f in field_obj.get("driving_forces", []))
    th = "\n".join(f"- [{t['id']}] {t['name']}: {t['question']}" for t in thread_rows)
    return f"""TASK: narrative
Write the story of this field for someone new to it: 5-7 short paragraphs in plain language, no hype.
Follow the driving forces rather than the calendar alone. Mention works as [[id]] with the exact ids below, the first time
each important one appears; mention 12-20 works in total, but at most three in any one sentence. Explain a mechanism in
one short clause where a newcomer needs it. End with what is still open.

Goal: {field_obj.get('goal', '')}
Core tension: {field_obj.get('core_tension', '')}
Driving forces:
{forces}
Threads:
{th}
Works:
{works_block(nodes)}

Return {{"title": "a short headline for the story", "paragraphs": ["...", "..."]}}"""


def outlook(field_obj: dict, thread_rows: List[dict], problems: List[dict], nodes: List[dict], today: str) -> str:
    """Next steps for the open problems, and the assumptions the whole map shares. Works on graph dicts."""
    forces = "\n".join(f"- {f.get('name', '')}: {f.get('statement', '')}" for f in field_obj.get("driving_forces", []))
    th = "\n".join(f"- [{t['id']}] {t.get('name', '')}: {t.get('question', '')} ({t.get('status', '')})" for t in thread_rows)
    probs = "\n".join(f"[{p['id']}] ({p.get('status', '')}, thread {p.get('thread', '')}) {p.get('text', '')} "
                      f"— addressed by {p.get('addressed_by') or 'nobody'}" for p in problems)
    works = "\n".join(f"[{n['id']}] {n.get('short', '')} ({n.get('date', '')}): {clip((n.get('card') or {}).get('move', ''), 220)}"
                      for n in nodes)
    return f"""TASK: outlook
Today is {today}. Below are the threads, the problem ledger and the works of one research map.

Do two things, and do not predict anything the map does not support.

1. NEXT STEPS. Pick the 3-6 most important problems that are still open or only partly addressed. For each, name the
   closest current attempts (work ids from the list, most recent first) and the one experiment or result that would
   settle the question. Concrete: a benchmark, a comparison, an ablation, a deployment test.
2. SHARED ASSUMPTIONS. List 3-5 assumptions that most works on the map take for granted and rarely test (about the data,
   the people involved, the setting, the evaluation, the hardware). For each, say which threads and works rely on it,
   and what would change if it turned out to be wrong. A new direction usually starts where one of these breaks; do not
   claim which one will.

Driving forces:
{forces}
Threads:
{th}
Problems:
{probs}
Works:
{works}

Return {{"next_steps": [{{"problem": "P3 or ''", "text": "the open question, one sentence", "attempts": ["ids"],
                    "settle": "the experiment or result that would settle it, one or two sentences"}}],
  "assumptions": [{{"text": "the assumption, one sentence", "threads": ["T1"], "nodes": ["ids"],
                    "if_broken": "what would change, one sentence"}}]}}"""


def polish(rows: List[dict], rules: str) -> str:
    listing = "\n".join(f"[{r['k']}] {r['text']}\n    problems: {'; '.join(r['issues'])}" for r in rows)
    return f"""TASK: polish
Rewrite each text below in plain language. Keep its meaning, every fact, every number, every method name and every
[[id]] link. Do not add anything. Split long sentences; where one sentence names many works, keep the two or three that
matter most for the point and group the rest ("several works" or "later works such as [[a]] and [[b]]"), but every
[[id]] link in the original must still appear somewhere in your rewrite. Keep the text's language.

Rules:
{rules}

Texts:
{listing}

Return {{"t1": "rewritten text", "t2": "...", ...}} with one entry per text."""
