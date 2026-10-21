# Taste-Calibrated Research: reference

The full detail behind the [README](../README.md): every flag, rule and environment variable.

Give it one article. It grows a small, readable lineage around it, showing who solved whose problem, and distils the **driving forces** behind the whole line of work, so someone new to the field can see the mechanism at a glance.

```bash
python3 -m tastecal run "arXiv:<id>"      # live run with the audit and the gates (needs an LLM, see below)
python3 -m tastecal render runs/<seed>/graph.json               # re-render a graph.json
```

No dependencies beyond the Python standard library (3.9+).

## Quick start: use your subscription, no API key

Taste-Calibrated Research runs on the Claude or ChatGPT plan you already have, through the official command-line tool. It needs no API key and no credits.

1. Sign in once, with your own account.
   - **Claude** (Pro, Max, Team, Enterprise): install Claude Code, run `claude`, type `/login` and choose "Claude account with subscription".
   - **ChatGPT** (any plan, Free and Go too): `npm install -g @openai/codex`, run `codex login` and choose "Sign in with ChatGPT".
2. Get a free [Semantic Scholar key](https://www.semanticscholar.org/product/api#api-key-form) and `export S2_API_KEY=...`. Without it, most paper searches are refused and the map comes out thin. Keys pasted with curly quotes (TextEdit adds them), full-width characters or stray spaces are cleaned automatically, and `doctor` checks that the key works.
3. Run it and name your plan, or use the page and pick "Your subscription" there.

```bash
python3 -m tastecal run "arXiv:2212.10156" --plan claude-pro
python3 -m tastecal serve
python3 -m tastecal doctor        # one tiny call: which tool, model and account are used
```

What it does for you:

- **It picks your subscription.** With no `--provider`, it uses Claude Code if it is installed, else Codex. It never picks an API key by itself.
- **It bills your plan only.** API-key and gateway settings in your shell are left out of the tool's calls. If the tool still reports an API key, the run stops at the first call and says how to sign in. `TASTECAL_ALLOW_KEY=1` turns this off.
- **It waits out usage limits.** A usage limit is not an error. The run logs when the limit resets, waits, and goes on, and the page shows "Waiting for your plan's usage limit to reset". `--no-wait` stops instead. Nothing is lost either way, and Resume continues later. The waiting is capped at 8 days in all (`TASTECAL_MAX_WAIT_HOURS`).
- **A stuck call does not stop a run.** One call to Claude Code or Codex that runs past 15 minutes is ended, together with every process it started, and tried again. (On Windows a plain timeout ended only the CLI itself, and reading its output could then wait forever.)

| `--plan` | Plan | Tool | Model | Papers |
|---|---|---|---|---|
| `claude-pro` | Claude Pro | Claude Code | claude-opus-5-5 | 30 |
| `claude-max` | Claude Max | Claude Code | claude-opus-5-5 | 50 |
| `claude-team` | Claude Team, Standard seat | Claude Code | claude-opus-5-5 | 30 |
| `claude-team-premium` | Claude Team, Premium seat | Claude Code | claude-opus-5-5 | 50 |
| `chatgpt-free` | ChatGPT Free or Go | Codex | the plan default | 10 |
| `chatgpt-plus` | ChatGPT Plus or Business | Codex | gpt-6-astra | 25 |
| `chatgpt-pro` | ChatGPT Pro | Codex | gpt-6-astra | 50 |

Without a preset or flags, a run uses Opus 5.5 with Claude and GPT-6 Astra with GPT, at high effort. `--model default` or `--effort default` leaves the choice to the tool. The free ChatGPT preset uses the plan's default model, since Astra may not be on Free. Your own `--provider`, `--model` and `--budget` always win over the preset. Set `TASTECAL_PLAN` once instead of passing `--plan` each time. Usage limits are per person and shared with the chat apps, so a large run on a small plan takes several limit windows.

Each person signs in to the unmodified official tool with their own account. Do not share one subscription between people, and do not run Taste-Calibrated Research as a service on someone's subscription.

**Or use the page.** `python3 -m tastecal serve` opens a local page (only on this computer, at 127.0.0.1) in the style of the reports. Give the seed (a title, link, DOI or id) and, if you like, must-read papers (one per line: they go on the map with the seed and the map grows from them too), pick Claude or GPT and how to sign in (your Claude Code or ChatGPT login is the default, an API key only if you switch to it), the version and how hard it should think (effort: low to max), set the maximum number of papers and the report language, and optionally give your taste: papers you rated (title or link, a score from 0 to 1, a line on why; they need not be related to the seed). The page starts empty; while the list of rated papers is empty it shows three examples of what to write, in the report language (two of them made-up titles), which are never sent. *Load a saved taste* replaces the rated papers on the page with those of a taste saved earlier (newest first, with its date and number of papers) or of a ratings file in the project folder (`ratings*.json`, `.yaml`, `.csv`, `.xlsx` or `.txt`, listed with its number of papers); *Import a file* adds the papers of a ratings file, read as `fit --rated` reads it (`.json`, `.yaml`, `.csv`, `.xlsx`, or `title | score | why` lines); *Save this taste* keeps the rated papers in `taste.json` under a name (a taste you loaded keeps its own entry), and asks before replacing a taste of the same name. Nothing else writes `taste.json`: starting a report does not. The report is made with the rated papers on the page, under the name of the taste you loaded or saved. With 3 or more rated papers, the run then calibrates your taste on the new map (`run --fit`, the same as `fit` on its graph), so the report comes out with both parts; that adds about an hour, and the page shows *Calibrating your taste* meanwhile. If the calibration fails, the report keeps its lineage part and the log gives the `fit` command to run it again. At the bottom the page shows whether the two free keys for paper data are set (Semantic Scholar finds papers and their citers; OpenAlex counts citations), what goes wrong without each, and the command that sets it on your system (`setx` in PowerShell on Windows, `export` elsewhere). It starts the same `run` in the background, keeps every report under `runs/`, and lists them with their status, log and an *Open report* link, plus the examples; *Reuse settings* fills the page with a report's settings again. A key pasted into the page is used for that run only and never written to disk; otherwise `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from the environment are used, or your Claude Code login. The taste on the page becomes the run's taste profile (`runs/<id>/taste.md`). `taste.json` (see `taste.example.json`) is git-ignored because it is personal; `--taste <name>` reads it on the command line. Rated papers can also be pasted as a list (one per line: `title or link | score | why`).

## What you get

`runs/<seed>/report.html` is a single HTML file you can open in any browser. It has two parts, switched in the bar at the top: **Lineage and logic**, below, and, once you have run `fit` on the run, **Taste calibration** (see *Calibrating your taste*). Each part is in tabs drawn as stations on a line, one tab in view at a time; the address keeps the part and the tab (`#logic/map`, `#taste/papers`), so a link opens where it was. A work named anywhere opens its card where you are; the card's *Show on the map* button takes you to it on the map. The first part has these tabs (Next only when the run has it):

| Section | What it answers |
|---|---|
| **Mechanism** | The field's goal, its core tension, the enabling insight, and 1–4 **driving forces** (root causes) |
| **Map** | A transit-style swimlane map. Each coloured line is a *problem thread*, each station is a work placed by date, and the seed is the interchange. Links are typed: resolves, extends, inspired, challenges, competes, applies, explains |
| **Threads** | The threads listed by driving force; pick one to read its **why-ladder** from the top: the symptom researchers saw, then "why?" asked until it reaches a root no paper can change |
| **Story** | A newcomer's narrative that links back into the map, plus knock-on effects (fixing one problem created another) and open problems |
| **What's next** | Who is working on what in the last 12 months; the open questions, each with its closest attempts and the experiment that would settle it; and the assumptions most works share. It does not predict a new paradigm: the shared assumptions are where one would start looking |
| **Method** | The expansion rounds and the full problem ledger |

The careful reading of each paper (the gates, below) is not shown: it is kept in `graph.json`, and the taste calibration measures each paper on it. The run gives no taste score of its own; the only taste score is the calibration's.

All text the reader sees is written in plain language: one idea per sentence, at most three works named per sentence, no praise words. `lint` checks a graph against these rules without an LLM; `run` rewrites the sentences that break them (see *Plain language* below).

Alongside the report you get `graph.json`, the structured data the report is drawn from (schema `deepanalyze.graph/1`), and `run.log`.

## How it works

**1. Grow along problems, not citations** (`lineage/grow.py`)

Following raw citations explodes: a popular method can have thousands of citers, and most of them only *use* it. So every item is first reduced to a card:

```
inherits (the problem it starts from) → move → key insight → leaves (limitations)
```

The `leaves` open entries in a **problem ledger**. Each round then does three things:

- **Backward.** Read the references of the frontier items, but judge each one by *the sentence in which it is cited*. Semantic Scholar provides these "citation contexts". Keep only the references that supplied the problem or the insight.
- **Forward.** Do the same for citers. Semantic Scholar supplies the citation contexts, and OpenAlex supplies the citers *sorted by their own influence*. Keep only the citers that fix, extend, challenge, compete with, apply or explain the item. Mere users are dropped.
- **Search by problem.** Every open problem becomes 1–2 searches over papers, plus the web if a key is set. This finds work that tackles a problem without citing whoever raised it, and it is how blogs get in.

Newcomers get cards and update the ledger: they close problems and open new ones. Papers often restate a known problem in new words, so new entries are de-duplicated before they count: a near-verbatim repeat is folded in by word overlap, and once the ledger has a few open problems, one model call per round groups paraphrases and folds each group into its oldest entry (the old ids keep working). After the first two rounds, only *core* problems are searched: those raised by two or more works, or by the seed or a direct neighbour of it.

Growth stops at the budget (default 30 items), or after two quiet rounds in a row. A round is quiet when it opens at most 0.25 new problems per work it added (`saturation_ratio` in `core/config.py`), so growth stops once new papers mostly repeat known problems.

**2. Synthesize the mechanism** (`lineage/synthesize.py`)

1. Group the ledger's problems into 3–6 **threads**. A thread is a persistent question, not a method family.
2. Build a **why-ladder** per thread, ending at a root of one of these types: hardware, math, data, economics, or the field's goal.
3. Merge threads whose ladders end at the same root into **driving forces**. This step also produces the goal, core tension, enabling insights, external drivers, knock-on effects and roles.
4. Optionally (`--backtest`, off by default and not shown in the report; the result is kept in `graph.json`), **check** the result with a backtest that cannot see the answer (`lineage/backtest.py`). The map is split at the 70th-percentile date. Driving forces are rebuilt from the works before that date only. They predict 4–6 next moves, and so does a baseline that sees the same early works but no forces. Both sets are shuffled, unlabelled and matched against later works: the map's later works plus later papers from a plain field search, which were not found by following the map's problems. Each match must say what in the work realises the prediction, and a prediction too vague to fail (specificity 1 of 3) does not count. The report gives both hit counts; the forces earn credit only for beating the baseline. The model may know later papers from training, and the baseline knows them just as well. Set `TASTECAL_MODEL_CUTOFF=YYYY-MM` to mark a backtest whose cutoff falls inside the model's knowledge as illustrative. A separate call lists works that fit none of the full-map forces (misfits).
5. Write a **story** with `[[id]]` links into the graph.

Every prompt lives in `tastecal/prompts/` and begins with `TASK: <name>`.

**3. Audit attention versus contribution** (`judge/audit.py`)

The report shows only the context this step gathers: counts, the claims and how well the paper's own tables back them, earlier work with a similar idea, what later papers do with it, and later evidence against it. The blind score and the flags below are still written to `graph.json` but are not shown, and the adversarial review is off: a single number on a scale other readers set says little about a judgement that differs from reader to reader.

Some works are important but little noticed; others are widely cited mainly because they were well promoted. The audit keeps the two questions apart:

- **Attention** is citations per year, plus code-repository stars per year when known, each as a percentile. Citations are ranked against every work the growth step saw (references, citers and search hits, usually hundreds), not only the works on the map: the map holds a field's important works, and ranking within it made works with hundreds of citations look unnoticed. It measures popularity only. When a citation count is known to be undercounted, it is marked as a lower bound, and a lower bound never makes a work look unnoticed.
- **Contribution** is scored from a *blind evidence pack*. The pack has no title, authors, venue, awards, labs or counts, and the work's own name is replaced by `[THIS WORK]`. It holds:
  - the work's main claims and how well its own experiments support them, plus fairness notes (extra inputs, unequal baselines, mixed metric protocols);
  - earlier work with the same idea, and whether the work cites it;
  - what later papers *do* with the work (build on it, engage with it, use it only as a baseline, mention it, or ignore it), taken from an even sample of citers rather than the most-cited ones;
  - later evidence against it.

  The scorer rates novelty, significance, evidence and uptake, each judged by the yardstick for the work's type (method, benchmark, analysis and so on).
- **Flags.** High contribution with low attention makes a *possible hidden gem*, but only if the work is also unnoticed in absolute terms: under 100 citations a year, under 500 in all, and outside the top 10% of its field and year by OpenAlex's normalised citation percentile (thresholds in `Thresholds`). A possible gem's review adds an *attention check* that does see the counts and asks whether the work is really under-noticed; the flag stays only if both the blind judge and the attention check agree. Low contribution with high attention makes a work *possibly overhyped*. A very low contribution makes it *safe to skip*. Only these flagged works get an **adversarial review**: an advocate and a critic argue separately from the same blind pack, and a judge who also sees only the pack decides whether the contribution is substantial, modest or negligible. The flag stands only if the judge agrees.
- Works younger than 18 months are marked *too early to tell*.
- Works read only from an abstract or a summary card are marked *too little text to judge*. They get no blind score and none of the flags above: a score from a summary says more about the summary than the paper. Your rated papers follow the same rule: one read from its abstract only gets no blind score either.

The audit covers the map's papers and the best runners-up: works the expansion judged relevant but had no room for. Lower `--popularity-weight` if you also want growth itself to lean less on citation counts.

**4. Gates: reading notes** (`judge/gates.py`)

Every released paper beats its chosen baseline, so "beats the baseline" says almost nothing. The gates ask where the gain comes from, and they ask about the idea before the experiments. Each paper is read once, carefully, from its own full text, and the audit reuses that reading instead of reading the paper again. The text comes from, in order: a file you put in `./papers` (PDF, TXT, MD or HTML, named by node id, arXiv id, DOI with `/` as `_`, or the start of the title), arXiv (HTML, then PDF), a free PDF from elsewhere (the open-access PDF Semantic Scholar knows of, OpenAlex's open-access locations, and the PDF the publisher's own page names, as Nature, Springer, MDPI, ACM and OpenReview pages do), a legal open-access copy found through Unpaywall (set `UNPAYWALL_EMAIL`), and only then the abstract. A link counts only when it returns a real PDF, so paywall pages are skipped. PDFs need `pdftotext` (`brew install poppler`) or the `pypdf` package (`pip install pypdf`, the only option on Windows); `doctor` says which one you have. The paper is checked in order:

| Gate | Question | Answers |
|---|---|---|
| **0. Claim vs delivery** | Do the experiments show what the title and abstract claim, and does the gain come from it? Words in the title count. | delivered / partial / not, plus what it *really* delivered |
| **1. Reason** | Does it say why it should work, in a way that also says when it would not? An ablation is evidence, not a reason. | proof / mechanism / analogy / none |
| **2. Robustness** | Do the gains repeat beyond one setting? Which levers could make the number without the idea: a chosen cost ratio, a component trained on the metric, tuning the baselines did not get, a mismatched setup, a small or saturated benchmark, no ablation of the new idea? | repeats / single / unclear, plus levers |
| **3. Field reaction** | Did later works on the map build on it or challenge it? Uses the audit's citer sample when present; skipped for works under 6 months old. | adopted by / challenged by |

The same reading also runs four checks: do the headline numbers match the paper's own tables (and is a mismatch about the headline result or a minor figure); did the baselines get the same data, inputs and tuning; is there an experiment that removes only the new idea; was code released. A "partial" delivery says which kind it is: *narrower* (shown in a narrower setting) or *unisolated* (the claimed component's own effect is not shown).

A mechanism counts as a reason only when the paper itself says when the method would not help, and the reader must copy that sentence word for word: the code looks for it in the text, and a quote it cannot find counts as not stated.

Each lever carries a status: *present* (the text shows it, with where), *controlled* (the paper rules it out) or *suspected*. Only levers shown in the text count, and a present lever must come with a quotation from the text that the code finds; one whose quotation is not found does not count. A difference that *is* the paper's new idea is not a mismatched setup, and ordinary training on the task's usual loss is not "trained on the metric". The reader used to list every lever that *could* matter, so every paper had five of them and the list could not tell papers apart.

The report does not show these answers: they are what the taste calibration measures each paper on (see *Calibrating your taste*). `graph.json` keeps them, with a label from fixed rules, for older readers of the file and to mark works not read in full; no label is shown and nothing is folded:

| Label | Rule |
|---|---|
| **Claim not delivered** | Gate 0 says "not", with the main text read in full |
| **Reasoned, not yet verified** | A proof or mechanism, not yet robust |
| **Insufficient evidence** | Part of the main text was not read, so an absence cannot be established; or robustness is unclear and no reason is given |
| **Solid** | Delivered, with a reason or robustness, and the gain is not confounded |
| **Gain not attributed** | A serious lever quoted from the text, unequal baselines with no ablation of the new part, or a headline number the tables do not back |
| **Incremental** | Delivered, without a reason and tested in only one setting |
| **Not read in full** | Only an abstract or a summary card could be read |

**Nothing is folded.** Earlier versions hid works whose label was *not delivered* or *incremental*. In a real run that took whole parts of the field off the map on the strength of one reading, so every work now stays on the map. A graph gated before gets the problems those works addressed back on the next `gates` run.

**Works not read in full.** Before a work is read, a missing abstract is filled from OpenAlex, then from the meta tags of the publisher's page (through the DOI, then the work's link), so a paywalled paper at least gets its abstract. Such a work is not scored by the taste calibration, whose part lists it with the file name its PDF needs. `python -m tastecal missing runs/<run>/graph.json` lists these works, each with its link and the file name `./papers` expects (the DOI with `/` as `_`, else the arXiv id, else the start of the title); `run`, `assess` and `gates` print a reminder when there are any. Put the PDFs in `./papers` and run `python -m tastecal assess runs/<run>/graph.json`, then `python -m tastecal gates runs/<run>/graph.json`, then `fit` again. Works already read come from the cache, so only the newly found texts cost model calls.

**Rerunning stages.** New graphs save public model settings and absolute cache/papers paths. `assess` and `gates` reuse them unless a command-line option overrides them; `assess` also reuses the saved attention reference population and the same detailed reading path, including OpenAlex when enabled. Secrets stay in the environment. Old graphs without these settings use the normal defaults. Runs made before 2026-10-21 may carry a taste score per work, a taste check and a list of works to rate next; the report never shows them, and `gates` drops them.

**Reading limits.** Evaluation fit, quote verification and reading coverage reach the blind scoring and the notes the taste calibration measures papers on. Missing ablations are unknown when omitted text could contain them. HTML extraction keeps the full parsed text before selection, so omitted tails are counted. Auto-inferred fields, overflow imports and borrowed-tool markers are exported to the report.

**The seed is read in full before growing.** Its card and the limitations that start the problem ledger come from an excerpt of its full text (the start of the paper and its conclusion or limitations section) when the papers folder, arXiv or an open-access PDF has it. Otherwise the run log warns and names the file to put in `./papers`; the seed's limitations then come from its abstract, and the search follows them. On Windows, PDFs need `pip install pypdf`.

**Taste.** A taste profile is the papers you rated, each with a score and one line on why (a name, then *Papers I liked / disliked / noted* in Markdown, or an entry in `taste.json`); any other text in a Markdown profile is ignored. No profiles ship with the tool: save yours from the page into `taste.json`, or put one in `./profiles/<name>.md` (start from `docs/taste-template.md`) and pass `--taste <name>`, or pass a file path; `python3 -m tastecal profiles` lists them all. For a new run, `./taste.md` is used when it exists. A run keeps the profile with its map, for `fit` (with `--fit`, the run calibrates right after the map); for `gates`, omitting `--taste` keeps the profile saved in the graph. The reading never sees the profile, and the run scores nothing with it: your taste is calibrated from your rated papers in the taste part, not guessed per work.

**5. Plain language** (`report/polish.py`)

Every prompt that writes text for the reader carries the same rules: one idea per sentence (at most about 25 English words or 40 Chinese characters), at most three works named per sentence, no stacked adjectives or praise words, and a short explanation of a technical term the first time it appears. After the run, a lint finds sentences that still break the rules and one LLM pass rewrites only those. A rewrite that drops an `[[id]]` link or a number is thrown away and the original stays. `--language zh-CN` writes the whole report in Chinese. Search queries are always written in English, whatever the report language, because the search engines index English titles and abstracts; any query with Chinese, Japanese or Korean characters is dropped.

```bash
python3 -m tastecal lint runs/<seed>/graph.json                  # which sentences break the rules (no LLM)
python3 -m tastecal polish runs/<seed>/graph.json --outlook      # rewrite them, and add What's next to an older graph
```

### Calibrating your taste (trial)

`python3 -m tastecal fit runs/<run>/graph.json --rated ratings.json` (`taste/axes.py`, `taste/attention.py`) calibrates your taste in two steps and sets it against the field's attention. It writes `taste_fit.json` and `taste_fit.html` (the calibration as a page of its own) next to the graph, writes `report.html` there again with the calibration as its second part, and reuses the run's reading notes; only rated papers the run did not read, and the random sample, are read now. The model only measures papers against your clauses; it never gives a verdict of its own.

**Carried over from fit to fit.** Your taste does not change with the map, so the clauses a fit ends with are saved (`taste_clauses.json` by default, one set per language; personal and kept out of git) and the next fit, on any map, starts from them instead of the general ones and goes on improving them. `--clauses <file>` picks another file, `--fresh` starts from the general clauses. A trial on a few works (`--max`, `--works`) does not overwrite them.

**Step 1, your scores: a hard constraint.** Your scores are never judged: the clauses must reproduce them. Within them, step 2 fits the scoring so that every other paper comes as close to y = x as it can.

- **Items as step functions.** Each item (four general ones: novelty, soundness, validity, practicality, rewritten in your terms where your reasons say more, plus those your reasons add) has six levels, 0, 0.2, …, 1.0, and each level is a concrete clause about the paper: what it does, shows or reports ("0 = only open-loop averages; 0.2 = closed loop, but the other agents replay logs; …"). A clause may never say what the reader likes, may never name a paper, and may never speak of how the field received the paper (citations, later work taking it up, fame, venue, authors): the field's attention is the other axis, and a clause about it would copy that axis into the score. Each paper gets the highest level whose clause it meets, with the passage that meets it and what it lacks for the next level up; there is no default level. Your rated papers are measured one indicator at a time, all of them in the same call, so the model sets them against each other (levels given one paper at a time crowd in the middle), and twice, the second time in the other order: each level is the average of the two reads, which about halves the model's wobble from one read to the next (a level may fall between two steps, such as 3.5). The noise reported is that of a single read, measured from the gap between the two, since the other papers are read once; the other papers are measured with five of your rated papers, spread over your scores, shown with their levels as the standard (your scores are never shown). Measuring never sees your scores or reasons, and the reading notes it works from carry nothing about how the paper was received. A rated paper the run has only a short audit excerpt of is read in full first. The rated papers may come from several fields, so every level must apply to a paper of any field (a field-specific example may follow in parentheses). A clause or note that breaks one of these rules is sent back once to be rewritten before it is refused.
- **The combined score and the line, in this step.** Every item counts the same: s is the average of a paper's levels, and your score = a·s + b, where a ≥ 0 and b only put s on your own scale (fitted to your rated papers by least squares). There are no weights to fit in this step, so all the optimizing goes into the wording of the step clauses: whatever you value has to be in them. Step 2 then fits weights, starting from these. The slope a is at most 2: when your rated papers' average levels bunch together, a steeper line would turn small differences in level into large ones and push other papers to 0 or 1, so the clauses have to spread the papers instead (and while they do not, the trust number shows it).
- **The loop** optimizes the clauses and the items until they reproduce your scores: it runs while a rated paper is off by more than 0.1 or a pair you scored 0.3 or more apart is in the wrong order. The worst miss is set against the rated paper predicted closest to it but scored far apart, and the model proposes one general change: rewrite an item's clauses, add an item, take out an item your reasons never judge by (never below three), or add a reading note to an item it reads wrongly. A reading note (at most about 80 words, ending at a whole sentence) is part of the item from then on, applied to every paper. The change is kept only if your scores are reproduced more closely (on average, or with fewer papers off, or a clearly smaller worst miss, never worse on average) and no pair you scored 0.3 or more apart ends up in the wrong order. A paper that resists two changes in a row gives way to the next one off, so one paper the clauses cannot reach does not end the loop. There are never more items than max(4, rated papers − 2). The loop ends when every paper is reproduced, when every paper still off has resisted two changes, or after fifteen rounds. The leave-one-out error (each rated paper scored by clauses fitted without it) is reported as a check of how robust the clauses are, not optimized.

**Step 2, every paper towards y = x.**

- **The papers compared:** every method paper on the map of the last ten years (`--years 10`; your rated papers are kept whatever their year) read in full, and a sample drawn at random (`--random-share 0.15`: 15% as many as the map's papers, at least three) from recent work citing a few map papers, read in full the same way. References are not drawn from: they bring in general tools from other fields. Before anything is read, one short call on titles and abstracts keeps only the drawn papers on the map's own problem (the seed's), not those on a neighbouring task that only cite the map's papers for a component; twice as many are drawn to allow for it. The map grows along citations, so it leans to cited work and the little-attended side is thin by construction; the random papers are not chosen by citations. Drawn papers without full text are not scored. Tools, datasets, surveys and benchmarks are never scored, nor are concept works: definitions, a taxonomy, terminology or a process described in words, with no method that runs and nothing tested (one model call sorts them out, for your rated papers too). Every clause about evidence would put a concept work at the bottom, and its citations come from the field using its words, so it would always land in *much attention, not to your taste* and say nothing.
- **Attention**, looked up for each paper, your rated papers included (OpenAlex, Semantic Scholar, the audit): *cumulative*, citations a year since publication; *recent*, citations a month over the last two calendar years; *influential*, Semantic Scholar's influential citations a year; *stars*, GitHub stars a year when the audit found a repository. A paper a few months old with a handful of citations says little yet: its reliability (age up to 18 months, citations up to 5) widens its attention bar and lowers its weight in the fit. New papers are never left out.
- **One scale.** Citations spread over orders of magnitude, so each count is put on 0 to 1 through a normal distribution on its log, in two halves that meet at the median of the papers compared in this run (map and random sample), which is 0.5. Below the median the spread is these papers' own (σ from their lower quartile), so the little-cited new papers are spread out instead of pressed against 0; above it Attention Is All You Need, looked up in every run, is +3σ (when it cannot be looked up, the most attended paper known, your rated papers included, takes its place), so the scale still ends at the landmark and no paper of the field looks as attended as it. (If most papers are not cited yet, the middle is the least-cited paper that is; a landmark record at or below the middle is ignored.) The chart names the median and the landmark. Every count follows one rule: the larger of OpenAlex's and Semantic Scholar's counts looked up now (both miss citations, and a wrongly matched record shows few), else the count the map recorded for the paper. A paper's attention bar spans its count ± u·(count + 1), u its unreliability, so a paper with no citation yet has a bar too. Papers without a citation count have no attention: they are scored, but neither fitted to nor drawn against it. When fewer than eight papers (and fewer than 80% of them) have a count, the run's own percentile is used for every paper instead, put on your scale by rank (the two are never mixed). Your rated papers' attention only anchors the scale: they are drawn on y = x at your own score.
- **Every paper towards y = x, within your scores.** The objective is the distance of the papers you have not rated from y = x, straight up or down on the chart, root mean square, each paper weighted by how reliable its attention is; it is taken on the scores as drawn (clipped to 0..1), so a paper past either end costs no more for going further out. The constraint is your scores: each rated paper stays within 0.1 of your score (or within step 1's miss, where that was larger), and every pair you scored 0.3 or more apart stays in your order (a pair step 1 already had the wrong way round may not get worse). Two levers. *The weights:* the score becomes a weighted sum of the levels, b + Σ w_k·x_k with every w_k ≥ 0 (their sum at most 2, as for the line), fitted directly to the objective under the constraint (a small quadratic program; when no start at hand meets your scores, one is searched for, and only if none exists does the fit fall back to every item counting the same, saying so), starting from, and pulled lightly towards, every item counting the same, so a weight the papers do not decide stays where step 1 left it. *The clauses:* the field may rewrite a clause, add a reading note, or add up to two items of its own (it may not take one out: an item the papers do not need simply gets no weight). A change is measured as in step 1: on your papers twice, side by side, in both orders; on the other papers in batches with a few of yours as the standard. The papers are split in two fixed halves, each scored by weights fitted without it. Changes are proposed from one half (the paper furthest from y = x under that half's own fit, against the one scored alike but attended very differently) and kept only if the other half comes closer to y = x and the proposing half no further. As in the first loop, a paper the model finds nothing to change for, or that resists two changes in a row, gives way to the next one. Clauses the field brought in are marked *from the field*; six rounds at most. What stays far from y = x afterwards is what your scores do not let the scoring close: a real difference between your taste and the field's attention.

**Trust in the result.** The overview shows it first, as a number: how far the clauses miss your own scores (root mean square over your rated papers, with the worst miss). The larger its absolute value, the less the result can be trusted. No label or threshold is put on it, since none would hold as the rated papers grow. The same number is added to every paper's score bar: the clauses cannot score another paper more precisely than they reproduce yours, so the poorer the fit, the further a paper must be from y = x to count as off the line.

**What the page shows.** The report's second part, and `taste_fit.html` on its own, in tabs (the tab is kept in the address); `render`, `gates` and the other commands that write `report.html` keep the part as long as `taste_fit.json` is next to it; click a paper anywhere, a point or a row, to open its details: its score and uncertainty, every measure of attention, and each level with the passage that meets it and why it is not higher.

- **Overview:** the numbers to read first (trust in the result, the papers compared, how many are off the line on each side), then your score against the field's cumulative attention (what the fit aims at): across, the field's attention (citations a year on the normal scale above, the median paper in the middle); up, the taste score your clauses give; y = x, shaded beyond it. A paper counts as off the line when it is further than max(0.15, twice the noise) plus its two bars (the bars appear on hover, or with the switch); a paper under a year old is never counted, its citations say too little yet. Each paper's card shows where it appeared and who wrote it, as the map recorded them. Top left: *to your taste, little attention* (overlooked good work, or too new to be noticed); bottom right: *much attention, not to your taste* (not to your standard, or carried by fame; citations include use as a baseline and criticism, so it is a list to check, not a verdict); along the line, *to your taste, much attention* (taste score and attention both above 0.6) and *not to your taste, little attention* (both below 0.4). Your rated papers sit on y = x at your own score (their attention is not used), with a tick to what the clauses give them. Papers are drawn as on the map: colour by thread, turning points bigger with a core, random ones grey, filled when off the line, dashed when under a year old. A switch above each chart names the papers off the line and yours, all of them, or none (hover or click a point to see its name); a chart of more than 20 papers starts with every name hidden, and the choice holds for every chart and is remembered in the browser. The tabs and this switch work without the page's script. The four regions are chips that pick out their papers on the chart, with one line per paper.
- **Papers:** every paper in one table (score, attention, gap, region, levels as small bars), sortable, with filters (rated by you, off the line, drawn at random) and a search.
- **Attention measures:** the same chart for each measure (*recent*, *influential*, *stars*), one at a time, and which measures put each paper off the line.
- **Clauses:** each with its source, its six levels, its reading notes and its share of the score (fitted in step 2, with the range of that share when one of your rated papers is left out; all equal when there was nothing to fit to).
- **How it was fitted:** how closely the clauses reproduce your scores, the distance from y = x and your papers' mean miss before and after the weights are fitted, the step towards y = x (the distance with every item counting the same and with the weights fitted), every change the two loops tried, the papers worth rating next, rated papers not used, map papers not scored because only an abstract or a summary could be read (each with the file name its PDF needs), papers older than the window, and papers not scored (tools, datasets, surveys, benchmarks and concept works).

Ratings: a `.json` file, a list of `{"paper": ..., "score": 0.7, "reason": ...}` (or `.yaml` with the same fields, if PyYAML is installed), a spreadsheet (`.xlsx`, first sheet) or `.csv` with three columns, paper, score, reason (a header row is skipped), or a text file with one per line, `title or short name | score | reason`. Name the file `ratings*.json` (or `.yaml`, `.txt`) so `.gitignore` keeps it out of the repository. A paper can be a title, a short name from the map, an arXiv id or a DOI. Flags: `--taste <profile>` (rated papers from a profile instead; default: the one saved with the run), `--max 10` (score only ten map papers, a trial, no random sample), `--works id1,id2`, `--random-share 0.15` (papers drawn at random, as a share of the map's papers; 0 for none), `--years 10` (compare papers of the last N years; 0 for any), `--no-attention` (no citation lookups: the run's own percentile only), `--redraw` (draw `taste_fit.html` and `report.html` again from `taste_fit.json`, no model calls), `--refit` (recompute step 2 from `taste_fit.json`: the attention scale, the weights, every score and the page, in seconds, with no model call and no lookup; the clauses and every paper's levels are kept, and the field's clause changes are not tried again).

Each rated paper needs a full-text reading. A method paper on the map, or one the audit read, already has one. Any other rated paper is found on Semantic Scholar and read in full now, the way the run reads its own papers: from the papers folder first, then arXiv or an open-access copy. A rated paper with no full text is not used; the command prints the file name to give its PDF in the papers folder, and `taste_fit.html` lists it. Run the command again once the PDF is there. A rated tool, dataset, survey or benchmark is listed, not read. At least three rated papers are needed; six or more make the line meaningful, and eight or more leave room for items from your own reasons. The papers do not have to come from the run's own field.

## Running it live

```bash
# Default: your subscription (Claude Code if installed, else Codex). See Quick start above.
python3 -m tastecal run "arXiv:<id>" --plan claude-max
python3 -m tastecal run "arXiv:<id>" --provider claude-cli            # add --model sonnet / opus to pick a model
python3 -m tastecal run "arXiv:<id>" --provider claude-cli --no-assess --no-gates   # map only, no audit or gates
python3 -m tastecal assess runs/<seed>/graph.json --provider claude-cli    # or audit an existing map later
python3 -m tastecal gates runs/<seed>/graph.json --provider claude-cli --taste taste.md   # or gate it later

# No API key, but a ChatGPT plan? Use Codex CLI with your ChatGPT login (npm install -g @openai/codex, then codex login):
python3 -m tastecal run "arXiv:<id>" --provider codex-cli --model gpt-6-astra

# Gate answers prepared elsewhere (for example in a chat), no LLM needed:
python3 -m tastecal gates runs/<seed>/graph.json --raw answers.json

# Only if you want to pay per token instead: Claude API …
export ANTHROPIC_API_KEY=sk-ant-...
python3 -m tastecal run "arXiv:<id>" --provider anthropic

# … or any OpenAI-compatible endpoint (OpenAI, DeepSeek, Qwen, a local vLLM …)
export OPENAI_API_KEY=...
python3 -m tastecal run "https://arxiv.org/abs/1706.03762" --provider openai \
    --base-url https://api.deepseek.com/v1 --model deepseek-chat
```

The seed can be an arXiv id or URL, a DOI, a Semantic Scholar id, or a title in quotes.

| Environment variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`) | Only for `--provider anthropic` / `openai`. The default runs `claude -p` under your Claude Code login (set `CLAUDE_BIN` if `claude` is not on your PATH) or `codex exec` under your ChatGPT login (set `CODEX_BIN` if needed), and leaves these out of those calls |
| `TASTECAL_PROVIDER` / `TASTECAL_PLAN` | Optional. Defaults for `--provider` (else `auto`) and `--plan` |
| `TASTECAL_ALLOW_KEY` | Optional. `1` lets Claude Code or Codex bill an API key or gateway instead of your plan |
| `TASTECAL_MAX_WAIT_HOURS` | Optional. How long a run may wait for usage limits to reset, in all (default 192) |
| `TASTECAL_MODEL` | Default model id. Otherwise `claude-opus-5-5` for Claude, `gpt-6-astra` for GPT; override with `--model` if your account uses different ids |
| `S2_API_KEY` | Strongly advised, and free. Without a Semantic Scholar key most searches are refused (HTTP 429) and requests are spaced about 1 s apart |
| `OPENALEX_MAILTO` | Optional. Puts you in OpenAlex's polite pool |
| `OPENALEX_API_KEY` | Advised for `fit`, and free ([openalex.org/settings/api](https://openalex.org/settings/api)). Without a key OpenAlex allows only a small daily amount, shared by everyone on your network; once it answers HTTP 429 it is not asked again in that run (cached answers are still used) and citation counts come from Semantic Scholar and the map. The key is sent with each request but never written to the cache, a log or an error |
| `TAVILY_API_KEY` or `BRAVE_API_KEY` | Optional. Enables blog and report discovery; without one the run is papers-only |
| `GITHUB_TOKEN` | Optional. Raises GitHub's rate limit when the audit looks up repository stars |
| `UNPAYWALL_EMAIL` | Optional. Lets the reader find legal open-access copies of papers that are not on arXiv (falls back to `OPENALEX_MAILTO`) |
| `TASTECAL_LANGUAGE` | Optional. Default for `--language` |
| `TASTECAL_CACHE_DAYS` | Optional. Search results and citer lists older than this many days are fetched again (default 14; paper records 60; page text never) |
| `TASTECAL_MODEL_CUTOFF` | Optional, `YYYY-MM`. Marks a backtest whose cutoff falls before this date as illustrative |

Useful flags: `--effort low|medium|high|xhigh|max|default` (default: high; `default` = the model's own), `--fit` (then calibrate your taste on the new map, as `fit` does, when the taste profile has at least 3 rated papers; the page always asks for it), `--must "<paper>"` (repeat for more: a paper you want on the map, a title, link, DOI or id; it is read in full like the seed, its limitations open problems, the first round opens it with the seed, it stays on the map whatever `--scope` says and it counts towards `--budget`; one that cannot be found is logged and listed under Method), `--scope "<field>"` (limit the map to a field: works from other fields, such as a generic diffusion model, are kept in `graph.json` under `imports` instead of being mapped, read or audited, and do not use the budget; the report does not list them; no limit by default), `--budget 30`, `--rounds 5`, `--expand-per-round 4`, `--max-back 2`, `--max-forward 2`, `--max-blogs 5`, `--no-openalex`, `--no-web`, `--out runs/my-run`, `-v`. Writing: `--language zh-CN`, `--no-polish`, `--no-outlook`. Reading: `--papers-dir papers`, `--taste practitioner`.
The audit and the gates run by default; `--no-assess` and `--no-gates` turn them off, and `run` uses `./taste.md` as the taste profile when it exists. Audit flags: `--assess-max 0` (default: every paper on the map plus the runners-up; a number keeps the seed and the most connected works, never just the oldest), `--no-review` (no longer needed: the advocate, critic and judge are off), `--popularity-weight 0.5` (default; 0.1 makes growth lean far less on citation counts).

**Rate as you read.** Open a report from the page (`serve`), click a work, and give it 1 to 5 under *Your rating*. The rating goes into your taste profile in `taste.json` (the one the report was made with, else your default), and every later run calibrates on it. A report opened as a plain file shows no rating buttons.

**Side branches.** The map folds side branches into a "+N side branches" badge on each line: works tied to the seed only through applies, competes or explains links, or that the synthesis calls a branch or an explainer. The chain through the seed always shows. "Side branches: Show" above the map, or `render --folded show`, opens them all.

An audit of 40 works adds roughly 6–8 LLM calls per work (claims check, citation roles, precedent search, blind score).
Gate flags: `--gates-max 0` (default: every paper on the map), `--taste taste.md` (the profile kept with the map for `fit`). The `gates` command also takes `--raw answers.json`, `--today YYYY-MM` and `--folded hide|show`. Gating adds one LLM call per paper (each reads up to about 30k characters of full text).

`--raw` takes a JSON object keyed by node id. Each value is one gate answer (`claimed`, `delivery`, `partial_kind`, `delivered`, `delivery_evidence`, `reason_type`, `reason`, `fails_when`, `fails_when_stated`, `robustness`, `robustness_note`, `levers` as `[{"lever", "status", "where", "note"}]`, `check_next`, `checks`), plus `basis` (`"full text"`, `"abstract"` or `"card"`), and optionally `verified` as `{"fails_when": true|false}` (whether the quote was found in the text); a `taste` field is ignored. Levers without a status count as suspected, so older answer files keep working.

**Cost and caching.** A 30-item run makes roughly 25–40 LLM calls, most of them small batched classification prompts, plus one ledger merge per round (and four backtest calls with `--backtest`). Every LLM reply is cached in `.tastecal_cache/`, so a re-run with the same settings costs nothing, and changing the synthesis prompts only re-runs synthesis. HTTP responses are cached with the time they were fetched: search results and citer lists are fetched again after 14 days (`TASTECAL_CACHE_DAYS`), paper records after 60, page text never. `--refresh` fetches every search and citer list again. When a fresh fetch fails, the old copy is used. The run log ends with an estimate of the token usage.

**Gaps and resume.** Requests that fail for a passing reason (HTTP 429, 5xx, network) are written to `runs/<run>/gaps.json`. `resume` replays the earlier attempt from the cache (whatever the cached copies' age) until it reaches a request the cache does not hold: where the earlier attempt stopped, or one of its gaps. From there the run continues live, so a resume neither stops at the papers already found nor leaves the gaps empty. For runs made before gaps files existed, `resume` reads the failed requests from `run.log`. When `claude -p` fails without a message, the error now names its subtype, the call is retried when the subtype means the run broke off, and the raw result is saved in `.tastecal_cache/llm/failures/`.

To re-render after editing `graph.json` by hand:

```bash
python3 -m tastecal render runs/<seed>/graph.json
```

## Layout

See the [README](../README.md#layout). Run the tests with `python3 -m unittest discover -s tests`.

## Larger maps

To get a larger map from a live run, raise the budget, for example `--budget 45 --rounds 6`. Larger maps quiet their links until you hover or select something. Clicking a thread's name on the map shows that thread's line alone.

## Example

Example runs are not included in this repository. Run one yourself (see *Running it live* above); each run writes `report.html`, `graph.json` and `run.log` to `runs/<run>/`. A finished run's gate answers can be re-applied without an LLM with `python3 -m tastecal gates runs/<run>/graph.json --raw answers.json`.

## Chinese reports

Set `"language": "zh-CN"` in `graph.json`'s `meta` and `render` produces a Chinese page. The template itself is unchanged: `tastecal/report/i18n_zh.py` holds the replacement pairs, and `localize()` raises if any pair no longer matches the template. Card text, labels and the story come from the graph, so write them in Chinese too. Without the language field the English output is byte-for-byte unchanged.

## Next steps

- Run the pipeline live on a seed you know well and compare the map and the reading notes with your own reading. This is the first real test of the prompts.
- Accept several seeds and merge their graphs into one field map.
- Add news and other source types. These would mostly feed the *external drivers* (why now) rather than the threads.
- Add a fixed evaluation set of seeds from fields you know, scored against the success criteria in `intention.md`.
