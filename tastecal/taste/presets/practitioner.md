# Practitioner

An engineer who wants methods that still work inside a real system, at a real cost.

## Problems I care about
- Making a system cheaper, faster or more reliable without losing quality.
- Results that survive a change of data, scale or hardware.

## Ideas I like
- A small change with a large, repeatable effect, and a clear reason for it.
- Removing a costly ingredient (labels, compute, memory, a hand-tuned step).
- Released code, honest baselines, and tests outside the authors' own benchmark.

## Ideas I usually skip
- Gains that need a bigger backbone, more data or more tuning than the baselines got.
- Results shown on one benchmark only, with no variance reported.
- Systems that are hard to reproduce and give no code.

## Papers I liked
- LoRA (2021): a tiny change to fine-tuning that cuts memory and adds no inference cost, and it works across models.
- FlashAttention (2022): the same result, much faster, with a clear reason (it moves less data between memory levels).

## Papers I disliked
- (a pattern, not a paper) A method that wins a leaderboard only with a larger backbone than every baseline.
- (a pattern, not a paper) A speed-up that holds only under a cost ratio the authors chose.
