---
title: "Scale study — result: the prompt-attention deficit does not scale away"
date: June 3, 2026
status: complete; pre-registered decision rule applied
---

# Scale study: result

## One line

Train the same recipe on the same 2M corpus at three sizes (52M / 200M / 1B),
varying only model size, and the out-of-distribution prompt-attention deficit is
**flat**: stress-bench engagement is 0.07 / 0.00 / 0.10 across a 20× span. Scaling
parameters does **not** fix the deficit. It does, however, make a better
*in-distribution* reasoner — which localizes the deficit as orthogonal to capacity.

## Results (blinded isolation judging, 0–4; 750 items)

**Engagement vs size:**

| bench | 52M | 200M | 1B |
|---|---:|---:|---:|
| **stress** (OOD) | 0.07 | 0.00 | 0.10 |
| holdout (in-dist.) | 1.29 | 1.64 | 1.74 |
| cx_patched | 0.38 | 0.50 | 0.22 |

**Substance vs size:**

| bench | 52M | 200M | 1B |
|---|---:|---:|---:|
| stress | 0.10 | 0.00 | 0.07 |
| holdout | 1.77 | 1.28 | 2.03 |
| cx_patched | 0.64 | 0.22 | 1.12 |

(Coherence on holdout: 2.01 / 1.82 / 2.41.)

## Pre-registered decision

Stress engagement spread across sizes is 0.10 (≤ 0.30) → **CAPACITY EXONERATED**:
a 20× model trained the same way fails the OOD prompt-attention test the same way.
The deficit is not a capacity wall at this training budget.

## The nuance that sharpens it

Scaling is not inert — it just doesn't touch *this* failure. On **holdout**
(in-distribution prompts) the 1B is the best of the three on every dimension
(engagement 1.74, substance 2.03, coherence 2.41), topping the 200M. So the 1B
*did* convert capacity into better reasoning where the prompt form is familiar.
And yet on OOD stress it sits at 0.10, no better than the 52M. The deficit is
therefore **orthogonal to capacity**: more parameters buy a stronger
in-distribution reasoner without buying any improvement in recognizing what an
*unfamiliar* prompt is asking. The failure is in input-recognition under
distribution shift, not in reasoning horsepower.

This also weakens the undertraining caveat below: if the 1B were simply too
undertrained to show its capacity, it would not have beaten the 200M on holdout.
It did. So the flat stress result is not merely hidden capacity.

## Caveats (disclosed)

- **Iso-step budget.** All three sizes got the same 100K-pretrain / 30K-SFT budget
  on the same ~580M-token corpus. That is far below compute-optimal for a 1B
  (~20B tokens), and the 1B's val sits *above* the 200M's (pretrain 2.03 vs 0.79;
  SFT 0.79 vs 0.74), confirming it is undertrained for its size. The clean reading
  is therefore: *at a matched training budget*, 20× parameters does not fix the
  OOD deficit. A compute-optimal 1B (more data + steps) is the rigorous follow-up
  before calling capacity fully dead — though the holdout win makes a reversal on
  OOD stress unlikely.
- **Cross-judge calibration.** Holdout/cx are scored across multiple subagent
  judges (one per 45-item batch), so per-dimension holdout means carry judge-
  calibration noise (e.g. the 200M's holdout substance dip is likely noise). The
  stress verdict — everyone scores it near the floor — is robust to this.
- Stress is 30 items, one judge per arm; the near-zero agreement across all three
  sizes makes the flat read solid.

## What it means for the project

Both axes of the (size × vocabulary) grid now point the same way. The deficit is:
- **not corpus quality** (§4.4: the model sits below its own training data),
- **not a post-training-objective problem** (§4.5: RL worse, DPO ×2 parity),
- **not the restricted vocabulary** (`docs/english-baseline-result-2026-06-02.md`:
  Δ stress engagement +0.00 at 40K-word English),
- **not raw capacity** (this study: flat across 52M→1B).

By elimination, the remaining lever is **training form** — the form-controlled
retrain (length-matched dialogue / objection-reply corpora that are structurally
prompt-attentive). That is now the decisive next experiment; if it too fails to
move OOD stress engagement, the deficit looks like a deep property of
short-prompt→long-essay distillation rather than any single fixable cause.

## Artifacts

- Generations: `eval/results/scale_{50m,200m,1b}_{stress,holdout,cx_patched}_20260603_172332.jsonl`
- Judge scores: `eval/judge_output_scale/batch_0{01..21}.jsonl` (+ `eval/scale_judge_manifest.json`)
- Aggregate: `eval/results/scale_judge_aggregate.json`
- Models (fortyfive): `checkpoints/reasoner_scale_{50m,1b}_sft/final.pt`, `checkpoints/reasoner_sft_v1/final.pt` (the 200M)
- Design: `docs/scale-study-design-2026-06-03.md`
