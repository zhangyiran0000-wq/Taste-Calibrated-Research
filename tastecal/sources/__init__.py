"""Where items come from. A `Source` answers four questions about the literature:
what is this seed, what does it cite, who cites it, and what else matches a query."""
from __future__ import annotations

import logging
from typing import List, Optional

from tastecal.core.model import Candidate, Item

log = logging.getLogger("tastecal.sources")

# Words that signal the citing sentence is *about* the cited work's problem,
# rather than just using it. Used to pre-rank candidates cheaply before the LLM.
ACT_CUES = (
    "however", "but ", "limit", "suffer", "drawback", "bottleneck", "unlike", "instead",
    "fail", "address", "overcome", "improv", "extend", "generaliz", "generalis", "inspired",
    "build on", "builds on", "built on", "motivat", "alleviat", "mitigat", "inefficien",
    "costly", "expensive", "latency", "memory", "challeng", "in contrast", "contrary",
    "outperform", "variant", "propose", "we show", "suboptimal", "restrict", "gap",
)
USE_CUES = ("we use", "we adopt", "we apply", "we employ", "implemented with", "using the",
            "fine-tuned with", "trained with", "following ", "we follow")


def cue_score(contexts: List[str]) -> float:
    if not contexts:
        return 0.0
    text = " ".join(contexts).lower()
    act = sum(1 for c in ACT_CUES if c in text)
    use = sum(1 for c in USE_CUES if c in text)
    return min(3.0, act * 0.5) - min(1.0, use * 0.25)


class Source:
    """Interface. Implementations may return [] for anything they cannot do."""

    def resolve(self, ref: str) -> Item:
        raise NotImplementedError

    def backward(self, item: Item, anchor_id: str) -> List[Candidate]:
        return []

    def forward(self, item: Item, anchor_id: str) -> List[Candidate]:
        return []

    def search(self, query: str, year_from: Optional[int], limit: int = 15,
               year_to: Optional[int] = None) -> List[Item]:
        return []

    def citing_sample(self, item: Item, n: int = 150) -> List[Candidate]:
        """An even sample of citers (not the most-cited ones), for the uptake audit."""
        cands = self.forward(item, item.id)
        if len(cands) <= n:
            return cands
        step = len(cands) / n
        return [cands[int(k * step)] for k in range(n)]

    def citation_context(self, citing: Item, cited: Item) -> Optional[Candidate]:
        return None


class WebSource:
    """Interface for blog / report / news discovery."""

    available = False

    def search(self, query: str, limit: int = 6) -> List[Item]:
        return []
