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

**Or use the page.** `python3 -m tastecal serve` opens a local page (only on this computer, at 127.0.0.1) in the style of the reports. Give the seed (a title, link, DOI or id), pick Claude or GPT and how to sign in (your Claude Code or ChatGPT login is the default, an API key only if you switch to it), the version and how hard it should think (effort: low to max), set the maximum number of papers and the report language, and optionally describe your taste and list papers you rated (title or link, a score from 0 to 1, a line on why; they need not be related to the seed). It starts the same `run` in the background, keeps every report under `runs/`, and lists them with their status, log and an *Open report* link, plus the examples. A key pasted into the page is used for that run only and never written to disk; otherwise `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from the environment are used, or your Claude Code login. Your taste and rated papers become the run's taste profile (`runs/<id>/taste.md`); give it a name and it is also saved to `profiles/<name>.md` for later runs. Your taste and sample papers live in one file, `taste.json` (see `taste.example.json`; it is git-ignored because it is personal). The page saves to it, fills itself in from its default profile, and `--taste <name>` reads it on the command line. Sample papers can be pasted as a list (one per line: `title or link | score | why`), saved as a template with *Save as template*, and loaded again with *Load template* or *Start from*; the presets come with example papers.

## What you get

`runs/<seed>/report.html` is a single HTML file you can open in any browser. It has these sections:

| Section | What it answers |
|---|---|
| **Mechanism** | The field's goal, its core tension, the enabling insight, and 1–4 **driving forces** (root causes) |
| **Map** | A transit-style swimlane map. Each coloured line is a *problem thread*, each station is a work placed by date, and the seed is the interchange. Links are typed: resolves, extends, inspired, challenges, competes, applies, explains |
| **Threads** | One **why-ladder** per thread: the symptom researchers saw, then "why?" asked until it reaches a root no paper can change |
| **Story** | A newcomer's narrative that links back into the map, plus knock-on effects (fixing one problem created another) and open problems |
| **Check** | How many works the forces explain, and whether predictions made from the forces alone match what came later |
| **What's next** | Who is working on what in the last 12 months; the open questions, each with its closest attempts and the experiment that would settle it; and the assumptions most works share. It does not predict a new paradigm: the shared assumptions are where one would start looking |
| **Holds up?** | One section for quality. The gates: which works deliver what they claim, give a reason, and hold up; which are drawn dashed on the map; which are treasure candidates worth reading. The audit: notice versus a blind score of contribution (possible hidden gems, possibly overhyped, safe to skip). Where the two disagree about a work, the section says so. Works read only from an abstract carry a "not verified" badge |
| **Method** | The expansion rounds and the full problem ledger |

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
4. **Check** the result with a backtest that cannot see the answer (`lineage/backtest.py`). The map is split at the 70th-percentile date. Driving forces are rebuilt from the works before that date only. They predict 4–6 next moves, and so does a baseline that sees the same early works but no forces. Both sets are shuffled, unlabelled and matched against later works: the map's later works plus later papers from a plain field search, which were not found by following the map's problems. Each match must say what in the work realises the prediction, and a prediction too vague to fail (specificity 1 of 3) does not count. The report gives both hit counts; the forces earn credit only for beating the baseline. The model may know later papers from training, and the baseline knows them just as well. Set `TASTECAL_MODEL_CUTOFF=YYYY-MM` to mark a backtest whose cutoff falls inside the model's knowledge as illustrative. A separate call lists works that fit none of the full-map forces (misfits).
5. Write a **story** with `[[id]]` links into the graph.

Every prompt lives in `tastecal/prompts/` and begins with `TASK: <name>`.

**3. Audit attention versus contribution** (`judge/audit.py`)

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

The audit covers the map's papers and the best runners-up: works the expansion judged relevant but had no room for. Lower `--popularity-weight` if you also want growth itself to lean less on citation counts.

**4. Gates: what earns a station, and what is worth reading** (`judge/gates.py`)

Every released paper beats its chosen baseline, so "beats the baseline" says almost nothing. The gates ask where the gain comes from, and they ask about the idea before the experiments. Each paper is read once, carefully, from its own full text, and the audit reuses that reading instead of reading the paper again. The text comes from, in order: a file you put in `./papers` (PDF, TXT, MD or HTML, named by node id, arXiv id, DOI with `/` as `_`, or the start of the title), arXiv (HTML, then PDF), a free PDF from elsewhere (the open-access PDF Semantic Scholar knows of, OpenAlex's open-access locations, and the PDF the publisher's own page names, as Nature, Springer, MDPI, ACM and OpenReview pages do), a legal open-access copy found through Unpaywall (set `UNPAYWALL_EMAIL`), and only then the abstract. A link counts only when it returns a real PDF, so paywall pages are skipped. PDFs need `pdftotext` (`brew install poppler`) or the `pypdf` package; `doctor` says which one you have. The paper is checked in order:

| Gate | Question | Answers |
|---|---|---|
| **0. Claim vs delivery** | Do the experiments show what the title and abstract claim, and does the gain come from it? Words in the title count. | delivered / partial / not, plus what it *really* delivered |
| **1. Reason** | Does it say why it should work, in a way that also says when it would not? An ablation is evidence, not a reason. | proof / mechanism / analogy / none |
| **2. Robustness** | Do the gains repeat beyond one setting? Which levers could make the number without the idea: a chosen cost ratio, a component trained on the metric, tuning the baselines did not get, a mismatched setup, a small or saturated benchmark, no ablation of the new idea? | repeats / single / unclear, plus levers |
| **3. Field reaction** | Did later works on the map build on it or challenge it? Uses the audit's citer sample when present; skipped for works under 6 months old. | adopted by / challenged by |

The same reading also runs four checks, shown in each work's drawer: do the headline numbers match the paper's own tables (and is a mismatch about the headline result or a minor figure); did the baselines get the same data, inputs and tuning; is there an experiment that removes only the new idea; was code released. A "partial" delivery says which kind it is: *narrower* (shown in a narrower setting) or *unisolated* (the claimed component's own effect is not shown).

A mechanism counts as a reason only when the paper itself says when the method would not help, and the reader must copy that sentence word for word: the code looks for it in the text, and a quote it cannot find counts as not stated.

Each lever carries a status: *present* (the text shows it, with where), *controlled* (the paper rules it out) or *suspected*. Only levers shown in the text count. The reader used to list every lever that *could* matter, so every paper had five of them and the list could not tell papers apart.

A method needs **a reason or robustness**. A method with a wrong or missing reason can still earn its place, but only through gains that repeat across many settings. The verdicts follow by fixed rules:

| Verdict | Rule | On the map |
|---|---|---|
| **Claim not delivered** | Gate 0 says "not" | Folded. The problems it claimed go back to open (status *claimed*) |
| **Treasure candidate** | A proof or mechanism, not yet robust, and attractive to you | Station with a dashed ring, and on the reading list with the next check |
| **Solid** | Delivered, with a reason or robustness, and the gain is not confounded | Station |
| **Gain not attributed** | Would be solid or a treasure, but the text shows the gain may come from something else: a serious lever shown in the text (unequal tuning, a mismatched setup, a component trained on the metric, a chosen cost ratio), baselines not treated equally with no experiment that removes only the new idea, a partial delivery whose new part is not isolated, or a headline number the tables do not back. Adoption by later works on the map overrides this | Station, listed with the reasons |
| **Incremental** | Delivered, with neither a reason nor robustness | Folded |

When more than 70% of the gated works get the same verdict, the report says so at the top of its caveats: the checks may not be telling those works apart.

**Every fold has a reason.** A folded work carries a one-line summary of why it does not earn a station, plus evidence from its text: where the claim fails, what was and was not tested, which levers sit behind the number. A verdict that cannot point to the text never hides a work, and neither does a reading of only the abstract; the seed is never folded. Works kept for these reasons show the verdict and why they were kept.

**Showing or hiding them.** On the map, *Folded works: Hide / Show* switches all folded works on or off. Each line's "+N other attempts" badge unfolds just that line, and hovering it lists the works with their reasons. Shown folded works are faded, with the verdict next to their date ("not delivered", "incremental"); hovering one shows its reason, and clicking it opens a *Why it is folded* box with the evidence. The Reading list section lists them all with the same reasons. `render --folded show` (or `gates --folded show`) makes the report open with them shown.

**Taste.** A taste profile is a short Markdown file: who you are as a reader, the problems you care about, ideas you like and skip, and three to five papers you liked or disliked with one line each on why (examples steer the scorer more than descriptions). Three presets ship with the tool: `practitioner`, `theorist` and `newcomer`. Put your own in `./profiles/<name>.md` (start from `docs/taste-template.md`) and pass `--taste <name>`, or pass a file path; `python3 -m tastecal profiles` lists them all. Without `--taste`, `./taste.md` is used when it exists. The profile only decides which reasoned but unverified works become treasure candidates, and the reading order; the report names the profile it used. The gate prompt never sees it, so your taste steers what you read, not how the evidence is judged. The taste scorer, though, sees what the gate read found in each paper (what it delivers, the levers shown, the fairness checks, the reviewer's notes), because tastes are often about evidence ("I skip gains that come from tuning") and a summary card does not carry those details. Without a profile, every reasoned but unverified work is a treasure candidate. While you have rated fewer than 8 papers, the report suggests up to 5 works on the map to rate next, spread from low to high blind score.

**5. Plain language** (`report/polish.py`)

Every prompt that writes text for the reader carries the same rules: one idea per sentence (at most about 25 English words or 40 Chinese characters), at most three works named per sentence, no stacked adjectives or praise words, and a short explanation of a technical term the first time it appears. After the run, a lint finds sentences that still break the rules and one LLM pass rewrites only those. A rewrite that drops an `[[id]]` link or a number is thrown away and the original stays. `--language zh-CN` writes the whole report in Chinese.

```bash
python3 -m tastecal lint runs/<seed>/graph.json                  # which sentences break the rules (no LLM)
python3 -m tastecal polish runs/<seed>/graph.json --outlook      # rewrite them, and add What's next to an older graph
```

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
| `TAVILY_API_KEY` or `BRAVE_API_KEY` | Optional. Enables blog and report discovery; without one the run is papers-only |
| `GITHUB_TOKEN` | Optional. Raises GitHub's rate limit when the audit looks up repository stars |
| `UNPAYWALL_EMAIL` | Optional. Lets the reader find legal open-access copies of papers that are not on arXiv (falls back to `OPENALEX_MAILTO`) |
| `TASTECAL_LANGUAGE` | Optional. Default for `--language` |
| `TASTECAL_CACHE_DAYS` | Optional. Search results and citer lists older than this many days are fetched again (default 14; paper records 60; page text never) |
| `TASTECAL_MODEL_CUTOFF` | Optional, `YYYY-MM`. Marks a backtest whose cutoff falls before this date as illustrative |

Useful flags: `--effort low|medium|high|xhigh|max|default` (default: high; `default` = the model's own), `--scope "autonomous driving"` (limit the map to a field: works from other fields, such as a generic diffusion model, are listed under *Borrowed from other fields* instead of being mapped, read or audited, and do not use the budget; no limit by default), `--budget 30`, `--rounds 5`, `--expand-per-round 4`, `--max-back 2`, `--max-forward 2`, `--max-blogs 5`, `--no-openalex`, `--no-web`, `--out runs/my-run`, `-v`. Writing: `--language zh-CN`, `--no-polish`, `--no-outlook`. Reading: `--papers-dir papers`, `--taste practitioner`.
The audit and the gates run by default; `--no-assess` and `--no-gates` turn them off, and `run` uses `./taste.md` as the taste profile when it exists. Audit flags: `--assess-max 0` (default: every paper on the map plus the runners-up; a number keeps the seed and the most connected works, never just the oldest), `--no-review` (skip the advocate, critic and judge), `--popularity-weight 0.5` (default; 0.1 makes growth lean far less on citation counts).

**Rate as you read.** Open a report from the page (`serve`), click a work, and give it 1 to 5 under *Your rating*. The rating goes into your taste profile in `taste.json` (the one the report was made with, else your default), and every later run calibrates on it. A report opened as a plain file shows no rating buttons.

**Taste check.** With at least 3 rated papers, a run scores each of them with your taste profile while that paper's own rating is taken out, and the reading list section says how many pairs of your papers the profile puts in your order and how far off it is on average. The reading list is ordered by your scale when there is one, else by the taste score.

**Your taste versus the blind score.** The report plots every work's taste score against its blind contribution score, with the papers you rated drawn as diamonds (your rating against their blind score) and your ratings' fitted line. The map's medians split it into four corners: read first, you like it but the evidence is thin, strong but not your taste, and skip. The two disagreeing corners are listed beside the plot, with the taste scorer's reason for each. It needs taste scores (a profile) and the audit; rated papers are optional.

**Your scale.** When your taste profile has papers you rated (with a score), the audit scores them blind like the rest and fits the blind score to your ratings. Each work then also shows its score on your scale, and the report says how often the two put your papers in the same order. The blind score itself is unchanged, and the scorer never sees your ratings. Each rated paper that is not already on the map costs about six model calls.

**Side branches.** The map folds side branches into a "+N side branches" badge on each line: works tied to the seed only through applies, competes or explains links, or that the synthesis calls a branch or an explainer. The chain through the seed always shows. Works that did not pass the gates stay in place, drawn dashed with their verdict. "Side branches: Show" above the map, or `render --folded show`, opens them all.

An audit of 40 works adds roughly 6–8 LLM calls per work (claims check, citation roles, precedent search, blind score) plus 3 per flagged work.
Gate flags: `--gates-max 0` (default: every paper on the map), `--taste taste.md`. The `gates` command also takes `--raw answers.json`, `--attractive 0.6` (taste score that counts as attractive), `--today YYYY-MM` and `--folded hide|show`. Gating adds one LLM call per paper (each reads up to about 30k characters of full text) plus one per 6 papers for taste.

`--raw` takes a JSON object keyed by node id. Each value is one gate answer (`claimed`, `delivery`, `partial_kind`, `delivered`, `delivery_evidence`, `reason_type`, `reason`, `fails_when`, `fails_when_stated`, `robustness`, `robustness_note`, `levers` as `[{"lever", "status", "where", "note"}]`, `check_next`, `checks`), plus `basis` (`"full text"`, `"abstract"` or `"card"`), optionally `verified` as `{"fails_when": true|false}` (whether the quote was found in the text), and optionally `taste` as `{"score", "why"}`. Levers without a status count as suspected, so older answer files keep working.

**Cost and caching.** A 30-item run makes roughly 25–40 LLM calls, most of them small batched classification prompts, plus one ledger merge per round and four backtest calls. Every LLM reply is cached in `.tastecal_cache/`, so a re-run with the same settings costs nothing, and changing the synthesis prompts only re-runs synthesis. HTTP responses are cached with the time they were fetched: search results and citer lists are fetched again after 14 days (`TASTECAL_CACHE_DAYS`), paper records after 60, page text never. `--refresh` fetches every search and citer list again. When a fresh fetch fails, the old copy is used. The run log ends with an estimate of the token usage.

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

- Run the pipeline live on a seed you know well and compare the map and the gate verdicts with your own reading. This is the first real test of the prompts.
- Accept several seeds and merge their graphs into one field map.
- Add news and other source types. These would mostly feed the *external drivers* (why now) rather than the threads.
- Add a fixed evaluation set of seeds from fields you know, scored against the success criteria in `intention.md`.
