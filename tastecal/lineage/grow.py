"""Growth loop: expand along problems, not along raw citations.

Round 0   read the seed, open its limitations in the ledger.
Round k   1. open the citations of the most promising frontier items
             (backward: what they cite, judged by *how* they cite it;
              forward: who cites them, judged by the citing sentence)
          2. turn unsearched open problems into keyword searches
             (finds work that tackles a problem without citing the raiser, and blogs)
          3. let the LLM keep only items that act on a problem, with a typed edge
          4. card the newcomers, update the ledger (which problems got addressed,
             which new ones appeared)
Stop      when the budget is full, or rounds stop producing new problems (saturation). New problems are
          counted after de-duplication: a restatement of a problem already in the ledger is folded into
          it (word overlap for near-verbatim repeats, then one model call per round that groups
          paraphrases). A round is quiet when it opens few new problems for the works it added
          (cfg.saturation_ratio), so growth stops when new papers mostly repeat known problems.
Search    problems raised by two or more works, or by the seed and its direct neighbours, are searched
          first; after the first rounds, only those.
"""
from __future__ import annotations

import logging
import re
import math
from typing import Dict, List, Optional, Tuple

from tastecal.prompts import lineage as prompts
from tastecal.core.config import Config
from tastecal.core.llm import LLM
from tastecal.core.model import (DROP_TYPES, RELATION_TYPES, RELATION_WEIGHT, Candidate, Card, Edge,
                    Ledger, Node, norm_title, search_queries, title_similarity)
from tastecal.sources import Source, WebSource
from tastecal.sources.openalex import OpenAlex
from tastecal.sources.semantic_scholar import influence

log = logging.getLogger("tastecal.grow")

CLASSIFY_BATCH = 12
SCOPE_BATCH = 12
CARD_BATCH = 6
LEDGER_BATCH = 10


# "Limitations" that describe the text the model was given, not the work: they must not open problems in the ledger.
ABOUT_THE_TEXT = re.compile(
    r"(所给|给定|提供的)?(文本|摘要|材料|信息)[^。]{0,12}(未|没有|并未|不)(说明|提供|给出|描述|提及|介绍)"
    r"|(未|没有)(说明|提供|给出|描述)[^。]{0,10}(方法|结果|实验|数据|细节)"
    r"|\b(the )?(given |provided )?(text|abstract|summary|excerpt|information)\b[^.]{0,40}\b(does not|doesn't|did not|"
    r"fails to|is too (short|thin))\b"
    r"|\b(no|insufficient|not enough|limited) (details?|information|text|abstract)\b[^.]{0,30}\b(given|provided|available)\b"
    r"|\bnot (stated|described|specified|reported) in the (text|abstract)\b", re.I)


def real_leaves(leaves) -> List[str]:
    """Limitations of the work, without the ones that only say the text was too thin to tell."""
    return [x for x in leaves or [] if isinstance(x, str) and x.strip() and not ABOUT_THE_TEXT.search(x)]


def chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


class Grower:
    def __init__(self, cfg: Config, source: Source, llm: LLM,
                 openalex: Optional[OpenAlex] = None, web: Optional[WebSource] = None):
        self.cfg, self.src, self.llm, self.oa, self.web = cfg, source, llm, openalex, web
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[Tuple[str, str], Edge] = {}
        self.edge_strength: Dict[Tuple[str, str], float] = {}
        self.ledger = Ledger()
        self.rounds: List[dict] = []
        self.expanded: set = set()
        self.mentions: Dict[str, List[str]] = {}
        self.seed_id = ""
        self.backlog: Dict[str, tuple] = {}   # good proposals that did not fit a round's cap
        self._closed_by_search = 0
        self._by_title: Dict[str, str] = {}
        # Field limit (cfg.scope): works judged outside it are listed here, not mapped. norm title -> row.
        self.imports: Dict[str, dict] = {}
        self._scope: Dict[str, Tuple[bool, str]] = {}      # norm title -> (in scope, its own field)
        # Without --scope, the seed's own field, inferred once. Works outside it may join the map as borrowed tools
        # (one hop from an in-field work, never expanded, limitations not in the ledger) instead of growing a
        # second map around the tool.
        self.home = ""
        # Every work seen while growing (references, citers, search hits), mapped or not: norm title ->
        # {"citations", "date"}. The audit ranks attention against this neighbourhood instead of the map alone,
        # because the map was built from the important works and would make well-cited ones look unnoticed.
        self.seen: Dict[str, dict] = {}

    BORROWED_SHARE = 0.2            # at most this share of the budget for borrowed tools

    @property
    def field(self) -> str:
        return self.cfg.scope or self.home

    def _saw(self, items) -> None:
        for it in items:
            it = getattr(it, "item", it)
            if getattr(it, "citations", None) is None:
                continue
            self.seen.setdefault(norm_title(it.title), {"citations": it.citations, "date": it.sort_date or ""})

    def attention_reference(self) -> List[dict]:
        return list(self.seen.values())

    # ------------------------------------------------------------------ helpers
    def _known(self, item) -> Optional[str]:
        if item.id in self.nodes:
            return item.id
        key = norm_title(item.title)
        if key in self._by_title:
            return self._by_title[key]
        for k, nid in self._by_title.items():
            if title_similarity(k, item.title) > 0.9:
                return nid
        return None

    def _names(self) -> Dict[str, str]:
        return {nid: (n.card.short if n.card else n.item.title[:40]) for nid, n in self.nodes.items()}

    def _add_node(self, node: Node) -> None:
        self.nodes[node.item.id] = node
        self._by_title[norm_title(node.item.title)] = node.item.id

    def _add_edge(self, e: Edge, strength: float) -> None:
        if e.source == e.target:
            return
        key = (e.source, e.target)
        rkey = (e.target, e.source)
        if rkey in self.edges:  # keep one direction per pair
            if self.edge_strength.get(rkey, 0) >= strength:
                return
            del self.edges[rkey]
        if key not in self.edges or self.edge_strength.get(key, 0) < strength:
            self.edges[key] = e
            self.edge_strength[key] = strength

    def _fill_abstracts(self, nodes: List[Node]) -> None:
        """Works the search returned without an abstract (often paywalled journals) get one from OpenAlex or the
        publisher's page, so their card is not written from the title alone."""
        from tastecal.sources.fulltext import fill_abstract
        http = getattr(self.src, "http", None)
        for n in nodes:
            if n.item.abstract or n.item.kind != "paper":
                continue
            got = fill_abstract(n.item, http, self.oa if (self.oa and self.cfg.use_openalex) else None)
            log.info("abstract for %s: %s", n.item.title[:70], f"from {got}" if got else "none found")

    def _seed_text(self, item, what: str = "seed") -> str:
        """The seed's full text (papers folder, arXiv, open-access PDF), so its card and the problems it opens come
        from the paper rather than its abstract. "" when none was found, with a note saying how to supply it. A
        must-read paper is read the same way (`what` names it in the log)."""
        from tastecal.sources.fulltext import card_excerpt, find_fulltext, suggested_name
        node = {"id": item.id, "title": item.title, "url": item.url}
        try:
            text, basis, where = find_fulltext(node, item, getattr(self.src, "http", None), self.cfg.papers_dir)
        except Exception as e:  # offline, blocked
            log.info("%s full text: %s", what, e)
            text, basis, where = "", "abstract", ""
        if basis == "full text":
            log.info("%s: read from the full text (%s)", what, where)
            return card_excerpt(text)
        log.warning("%s: no full text found, so its card and the problems it opens come from the abstract only. "
                    "Put its PDF in the %s folder as %s and start the run again.", what, self.cfg.papers_dir or "papers",
                    suggested_name(node, item))
        return ""

    def _make_cards(self, nodes: List[Node], texts: Optional[Dict[str, str]] = None) -> None:
        todo = [n for n in nodes if n.card is None]
        self._fill_abstracts(todo)
        for batch in chunks(todo, CARD_BATCH):
            rows = self.llm.json(prompts.SYSTEM, prompts.cards([n.item for n in batch], self.mentions, texts))
            got = {r.get("id"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
            for n in batch:
                r = got.get(n.item.id) or {}
                n.card = Card(
                    short=(r.get("short") or n.item.title.split(":")[0])[:40],
                    inherits=r.get("inherits", ""), move=r.get("move", ""), insight=r.get("insight", ""),
                    leaves=real_leaves(r.get("leaves"))[:3],
                    summary=r.get("summary", ""), date_guess=r.get("date_guess", "") or "")
                if not n.item.date and n.card.date_guess:
                    n.item.date = n.card.date_guess[:7]
                    if n.item.date[:4].isdigit():
                        n.item.year = int(n.item.date[:4])

    LEX_SAME = 0.6           # word overlap above which a "new" problem is taken as a restatement
    CONSOLIDATE_MIN = 6      # open problems needed before a round asks the model to group paraphrases

    def _consolidate(self, fresh: List[str]) -> int:
        """Ask the model which open problems say the same thing; fold each group into its oldest entry.
        Only groups that include a problem opened this round (`fresh`) are considered. Returns how many of the
        fresh problems were folded away."""
        open_ps = [p for p in self.ledger.problems.values() if not p.addressed_by]
        fresh = [f for f in fresh if f in self.ledger.problems]
        if len(open_ps) < self.CONSOLIDATE_MIN or not fresh:
            return 0
        res = self.llm.json(prompts.SYSTEM, prompts.ledger_merge(open_ps, fresh))
        groups = res.get("groups") if isinstance(res, dict) else res
        folded = 0
        num = lambda pid: int(re.sub(r"\D", "", pid) or 0)  # noqa: E731
        for grp in groups if isinstance(groups, list) else []:
            ids = [self.ledger.resolve(x) for x in grp if isinstance(x, str) and self.ledger.get(x)]
            ids = list(dict.fromkeys(ids))
            if len(ids) < 2 or not any(x in fresh for x in ids):
                continue
            ids.sort(key=num)
            keep = ids[0]
            for d in ids[1:]:
                if self.ledger.merge(keep, d):
                    folded += d in fresh
        if folded:
            for e in self.edges.values():
                if getattr(e, "problem", ""):
                    e.problem = self.ledger.resolve(e.problem)
            log.info("ledger: %d new problems were restatements of known ones and were merged", folded)
        return folded

    def _update_ledger(self, new_nodes: List[Node]) -> Tuple[int, int]:
        """Returns (new problems opened, problems newly addressed). New problems are counted after merging
        restatements of known ones."""
        opened = addressed = 0
        fresh: List[str] = []
        for batch in chunks(new_nodes, LEDGER_BATCH):
            res = self.llm.json(prompts.SYSTEM, prompts.ledger_update(
                list(self.ledger.problems.values()), batch, self._names()))
            if not isinstance(res, dict):
                res = {}
            for n in batch:
                r = res.get(n.item.id) or {}
                for pid in r.get("addresses") or []:
                    p = self.ledger.get(pid)
                    if p and n.item.id not in p.addressed_by and n.item.id not in p.raised_by:
                        if not p.addressed_by:
                            addressed += 1
                        p.addressed_by.append(n.item.id)
                leaves = [] if n.borrowed else (r.get("leaves") or [{"new": t} for t in (n.card.leaves if n.card else [])])
                for lv in leaves:
                    if not isinstance(lv, dict):
                        continue
                    if lv.get("same_as") and self.ledger.get(lv["same_as"]):
                        p = self.ledger.get(lv["same_as"])
                        if n.item.id not in p.raised_by and n.item.id not in p.addressed_by:
                            p.raised_by.append(n.item.id)
                    elif lv.get("new") and not real_leaves([lv["new"]]):
                        continue           # says the text was thin, not what the work leaves open
                    elif lv.get("new"):
                        twin = self.ledger.similar(lv["new"], self.LEX_SAME)
                        if twin:
                            if n.item.id not in twin.raised_by and n.item.id not in twin.addressed_by:
                                twin.raised_by.append(n.item.id)
                            continue
                        fresh.append(self.ledger.add(lv["new"], raised_by=n.item.id).id)
                        opened += 1
        opened -= self._consolidate(fresh)
        return opened, addressed

    def _core(self, p) -> bool:
        """A problem worth searching late in growth: raised by two or more works, or by the seed or a direct
        neighbour of it."""
        if len(p.raised_by) >= 2:
            return True
        return any(r in self.nodes and abs(self.nodes[r].hop) <= 1 for r in p.raised_by)

    # ------------------------------------------------------------- field limit
    def _scope_filter(self, items) -> None:
        """Ask once per work whether it belongs to cfg.scope. A work the model does not answer for counts as in."""
        todo, seen = [], set()
        for it in items:
            k = norm_title(it.title)
            if k not in self._scope and k not in seen:
                seen.add(k)
                todo.append(it)
        for batch in chunks(todo, SCOPE_BATCH):
            rows = self.llm.json(prompts.SYSTEM, prompts.scope_check(self.field, batch))
            got = {r.get("id"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
            for it in batch:
                r = got.get(it.id) or {}
                self._scope[norm_title(it.title)] = (r.get("in_scope") is not False, str(r.get("field") or "")[:60])

    def _outside(self, item) -> bool:
        return self._scope.get(norm_title(item.title), (True, ""))[0] is False

    def _borrow(self, anchor: Node, c: Candidate, r: dict) -> None:
        """Note a work from outside the field: which mapped works use it (or build on it, for citers), and how."""
        key = norm_title(c.item.title)
        row = self.imports.setdefault(key, {
            "title": c.item.title, "year": c.item.year, "url": c.item.url, "kind": c.item.kind,
            "field": self._scope.get(key, (False, ""))[1], "direction": "forward" if c.direction == "forward" else "backward",
            "used_by": [], "how": r.get("label", ""), "type": r.get("type", "")})
        if anchor.item.id not in row["used_by"]:
            row["used_by"].append(anchor.item.id)

    def imports_list(self) -> List[dict]:
        """Borrowed works, the most used first."""
        return sorted((dict(v) for v in self.imports.values()), key=lambda v: (-len(v["used_by"]), v.get("year") or 0))

    # ------------------------------------------------------------- candidates
    def _forward_candidates(self, anchor: Node) -> List[Candidate]:
        cands = self.src.forward(anchor.item, anchor.item.id)
        have = {norm_title(c.item.title) for c in cands}
        if self.oa and self.cfg.use_openalex:
            wid = anchor.item.ids.get("openalex") or self.oa.find(anchor.item)
            if wid:
                anchor.item.ids["openalex"] = wid
                extra = [it for it in self.oa.top_citing(wid, n=40) if norm_title(it.title) not in have]
                for it in extra[:20]:
                    # Get the citing sentence from Semantic Scholar when we can.
                    s2_item = getattr(self.src, "match_title", lambda t: None)(it.title)
                    ctx = self.src.citation_context(s2_item, anchor.item) if s2_item else None
                    c = Candidate(item=s2_item or it, anchor_id=anchor.item.id, direction="forward",
                                  contexts=ctx.contexts if ctx else [], intents=ctx.intents if ctx else [],
                                  influential=ctx.influential if ctx else False)
                    c.prior = 4.0 * self.cfg.popularity_weight * influence(c.item) + (1.0 if c.influential else 0.0) + 0.5
                    cands.append(c)
        return cands

    def _classify(self, anchor: Node, cands: List[Candidate], direction: str):
        out = []
        for batch in chunks(cands, CLASSIFY_BATCH):
            rows = self.llm.json(prompts.SYSTEM, prompts.classify_links(anchor, batch, direction))
            got = {r.get("id"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
            for c in batch:
                r = got.get(c.item.id)
                if not r or not r.get("keep") or r.get("type") in DROP_TYPES or r.get("type") not in RELATION_TYPES:
                    continue
                out.append((c, r))
        return out

    def _search_problems(self, rnd: int):
        """Problem-driven search: each open problem becomes 1-2 queries."""
        names = self._names()
        open_ps = [p for p in self.ledger.unsearched() if not p.addressed_by]
        if rnd > 2:                       # later rounds: only problems at the centre of the map
            open_ps = [p for p in open_ps if self._core(p)]
        open_ps.sort(key=lambda p: (not self._core(p), -len(p.raised_by),
                                    -max([self.nodes[r].score for r in p.raised_by if r in self.nodes] or [0])))
        picked = open_ps[: self.cfg.problems_per_round]
        if not picked:
            return []
        for p in picked:
            p.searched = True
        seed = self.nodes[self.seed_id]
        hint = f"{seed.item.title}. Key idea: {seed.card.insight if seed.card else ''}"
        if self.field:
            hint += f" Stay within this field: {self.field}."
        qmap = self.llm.json(prompts.SYSTEM, prompts.problem_queries(picked, hint, names), note=False)
        qmap = qmap if isinstance(qmap, dict) else {}
        results = []
        for p in picked:
            raiser = next((self.nodes[r] for r in p.raised_by if r in self.nodes), None)
            year_from = raiser.item.year if raiser else None
            found, seen = [], set()
            queries = search_queries(qmap.get(p.id)) or search_queries([p.text])
            if not queries:
                log.info("no English search query for problem %s; skipped", p.id)
            for q in queries[:2]:
                hits = self.src.search(q, year_from, limit=12)
                self._saw(hits)
                for it in hits:
                    k = norm_title(it.title)
                    if k in seen or self._known(it):
                        continue
                    seen.add(k)
                    found.append(it)
            if self.cfg.popularity_weight >= 0.5:   # default: most-cited first; otherwise keep relevance order
                found.sort(key=lambda it: -(it.citations or 0))
            found = found[:10]
            if not found or not raiser:
                continue
            rows = self.llm.json(prompts.SYSTEM, prompts.problem_matches(p, raiser, found))
            got = {r.get("id"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
            for it in found:
                r = got.get(it.id)
                if r and r.get("keep") and r.get("type") in RELATION_TYPES:
                    c = Candidate(item=it, anchor_id=raiser.item.id, direction="search", problem_id=p.id)
                    r.setdefault("problem", p.text)
                    results.append((c, r))
        log.info("round %d: problem search kept %d", rnd, len(results))
        return results

    def _search_web(self, rnd: int):
        if not (self.web and self.web.available and self.cfg.use_web):
            return []
        have_blogs = sum(1 for n in self.nodes.values() if n.item.kind != "paper")
        if have_blogs >= self.cfg.max_blogs:
            return []
        seed = self.nodes[self.seed_id]
        short = seed.card.short if seed.card else seed.item.title
        if rnd == 1:
            queries = [f"{short} explained", f"{short} practical lessons blog"]
        else:
            ps = [p for p in self.ledger.problems.values() if p.searched][-2:]
            queries = [f"{short} {p.text[:70]} blog" for p in ps]
        items = []
        for q in queries:
            for it in self.web.search(q, limit=6):
                if not self._known(it) and all(it.url != x.url for x in items):
                    items.append(it)
        if not items:
            return []
        cands = [Candidate(item=it, anchor_id=seed.item.id, direction="web") for it in items[:10]]
        return self._classify(seed, cands, "forward")

    # ------------------------------------------------------------------ main
    def run(self, seed_ref: str) -> "Grower":
        cfg = self.cfg
        seed_item = self.src.resolve(seed_ref)
        seed = Node(item=seed_item, card=None, hop=0, direction="seed", round=0, role="seed", score=10.0)
        self._add_node(seed)
        self.seed_id = seed_item.id
        log.info("seed: %s (%s)", seed_item.title, seed_item.year)
        seed_text = self._seed_text(seed_item)
        self._make_cards([seed], {seed_item.id: seed_text} if seed_text else None)
        if seed.card and seed.card.inherits:
            p = self.ledger.add(seed.card.inherits)
            p.addressed_by.append(seed.item.id)
        for lv in (seed.card.leaves if seed.card else []):
            self.ledger.add(lv, raised_by=seed.item.id)
        if not cfg.scope:
            try:
                got = self.llm.json(prompts.SYSTEM, prompts.home_field(seed_item, seed.card))
                self.home = " ".join(str((got or {}).get("field") or "").split())[:80] if isinstance(got, dict) else ""
            except Exception as e:  # the map still grows, only without the field check
                log.info("could not name the seed's field: %s", e)
            if self.home:
                log.info("seed's field: %s (works from other fields join only as borrowed tools)", self.home)
        must, opened = self._add_must()
        self.rounds.append({"round": 0, "expanded": [], "found": 1 + len(must), "kept": 1 + len(must),
                            "new_problems": (len(seed.card.leaves) if seed.card else 0) + opened, "addressed": 0,
                            **({"must": [n.item.id for n in must]} if must else {}),
                            "note": (f"Read the seed and {len(must)} must-read paper{'s' if len(must) > 1 else ''}; "
                                     "open their limitations") if must else "Read the seed; open its limitations"})

        quiet = 0
        for rnd in range(1, cfg.max_rounds + 1):
            if len(self.nodes) >= cfg.budget:
                break
            frontier = self._pick_frontier(rnd)
            proposals = []
            found = 0
            for anchor in frontier:
                self.expanded.add(anchor.item.id)
                if anchor.hop <= 0 and -anchor.hop < cfg.max_back_hops:
                    back_all = self.src.backward(anchor.item, anchor.item.id)
                    self._saw(back_all)
                    back = [c for c in back_all if not self._known_edge(c, anchor)]
                    for c in back:
                        if c.contexts:
                            self.mentions.setdefault(c.item.id, []).extend(c.contexts[:2])
                    back.sort(key=lambda c: -c.prior)
                    found += len(back)
                    proposals += [(anchor, c, r) for c, r in self._classify(anchor, back[: cfg.refs_to_classify], "backward")]
                if anchor.hop >= 0 and anchor.hop < cfg.max_forward_hops:
                    fwd_all = self._forward_candidates(anchor)
                    self._saw(fwd_all)
                    fwd = [c for c in fwd_all if not self._known_edge(c, anchor)]
                    fwd.sort(key=lambda c: -c.prior)
                    found += len(fwd)
                    proposals += [(anchor, c, r) for c, r in self._classify(anchor, fwd[: cfg.citers_to_classify], "forward")]
            proposals += [(self.nodes[c.anchor_id], c, r) for c, r in self._search_problems(rnd)]
            proposals += [(self.nodes[c.anchor_id], c, r) for c, r in self._search_web(rnd)]
            proposals += list(self.backlog.values())   # candidates that missed an earlier round's cap
            self.backlog = {}

            self._closed_by_search = 0
            added = self._admit(proposals, rnd)
            self._make_cards(added)
            opened, addressed = self._update_ledger(added) if added else (0, 0)
            addressed += self._closed_by_search
            for n in added:
                n.score = self._node_score(n)
            self.rounds.append({"round": rnd, "expanded": [a.item.id for a in frontier],
                                "found": found, "kept": len(added), "new_problems": opened,
                                "addressed": addressed,
                                "note": f"{len(frontier)} items opened; {len(proposals)} links proposed"})
            log.info("round %d: +%d items, +%d problems, %d addressed, total %d",
                     rnd, len(added), opened, addressed, len(self.nodes))
            if not added:
                break
            quiet = quiet + 1 if opened <= cfg.saturation_ratio * len(added) else 0
            if quiet >= cfg.saturation_rounds:
                log.info("saturated: %d rounds in which new works mostly repeated known problems", quiet)
                break
        return self

    def pool(self, n: int) -> List[tuple]:
        """Runners-up: proposals that were judged relevant but did not fit the budget.
        Returns (anchor node, candidate, classifier row), most relevant first, popularity ignored."""
        rows = [(a, c, r) for a, c, r in self.backlog.values() if not self._known(c.item)]
        if self.field:
            self._scope_filter([c.item for _, c, _ in rows])
            rows = [x for x in rows if not self._outside(x[1].item)]
        rows.sort(key=lambda x: -float(x[2].get("strength") or 0.5) * RELATION_WEIGHT.get(x[2].get("type"), 0.3))
        return rows[:n]

    def _known_edge(self, c: Candidate, anchor: Node) -> bool:
        nid = self._known(c.item)
        return bool(nid) and ((nid, anchor.item.id) in self.edges or (anchor.item.id, nid) in self.edges)

    def _add_must(self) -> Tuple[List[Node], int]:
        """The papers you named as must-read: found, read in full like the seed, and put on the map with it (the
        field limit does not apply to them). Their limitations open problems, and the first round opens them with
        the seed. One that cannot be found is logged and listed in the report. Returns them and how many problems
        they opened."""
        added: List[Node] = []
        self.must_missing = []
        for ref in self.cfg.must or ():
            try:
                item = self.src.resolve(ref)
            except Exception as e:  # not found, offline
                log.warning("must-read paper not found: %s (%s)", ref, e)
                self.must_missing.append(ref)
                continue
            known = self._known(item)
            if known:
                if known != self.seed_id:
                    self.nodes[known].must = True
                continue
            node = Node(item=item, card=None, hop=0, direction="must", round=0, score=9.0, must=True)
            self._add_node(node)
            text = self._seed_text(item, f"must-read {item.title[:60]}")
            self._make_cards([node], {item.id: text} if text else None)
            added.append(node)
            log.info("must-read: %s (%s)", item.title, item.year)
        opened = self._update_ledger(added)[0] if added else 0
        return added, opened

    def _pick_frontier(self, rnd: int) -> List[Node]:
        if rnd == 1:      # the seed, and the papers you named as must-read
            return [self.nodes[self.seed_id]] + [n for n in self.nodes.values() if n.must and n.item.id != self.seed_id]
        pool = [n for n in self.nodes.values() if n.item.id not in self.expanded
                and n.item.kind == "paper" and not n.borrowed
                and (-self.cfg.max_back_hops < n.hop < self.cfg.max_forward_hops)]
        pool.sort(key=lambda n: -n.score)
        return pool[: self.cfg.expand_per_round]

    def _node_score(self, n: Node) -> float:
        best = 0.0
        for (s, t), e in self.edges.items():
            if n.item.id in (s, t):
                best = max(best, self.edge_strength[(s, t)] * RELATION_WEIGHT.get(e.type, 0.3))
        raises_open = any(n.item.id in p.raised_by and not p.addressed_by for p in self.ledger.problems.values())
        return best + 1.2 * self.cfg.popularity_weight * influence(n.item) + (0.3 if raises_open else 0.0)

    def _admit(self, proposals, rnd: int) -> List[Node]:
        """Rank proposals, add the best within budget, wire edges (also between known items)."""
        best: Dict[str, tuple] = {}
        for anchor, c, r in proposals:
            strength = float(r.get("strength") or 0.5)
            s = (strength * RELATION_WEIGHT.get(r["type"], 0.3) + self.cfg.popularity_weight * influence(c.item)
                 + 0.15 * min(len(c.contexts), 3))
            known = self._known(c.item)
            if known:
                # A link between two items already in the graph: just add the edge.
                self._add_edge(self._edge(anchor, self.nodes[known], c.direction, r), strength)
                continue
            key = norm_title(c.item.title)
            if key not in best or best[key][0] < s:
                best[key] = (s, anchor, c, r)
        ranked = sorted(best.values(), key=lambda x: -x[0])
        room = self.cfg.budget - len(self.nodes)
        cap = max(3, math.ceil(room * (0.6 if rnd == 1 else 0.5)))
        added: List[Node] = []
        blogs = sum(1 for n in self.nodes.values() if n.item.kind != "paper")
        n_borrowed = sum(1 for n in self.nodes.values() if n.borrowed)
        for i, (s, anchor, c, r) in enumerate(ranked):
            borrowed = False
            if self.field and len(added) < min(room, cap):
                if norm_title(c.item.title) not in self._scope:
                    self._scope_filter([x[2].item for x in ranked[i:i + SCOPE_BATCH]])
                if self._outside(c.item):
                    # With --scope: listed, not mapped. Without it: a borrowed tool may join, one hop from an
                    # in-field work and within its share of the budget; otherwise it is listed too.
                    if (self.cfg.scope or anchor.borrowed
                            or n_borrowed >= max(1, int(self.cfg.budget * self.BORROWED_SHARE))):
                        self._borrow(anchor, c, r)      # no node, no budget, never expanded
                        continue
                    borrowed = True
            if len(added) >= min(room, cap):
                self.backlog[norm_title(c.item.title)] = (anchor, c, r)
                continue
            if c.item.kind != "paper":
                if blogs >= self.cfg.max_blogs:
                    continue
                blogs += 1
            hop = anchor.hop - 1 if c.direction == "backward" else anchor.hop + 1
            node = Node(item=c.item, card=None, hop=hop, direction=c.direction, round=rnd, score=s, borrowed=borrowed)
            n_borrowed += borrowed
            self._add_node(node)
            self._add_edge(self._edge(anchor, node, c.direction, r), float(r.get("strength") or 0.5))
            if c.problem_id and self.ledger.get(c.problem_id):
                p = self.ledger.get(c.problem_id)
                if node.item.id not in p.addressed_by:
                    if not p.addressed_by:
                        self._closed_by_search += 1
                    p.addressed_by.append(node.item.id)
            added.append(node)
        return added

    def _edge(self, anchor: Node, other: Node, direction: str, r: dict) -> Edge:
        if direction == "backward":
            src, dst, where = other, anchor, f"how {anchor.card.short if anchor.card else 'the anchor'} cites it"
        else:
            src, dst = anchor, other
            where = {"forward": f"how {other.item.title[:50]} cites {anchor.card.short if anchor.card else 'it'}",
                     "search": "abstract (found by problem search)",
                     "web": "page text"}.get(direction, "")
        # Keep edges pointing forward in time when the dates say otherwise.
        if (src.item.sort_date or "") > (dst.item.sort_date or "9999") and r.get("type") != "competes":
            src, dst = dst, src
        return Edge(source=src.item.id, target=dst.item.id, type=r["type"], label=r.get("label", ""),
                    evidence=r.get("evidence", ""), evidence_source=where if r.get("evidence") else "",
                    confidence=r.get("confidence", "inferred"), problem=r.get("problem", ""))
