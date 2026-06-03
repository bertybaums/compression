---
title: "Scale study — does the prompt-attention deficit dissolve with model size?"
date: June 3, 2026
status: design (pre-build), decisions locked, pre-registered
---

# Scale study: the capacity axis

## The question

The prompt-attention deficit — fluent, well-formed reasoning about something
other than what was asked, stress-bench engagement ~0.1 at 200M — has now resisted
RL, two rounds of DPO, naive form-SFT, and (the English-vocab baseline,
`docs/english-baseline-result-2026-06-02.md`) a 40× vocabulary expansion. Two
suspects remain: **training form** and **model capacity**. This study isolates
capacity: train the *same recipe on the same corpus* at three model sizes and read
stress engagement vs size.

## No losing outcome (pre-registered)

| 1B stress engagement vs 200M | Reading | Effect |
|---|---|---|
| ≫ 200M (crosses toward engaging, e.g. +1.0 / into the 2s) | **Capacity wall** — the deficit is a small-model limitation; bigger models reason on demand | Big reframe: the deficit is a scale effect, not a permanent property |
| ≈ 200M ≈ 52M (flat curve) | **Capacity exonerated** — a 5× model trained the same way fails the same way | The deficit is training-**form**; the form-retrain becomes the decisive remaining lever, and the finding is more fundamental |
| Gradual rise | Partial — quantifies capacity's share | A curve, not a cliff |

**Honest expectation:** lean slightly toward *flat*. The deficit has shrugged off
every post-training lever and the vocabulary swap, and the corpus audit put the
200M model *below* its own training data (so it is not starved for signal). But
more capacity genuinely might let the model learn prompt-recognition from the same
traces, so it is close to a coin-toss. Either way the result is decisive, and it
fills the parameter axis of the (size × vocabulary) grid the English baseline began.

## Design — three points, everything fixed but size

| Point | d_model / layers / heads / kv / d_ff | Params | Source |
|---|---|---|---|
| Small | 768 / 8 / 12 / 3 / 2048 | ~52M | train fresh |
| Medium | 1024 / 16 / 16 / 4 / 3072 | ~197M | **reuse v1** (`checkpoints/reasoner_sft_v1/final.pt`) |
| Large | 2048 / 22 / 16 / 8 / 5504 | ~1.03B | train fresh |

**Held constant across the three:**
- **Corpus:** the full 2M v1 corpus (pretrain on ugf_reasoning + cxbot + misccorpora
  + parallel_corpus; SFT on ugf_reasoning). Chosen over the 400K matched-N set so
  the 1B is not data-starved — that would confound size with data.
- **Recipe:** v1's — 100K pretrain + 30K SFT, seq 512, SFT-v1 template format,
  effective batch 64. The 1B uses batch 4 / grad_accum 16 (vs 8/8) purely for
  memory; the effective batch is identical.
- **Vocabulary:** UGF (3,643 tokens), held constant — this study varies size only.
- **Eval:** the English-baseline pipeline (`eval/run_sft_v2_bench.py` → blinded
  isolation judging by Claude subagents → `eval/aggregate_*`), all three judged
  identically. Reusing v1 means re-judging it through this pipeline so the 200M
  point is on the same footing as the new two.

**Why reuse v1 for the middle.** v1 is exactly a 200M model on the 2M corpus + this
recipe, so it is the legitimate medium point; retraining it would only spend compute
to reproduce it. The 52M and 1B clone v1's configs, changing only model dims (and,
for the 1B, the batch split).

## Build / compute

- Configs: `configs/reasoner_scale_{50m,1b}_{pretrain,sft}.yaml`.
- Launch: `slurm/train_scale_50m.sbatch` (gpu-8, ~few hours) +
  `slurm/train_scale_1b.sbatch` (gpu-8-long, **~4–6 GPU-days — the long pole**).
  Each runs pretrain → SFT in sequence (`set -e`).
- Memory: 1B at seq 512 / batch 4 should sit well under the A6000's 48GB; watch the
  first steps (gradient_checkpointing is a no-op here). OOM fallback: batch 2 /
  accum 32, resubmit (pretrain checkpoints resume).
- Sanity at init: loss should start near ln(3643) ≈ 8.2 for every size (correct
  random init), as it did for both English-baseline arms.

## Eval (pre-registered)

Generate all three on stress (primary) + holdout + cx_patched with matched anti-rep
decode; judge in isolation; aggregate engagement / coherence / substance; plot vs
size and apply the decision-rule table above. Substance and coherence are reported
alongside but the verdict is on **stress engagement vs size**.
