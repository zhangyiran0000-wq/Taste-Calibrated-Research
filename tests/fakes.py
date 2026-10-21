"""Offline stand-ins for the literature APIs and the LLM, so the whole pipeline
can be exercised without network access or API keys."""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from tastecal.core.llm import LLM
from tastecal.core.model import Candidate, Item
from tastecal.sources import Source


def _item(pid: str, title: str, year: int, cites: int, abstract: str) -> Item:
    return Item(id="s2:" + pid, title=title, year=year, date=f"{year}-06", authors=["Ada Lovelace", "Alan Turing", "Grace Hopper"],
                venue="TestConf", url=f"https://example.org/{pid}", abstract=abstract, citations=cites, ids={"s2": pid})


CORPUS: Dict[str, Item] = {i.ids["s2"]: i for i in [
    _item("seed", "SeedNet: Cheap Adaptation", 2021, 900, "We adapt big models cheaply. It still needs much memory."),
    _item("a", "Alpha: Small Updates Suffice", 2018, 400, "Updates live in a small subspace."),
    _item("b", "Beta Adapters", 2019, 600, "Insert small layers. They add latency."),
    _item("z", "Zeta Dataset", 2017, 5000, "A benchmark dataset."),
    _item("c", "Gamma: Quantized SeedNet", 2022, 300, "Quantize the frozen model to cut SeedNet's memory."),
    _item("d", "Delta: Fixing Gamma Error", 2023, 120, "Gamma introduces quantization error; we fix the initialization."),
    _item("e", "Epsilon: Rank Allocation", 2024, 80, "Allocate rank adaptively across layers."),
]}
REFS = {"seed": ["a", "b", "z"], "c": ["seed"], "d": ["c", "seed"], "e": ["seed"]}


class FakeSource(Source):
    def resolve(self, ref: str) -> Item:
        return CORPUS["seed"]

    def backward(self, item: Item, anchor_id: str) -> List[Candidate]:
        out = []
        for r in REFS.get(item.ids["s2"], []):
            ctx = [f"Unlike {CORPUS[r].title}, which suffers from a limitation, we improve it."] if r != "z" else ["We use the Zeta dataset."]
            out.append(Candidate(item=CORPUS[r], anchor_id=anchor_id, direction="backward", contexts=ctx, prior=1.0))
        return out

    def forward(self, item: Item, anchor_id: str) -> List[Candidate]:
        pid = item.ids["s2"]
        out = []
        for citing, refs in REFS.items():
            if pid in refs:
                out.append(Candidate(item=CORPUS[citing], anchor_id=anchor_id, direction="forward",
                                     contexts=[f"We address the memory limitation of {item.title}."], prior=1.0))
        return out

    def search(self, query: str, year_from: Optional[int], limit: int = 15,
               year_to: Optional[int] = None) -> List[Item]:
        if year_to:   # precedent search: earlier work only
            return [i for i in CORPUS.values() if (i.year or 0) <= year_to][:limit]
        return [CORPUS["e"]]

    def citation_context(self, citing: Item, cited: Item) -> Optional[Candidate]:
        return None


class FakeLLM(LLM):
    name = "fake"

    def __init__(self):
        super().__init__(cache_dir=None)
        self.tasks: List[str] = []
        self.prompts: List[tuple] = []

    @staticmethod
    def _ids(text: str, after: str = "") -> List[str]:
        if after and after in text:
            text = text.split(after, 1)[1]
        return list(dict.fromkeys(re.findall(r"^\[([^\]]+)\]", text, re.M)))

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        task = prompt.split("\n", 1)[0].replace("TASK:", "").strip()
        self.tasks.append(task)
        self.prompts.append((task, prompt))
        fn = getattr(self, "t_" + task)
        return json.dumps(fn(prompt))

    def t_cards(self, p):
        out = []
        for i in self._ids(p, "Items:"):
            out.append({"id": i, "short": i.split(":")[-1].upper(), "inherits": f"problem before {i}",
                        "move": f"{i} does a thing", "insight": "small is enough",
                        "leaves": [f"limitation of {i}"], "summary": f"{i} in plain words", "date_guess": ""})
        return out

    def t_classify_links(self, p):
        direction = "backward" if "Direction: BACKWARD" in p else "forward"
        out = []
        for i in self._ids(p, "Candidates:"):
            drop = i.endswith(":z")
            out.append({"id": i, "keep": not drop, "type": "uses" if drop else ("inspires" if direction == "backward" else "resolves"),
                        "label": f"link to {i}", "problem": "memory", "evidence": "we improve it", "confidence": "stated",
                        "strength": 0.8})
        return out

    def t_problem_queries(self, p):
        return {i: ["rank allocation"] for i in self._ids(p, "Problems:") if i.startswith("P")}

    def t_problem_matches(self, p):
        return [{"id": i, "keep": True, "type": "resolves", "label": "tackles it", "evidence": "", "confidence": "inferred",
                 "strength": 0.6} for i in self._ids(p, "Candidates:")]

    def t_ledger_update(self, p):
        ledger = [i for i in self._ids(p.split("New works:")[0]) if i.startswith("P")]
        return {i: {"addresses": ledger[:1], "leaves": [{"new": f"new limitation from {i}"}]}
                for i in self._ids(p, "New works:")}

    def t_threads(self, p):
        works = self._ids(p, "Works:")
        probs = [i for i in self._ids(p.split("Works:")[0]) if i.startswith("P")]
        assign = {w: (["T1", "T2"] if k == 0 else [("T1", "T2")[k % 2]]) for k, w in enumerate(works)}
        return {"threads": [
            {"id": "T1", "name": "Memory", "question": "How to fit it?", "problems": probs[::2], "status": "active", "status_note": "x"},
            {"id": "T2", "name": "Capacity", "question": "Is small enough?", "problems": probs[1::2], "status": "open", "status_note": "y"}],
            "assign": assign}

    def t_why_ladders(self, p):
        return {t: {"rungs": [{"kind": "symptom", "text": "s"}, {"kind": "why", "text": "w"}, {"kind": "root", "text": "r"}],
                    "root_type": "hardware"} for t in ("T1", "T2")}

    def t_field(self, p):
        works = self._ids(p, "Works:")
        return {"field": "Toy field", "goal": "g", "core_tension": "t",
                "enabling_insights": [{"text": "small is enough", "nodes": works[:1]}],
                "driving_forces": [{"id": "F1", "name": "Memory wall", "statement": "s", "root_type": "hardware", "threads": ["T1"]},
                                   {"id": "F2", "name": "Rank bet", "statement": "s", "root_type": "math", "threads": ["T2"]}],
                "external_drivers": [{"text": "bigger models", "year": 2020, "nodes": []}],
                "knock_on": [{"from_thread": "T1", "to_thread": "T2", "via": works[-1], "text": "k"}],
                "open_problems": ["o"], "roles": {w: "improvement" for w in works}}

    def t_predict(self, p):
        return {"predictions": ["quantize more", "allocate rank"]}

    def t_check_predictions(self, p):
        recent = self._ids(p.split("Driving forces:")[0], "Recent works:")
        return {"predictions": [{"text": "quantize more", "matched": recent[:1]}, {"text": "allocate rank", "matched": []}],
                "misfits": []}

    def t_early_forces(self, p):
        return {"driving_forces": [{"id": "F1", "name": "Memory is scarce", "statement": "GPU memory limits what can be tuned."}]}

    def t_predict_null(self, p):
        return {"predictions": ["models get better"]}

    def t_check_blind(self, p):
        ids = re.findall(r"^\[(A\d+)\] (.*)$", p, re.M)
        later = [i for i in self._ids(p, "Later works:") if not i.startswith("A")]
        out = []
        for k, text in ids:
            if text == "quantize more":
                out.append({"id": k, "matched": later[:1], "evidence": "it quantizes", "specificity": 3})
            elif text == "models get better":
                out.append({"id": k, "matched": later[:1], "evidence": "it is better", "specificity": 1})
            else:
                out.append({"id": k, "matched": [], "evidence": "", "specificity": 2})
        return {"predictions": out}

    def t_misfits(self, p):
        return {"misfits": []}

    def t_narrative(self, p):
        works = self._ids(p, "Works:")
        return {"title": "Toy story", "paragraphs": [f"It began with [[{works[0]}]] and [[not-a-node]].", "Then more."]}

    # --- audit ------------------------------------------------------------------
    # Cards say "<internal id> does a thing", so the fake can tell works apart in a blind pack
    # without seeing any title: s2:b is weak, s2:e is strong, everything else is middling.
    @staticmethod
    def _which(p):
        return "weak" if "s2:b does" in p else "strong" if "s2:e does" in p else "mid"

    def t_audit_citation_roles(self, p):
        n = len(re.findall(r"^\[\d+\]", p, re.M))
        return [{"i": k + 1, "role": ("builds_on", "baseline", "mentions")[k % 3]} for k in range(n)]

    def t_audit_claims(self, p):
        return {"claims": [{"claim": "it is better", "support": "partial", "evidence": "Table 1, small gain"}],
                "fairness_notes": ["uses an extra input"]}

    def t_audit_mechanism(self, p):
        return {"mechanism": "update few weights", "queries": ["few weights"]}

    def t_audit_precedents(self, p):
        ids = self._ids(p)
        return [{"id": i, "overlap": "same idea" if k == 0 else "different", "note": "same trick"} for k, i in enumerate(ids)]

    def t_audit_contribution(self, p):
        score = {"weak": 0.3, "strong": 0.8, "mid": 0.55}[self._which(p)]
        return {"type": "method", "novelty": score, "significance": score, "evidence": score, "uptake": score,
                "score": score, "rationale": f"Scored {score}. Based on the pack."}

    def t_audit_advocate(self, p):
        return {"case": "it matters", "strongest_evidence": ["later paper 1 builds on it"]}

    def t_audit_critic(self, p):
        return {"case": "it is redundant", "strongest_evidence": ["same idea earlier"]}

    def t_audit_judge(self, p):
        v = {"weak": "negligible", "strong": "substantial", "mid": "modest"}[self._which(p)]
        return {"verdict": v, "confidence": "medium", "reasons": [f"judged {v}"], "would_change": "more evidence"}

    def t_ledger_merge(self, p):
        return {"groups": []}

    def t_audit_attention(self, p):
        m = re.search(r"Citations: (\d+)", p)
        few = m is not None and int(m.group(1)) < 100
        return {"verdict": "under-noticed" if few else "well noticed", "why": "from the counts"}

    # --- gates ------------------------------------------------------------------
    # Fictional answers keyed by the internal id inside the card text ("s2:x does a thing"):
    #   seed, a  a reason and gains that repeat          -> solid
    #   b        the headline claim is not what is shown -> not-delivered
    #   c, d     delivered, no reason, one setting       -> incremental
    #   e        a mechanism, one setting                -> treasure
    GATES = {
        "seed": ("delivered", "mechanism", "repeats"), "a": ("delivered", "proof", "repeats"),
        "b": ("not", "mechanism", "single"), "c": ("delivered", "none", "single"),
        "d": ("delivered", "analogy", "single"), "e": ("partial", "mechanism", "single"),
    }

    @staticmethod
    def _gate_key(p):
        m = re.search(r"Move: (?:s2:)?(\w+) does", p)   # synthesis may have re-keyed the shared corpus
        return m.group(1) if m else "c"

    def t_gates_audit(self, p):
        k = self._gate_key(p)
        d, rt, rb = self.GATES.get(k, ("delivered", "none", "single"))
        return {"claimed": f"{k} claims a property", "delivery": d, "delivered": f"{k} shows something narrower",
                "delivery_evidence": "Table 2: the claimed part adds nothing once tuning is equal",
                "reason_type": rt, "reason": f"why {k} works",
                "fails_when": "It would not help when the training data are small and noisy.",
                "robustness": rb, "robustness_note": "one benchmark (Table 2), no variance" if rb == "single" else "three benchmarks",
                "levers": [{"lever": "unequal-tuning", "note": "only the method was tuned"}, "a made-up lever"],
                "check_next": f"remove the new part of {k}", "fails_when_stated": k != "e" or True,
                "checks": {"numbers": "match", "numbers_note": "Table 2 matches the abstract",
                           "fair_baselines": "no" if k in ("c", "d") else "yes", "baselines_note": "only the method was tuned",
                           "novelty_ablation": "no", "ablation_note": "no row removes the new part",
                           "code": "released", "code_note": "https://github.com/example/repo", "bogus": "x"},
                "claims": [{"claim": f"{k} is better", "support": "partial", "evidence": "Table 2"}],
                "fairness_notes": ["baselines were not re-tuned"]}

    def t_polish(self, p):
        out = {}
        for k in re.findall(r"^\[(t\d+)\] ", p, re.M):
            text = re.search(r"^\[" + k + r"\] (.*)$", p, re.M).group(1)
            out[k] = text.replace(", and ", ". And ").replace("remarkable ", "")
        return out

    def t_outlook(self, p):
        ids = re.findall(r"^\[([^\]]+)\] ", p.split("Works:", 1)[1], re.M)
        return {"next_steps": [{"problem": "P1", "text": "Is the cheap update enough?", "attempts": ids[-2:] + ["not-a-node"],
                                "settle": "Compare on a second benchmark."}],
                "assumptions": [{"text": "Benchmarks reflect real use.", "threads": ["T1", "T9"], "nodes": ids[:2],
                                 "if_broken": "Gains might not transfer."}]}
