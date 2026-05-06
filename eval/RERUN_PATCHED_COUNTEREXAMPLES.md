# Re-running the patched counterexample subset

The 50 counterexample_analysis items in `eval/sets/holdout_bench.jsonl` had
their `question` fields hard-truncated to 80 characters by a bug in
`corpus/generation/cxbot_ugf_to_reasoning.py:57` (now fixed). The patched
holdout in `eval/sets/holdout_bench_patched.jsonl` has the full definitions
restored from the cx-bot source.

To get unbiased numbers for this slice we re-run the eval pipeline on the
patched 50 items only, leaving the other 120 holdout items untouched (their
scores are already valid).

## Step 1 — extract the 50 patched items into a sub-bench

```bash
python3 -c "
import json
with open('eval/sets/holdout_bench_patched.jsonl') as f, \
     open('eval/sets/holdout_bench_cx_patched.jsonl', 'w') as g:
    for line in f:
        r = json.loads(line)
        if r.get('type') == 'counterexample_analysis':
            g.write(line)
"
```

## Step 2 — Reasoner pipeline (on fortyfive)

```bash
ssh fortyfive.hpc.uidaho.edu
cd ~/compression
git pull
sbatch slurm/run_holdout_bench.sbatch eval/sets/holdout_bench_cx_patched.jsonl \
       eval/results/holdout_cx_patched_reasoner.jsonl
```

(The existing SLURM script accepts the bench file path as the first
positional arg; if it doesn't, edit it to do so or invoke
`run_logic_bench.py --skip-translate-en2ugf` directly.)

## Step 3 — Comparator pipeline (locally or on fortyfive)

```bash
python3 eval/run_comparator.py \
    --bench eval/sets/holdout_bench_cx_patched.jsonl \
    --output eval/results/holdout_cx_patched_comparator.jsonl
python3 eval/translate_ugf_to_english.py \
    --input eval/results/holdout_cx_patched_comparator.jsonl \
    --output eval/results/holdout_cx_patched_comparator_with_english.jsonl
```

(Comparator runs through MindRouter and respects the AsyncTokenBucket
rate limiter; safe to run locally.)

## Step 4 — re-judge via parallel Claude subagents

Prepare new judge batches for the patched outputs:

```bash
# Manually update prepare_judge_batches.py SOURCES dict to point at the new files,
# OR write a one-shot batch-prep targeting only these two files.
```

Then dispatch ~2 parallel agents (one per system) using the same prompt
template as in the May 5 run. Outputs go to `eval/judge_output/`,
overwriting the old reasoner_holdout / comparator_holdout cx-batch outputs
where they overlap.

## Step 5 — aggregate

```bash
python3 eval/aggregate_judge_scores.py
```

The aggregator reads everything in `eval/judge_output/` and joins back
to the original `holdout_bench.jsonl` (via id) for the type field. As long
as the new outputs have the same ids as the old ones, the join works
unchanged. The new aggregate will replace the old counterexample numbers.

## Expected impact

The current Layer-3 numbers show counterexample_analysis with the worst
deltas in the holdout (engagement −3.34, substance −1.16, n=50 — the
single biggest contributor to the holdout-side engagement gap of −1.53).

If the truncation was the dominant cause, we should see the
counterexample_analysis engagement delta narrow substantially, dragging
the overall holdout engagement gap closer to the −0.4 range we see on the
other dimensions. If it doesn't move much, the failure is more
fundamental (model can't do counterexample analysis) and the honest
report stands.

Either outcome is publishable — but the *current* number is contaminated
by a data-layer bug and should not stand as-is.
