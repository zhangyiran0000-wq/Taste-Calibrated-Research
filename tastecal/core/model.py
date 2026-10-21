"""Core data structures: items, cards, edges and the problem ledger."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

# Edge semantics are always read "LATER work <type> EARLIER work";
# the edge points from the earlier item (source) to the later one (target).
RELATION_TYPES = {
    "resolves": "Later work fixes a specific limitation of the earlier one",
    "extends": "Later work generalises or scales the earlier framework",
    "inspires": "Earlier work supplied the key insight or motivation",
    "challenges": "Later work disputes the earlier work's claim, method or evaluation",
    "competes": "Both attack the same problem by different routes",
    "applies": "Later work carries the method into a new domain or task",
    "explains": "Later work interprets, summarises or gives practice notes; no new method",
}
DROP_TYPES = {"uses", "background", "unrelated"}

RELATION_WEIGHT = {
    "resolves": 1.0, "challenges": 1.0, "extends": 0.85, "inspires": 0.8,
    "competes": 0.75, "applies": 0.5, "explains": 0.35,
}

KINDS = ("paper", "blog", "report", "news")
ROLES = ("seed", "foundation", "driver", "turning-point", "improvement", "branch", "frontier", "explainer")


@dataclass
class Item:
    id: str
    title: str
    kind: str = "paper"
    year: Optional[int] = None
    date: str = ""                      # YYYY-MM or YYYY-MM-DD
    authors: List[str] = field(default_factory=list)
    venue: str = ""
    url: str = ""
    abstract: str = ""                  # abstract, or an excerpt for web items
    citations: Optional[int] = None
    ids: Dict[str, str] = field(default_factory=dict)  # s2, openalex, arxiv, doi

    @property
    def sort_date(self) -> str:
        if self.date:
            return self.date
        return f"{self.year or 0:04d}"

    def author_line(self) -> str:
        if not self.authors:
            return ""
        last = self.authors[0].split()[-1] if self.authors[0].split() else self.authors[0]
        return last + (" et al." if len(self.authors) > 2 else (" & " + self.authors[1].split()[-1] if len(self.authors) == 2 else ""))


@dataclass
class Card:
    """The three-part summary every item is reduced to."""
    short: str
    inherits: str          # the problem it starts from
    move: str              # its method / contribution
    insight: str           # the idea that makes the move work
    leaves: List[str]      # limitations it leaves behind
    summary: str           # plain-language line for a newcomer
    date_guess: str = ""   # for web items without metadata


@dataclass
class Candidate:
    item: Item
    anchor_id: str          # graph node it was found from
    direction: str          # backward | forward | search | web
    contexts: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    influential: bool = False
    problem_id: Optional[str] = None   # for problem-driven search hits
    prior: float = 0.0                 # heuristic score before the LLM looks


@dataclass
class Edge:
    source: str
    target: str
    type: str
    label: str
    evidence: str = ""
    evidence_source: str = ""
    confidence: str = "inferred"       # stated | inferred
    problem: str = ""                  # problem id the link is about


@dataclass
class Node:
    item: Item
    card: Optional[Card]
    hop: int = 0            # <0 ancestors, >0 descendants, 0 seed
    direction: str = "seed"
    round: int = 0
    role: str = ""
    threads: List[str] = field(default_factory=list)
    score: float = 0.0
    # A tool or idea from another field that the map's works use: kept one hop from them, never expanded, and its
    # own limitations do not enter the problem ledger.
    borrowed: bool = False
    must: bool = False      # named by you as must-read: put on the map with the seed and opened like it


@dataclass
class Problem:
    id: str
    text: str
    raised_by: List[str] = field(default_factory=list)
    addressed_by: List[str] = field(default_factory=list)
    searched: bool = False
    thread: str = ""

    @property
    def status(self) -> str:
        return "addressed" if self.addressed_by else "open"


STOP = set("""a an the of to in on for with and or by from as at is are be been being that this these those it its
into than then which who whom whose what when where how why not no can could should would may might must do does did
using use used via over under between across without within more most less least very much many such each other
their there they them we our us one two new still also only both either neither any all some per while whether
problem problems lack lacks lacking limited limitation limitations remains remain open issue issues""".split())


def problem_words(text: str) -> set:
    """Content words of a problem statement, crudely stemmed, for spotting the same problem said twice."""
    out = set()
    for w in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", (text or "").lower()):
        if w in STOP or len(w) < 2 and not ("\u4e00" <= w <= "\u9fff"):
            continue
        for suf in ("ization", "ations", "ation", "ities", "ness", "ing", "ies", "ed", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


JUNK_TITLE = re.compile(r"will be inserted by the editor|manuscript no\b|^(untitled|title|abstract|preprint|front matter|"
                        r"table of contents|contents|editorial|index|erratum|corrigendum)\.?$", re.I)


def junk_title(title: str) -> bool:
    """A title that is broken metadata, not a paper: a journal template line, a fragment like "and s", a bare
    section name. Such records only fill the map with nothing to read."""
    t = " ".join((title or "").split())
    if CJK.search(t):
        return len(t) < 4
    return len(t) < 8 or bool(JUNK_TITLE.search(t))


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def search_queries(qs) -> List[str]:
    """The usable search queries: non-empty strings with no Chinese, Japanese or Korean characters. The paper search
    engines index English titles and abstracts, so a query written in the report's language finds nothing."""
    return [q.strip() for q in (qs or []) if isinstance(q, str) and q.strip() and not CJK.search(q)]


def word_overlap(a: str, b: str) -> float:
    """Jaccard overlap of content words (0..1)."""
    wa, wb = problem_words(a), problem_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class Ledger:
    """Running list of problems. New limitations open entries; later items close them.

    The same problem is often restated in new words by each paper that raises it. `similar` catches close
    restatements by word overlap; `merge` folds a duplicate into the entry it repeats (the old id keeps
    working through `get`)."""

    def __init__(self) -> None:
        self.problems: Dict[str, Problem] = {}
        self.alias: Dict[str, str] = {}      # merged id -> the id it was folded into
        self._n = 0

    def add(self, text: str, raised_by: Optional[str] = None) -> Problem:
        self._n += 1
        p = Problem(id=f"P{self._n}", text=text.strip())
        if raised_by:
            p.raised_by.append(raised_by)
        self.problems[p.id] = p
        return p

    def resolve(self, pid: str) -> str:
        seen = set()
        while pid in self.alias and pid not in seen:
            seen.add(pid)
            pid = self.alias[pid]
        return pid

    def get(self, pid: str) -> Optional[Problem]:
        return self.problems.get(self.resolve(pid)) if pid else None

    def similar(self, text: str, threshold: float) -> Optional[Problem]:
        """The existing problem that says nearly the same thing, if any."""
        best, score = None, threshold
        for p in self.problems.values():
            s = word_overlap(text, p.text)
            if s >= score:
                best, score = p, s
        return best

    def merge(self, keep: str, drop: str) -> bool:
        """Fold problem `drop` into `keep`. Returns False when either is unknown or they are the same."""
        k, d = self.get(keep), self.get(drop)
        if not k or not d or k.id == d.id:
            return False
        for x in d.raised_by:
            if x not in k.raised_by and x not in k.addressed_by:
                k.raised_by.append(x)
        for x in d.addressed_by:
            if x not in k.addressed_by:
                k.addressed_by.append(x)
        k.raised_by = [x for x in k.raised_by if x not in k.addressed_by]
        k.searched = k.searched or d.searched
        del self.problems[d.id]
        self.alias[d.id] = k.id
        return True

    def open(self) -> List[Problem]:
        return [p for p in self.problems.values() if not p.addressed_by]

    def unsearched(self) -> List[Problem]:
        return [p for p in self.problems.values() if not p.searched]

    def as_list(self) -> List[dict]:
        out = []
        for p in self.problems.values():
            d = asdict(p)
            d["status"] = p.status
            d.pop("searched", None)
            out.append(d)
        return out


def slugify(text: str, taken: Optional[set] = None, max_len: int = 28) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].strip("-") or "item"
    if taken is None:
        return s
    base, i = s, 2
    while s in taken:
        s = f"{base}-{i}"
        i += 1
    taken.add(s)
    return s


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def title_similarity(a: str, b: str) -> float:
    ta, tb = set(norm_title(a).split()), set(norm_title(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
