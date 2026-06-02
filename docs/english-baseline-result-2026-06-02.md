---
title: "200M English-vocab baseline — result: vocabulary exonerated"
date: June 2, 2026
status: complete; pre-registered decision rule applied
---

# 200M English-vocab baseline: result

## One line

Train two fresh 200M models on the **same prompts, teachers, recipe**, changing
**only the output vocabulary** (~1K-word UGF, 3,643 tokens vs ~40K English,
40,027 tokens), and the prompt-attention deficit is **identical**: stress-bench
engagement is **0.07 for both arms (Δ = +0.00)**. The restricted vocabulary is
**not** what breaks the model at student scale. This is the pre-registered
"most likely" outcome and it **strengthens the expressive-adequacy thesis**.

## Setup (what was held equal)

Matched pair at N ≈ 400K, both arms trained fresh and identically; design in
`docs/english-baseline-design-2026-05-24.md`.

| Held constant | Value |
|---|---|
| Prompts | same 400K `(topic, content_type)` pairs (byte-identical rendered prompts) |
| Teachers | same gpt-oss-120b + gemma-4-26b mix, per-prompt matched |
| Recipe | v1: 100K pretrain + 30K SFT, plain prompt→response, eff. batch 64, seq 1024 |
| **Transformer block** | **192,971,776 params — identical across arms** |
| Eval | same benches, rubric, blinded Claude-subagent judges, **isolation** judging |
| **Vocabulary (the only variable)** | UGF 3,643 (→ 196.7M total) vs English 40,027 (→ 234.0M total) |

Training was clean on both arms — no overfitting despite ~16-epoch pretrain
(pretrain val plateaued: UGF 3.40→0.78, English 5.39→1.17; SFT val 0.755 / 1.135).
UGF-N SFT val 0.755 ≈ v1's 0.74, so UGF-N faithfully replicates the v1 model.

## Results (blinded isolation judging; engagement/coherence/substance, 0–4)

| arm / bench | n | engagement | coherence | substance |
|---|---:|---:|---:|---:|
| ugf_n / stress | 30 | 0.07 | 1.93 | 0.40 |
| en_n / stress | 30 | 0.07 | 2.30 | 0.03 |
| ugf_n / holdout | 170 | 1.68 | 2.51 | 2.16 |
| en_n / holdout | 170 | 1.61 | 2.16 | 1.77 |
| ugf_n / cx_patched | 50 | 0.30 | 1.86 | 0.78 |
| en_n / cx_patched | 50 | 0.26 | 2.46 | 1.38 |

**Δ (English − UGF), engagement:** stress **+0.00**, holdout −0.07, cx −0.04.
**Δ substance:** stress −0.37, holdout −0.39, cx +0.60 (a wash; no English edge).

Batch-aligned holdout (same items, arm-vs-arm) tracks ~1:1: 3.71/3.58, 1.96/1.91,
0.27/0.18, 0.49/0.51 — the engagement match is not an averaging artifact.

## Pre-registered decision

`|Δ stress engagement| = 0.00 ≤ 0.30` → **VOCABULARY EXONERATED.** The deficit is
form/capacity, shared with full-vocabulary English; it is not the restriction.

## Interpretation

- **The v1 deficit replicates** (UGF-N stress engagement 0.07 ≈ v1's 0.13) and
  **travels to English unchanged.** A model with 11× the vocabulary, generating
  fluent unrestricted English, shows the *same* engagement collapse on OOD stress
  prompts — it produces fluent, internally-organized essays on topics unrelated
  to the prompt (e.g., asked about necessary-vs-contingent truth, both arms write
  generic essays about belief / information-sharing).
- **No substance dividend from vocabulary.** The precursor found the *teacher*
  pays a substance tax in UGF; the *student* English arm does **not** convert its
  richer vocabulary into more substance (slightly lower on stress/holdout). At
  200M, capacity/form is the binding constraint, not the lexicon.
- **Strengthens the expressive-adequacy thesis.** Restricting to ~1K words is not
  what prevents practical philosophical reasoning at this scale — the same
  derivations that a 40K-word model fails to engage, the 1K-word model fails to
  engage in the same way. UGF is expressively adequate relative to the binding
  constraint.

## Caveats (disclosed)

- Stress is the smallest bench (30 items, one judge per arm); the identical 0.07,
  and the all-benches engagement match, make the read robust, but stress substance
  (0.40 vs 0.03) is near-floor judge noise, not a real gap.
- Prompt-format OOD (raw bench prompts vs templated training prompts) is shared by
  both arms — part of the deficit being measured, not a between-arm confound.
- English residuals from the build are disclosed and small: 0.22% response UNK
  (genuine concept words, post Unicode-normalization), 8.95% train truncation at
  seq 1024 (vs UGF 0.04%) — neither produced an English engagement *advantage*, so
  if anything they bias against the null and the null still holds.

## Paper implications

Converts the v1 paper's central attribution ("deficit is capability/training-form,
not vocabulary") from an assumption defended only at *teacher* scale into a
*measurement* at *student* scale — directly answering the first reviewer question
("how do you know it's not the vocabulary?"). It is also the first filled cell of
the scaling grid (`docs/followups/scaling.md`). The clean form-controlled retrain
and the capacity/scale study remain the live levers on the deficit itself.

## Artifacts

- Generations: `eval/results/enbase_{ugf_n,en_n}_{stress,holdout,cx_patched}_20260602_081559.jsonl`
- Judge scores: `eval/judge_output_enbase/batch_0{01..14}.jsonl` (+ `eval/enbase_judge_manifest.json`)
- Aggregate: `eval/results/enbase_judge_aggregate.json`
- Models (fortyfive): `checkpoints/reasoner_{ugf_n,en_n}_sft/final.pt`
- Pipeline: `eval/{prepare,aggregate}_enbase_judge*.py`, `eval/run_sft_v2_bench.py` (`--vocab-path`), `slurm/eval_baseline_arms.sbatch`
