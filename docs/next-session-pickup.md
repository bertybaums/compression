---
title: Pickup list for next session
date: May 22, 2026
audience: future-Bert + future-Claude
---

# Pickup list — after RL v3, pivoting to Option B

Supersedes the May-20 version. Read `memory/session_status.md` first, then
`memory/rl_v3_outcome_2026-05-22.md`, then this.

## Where we are

The self-play GRPO experiment (Option A) is **done and decisively failed both
pre-registered checks** (training reward never crossed 0.28; held-out RL-vs-SFT-v2
bench eval has RL behind on substance −0.50 and engagement −0.68 via off-topic
boilerplate mode collapse). Full result: `docs/rl-v3-results-2026-05-22.md`,
progress-report §19, and `memory/rl_v3_outcome_2026-05-22.md`.

**SFT-v2 (`checkpoints/reasoner_sft_v2/final.pt`) remains the best deployable
Reasoner.** The RL v3 checkpoint is not promoted.

The decision is to **pivot to Option B**: regenerated P4 references as a *fixed
reference distribution* the policy is pulled toward, instead of pure self-play.
Spec sketch in `docs/rl-design-2026-05-18.md` §"Option B fallback".

## Step 0 — re-auth SSH (if stale)

```
! ssh -fN fortyfive.hpc.uidaho.edu
```
(Bert runs this; triggers the Duo/password prompt in-session.)

## Step 1 — design the Option B reference-generation pipeline

Option B was only ever sketched, not specified. Decisions to lock before building:

1. **Prompt set.** Which prompts get P4 references? Start from the RL training
   prompt source (`eval/prepare_rl_prompts.py`). Decide count (a few thousand is
   plenty for a reference CE term) and source mix (logic vs philosophy).
2. **Reasoning/claim split.** P4 = gpt-oss-120b English reasoning →
   split into reasoning + final claim → translate each to UGF via
   `translator/mr_structured_translator.py` → wrap with the v2 marker
   ("So my answer is:"). The split heuristic on the English output is the noisy
   part; spec it explicitly (e.g. last paragraph / explicit "answer:" cue).
3. **Compliance filter.** Reject any reference whose UGF isn't wordlist-compliant
   *and* doesn't parse (single marker, non-empty answer span). Measure the
   yield — the May-14 probe lost ~36% of P4 to 422s + non-compliance, so budget
   for it.
4. **How the reference enters the loss.** Per the design doc, either a separate
   CE term `total = grpo_loss + λ_sft·CE(sft) + λ_ref·CE(ref)`, or treat the
   P4 reference as the SFT-mix example itself (simpler — swap the anchor source
   from CoT corpus to P4 refs). Lean toward the latter first; it's one knob.
5. **Rate limits.** Reference generation goes through MR (gpt-oss-120b +
   translator). Respect the `AsyncTokenBucket` cap; don't run concurrent MR
   generation. This is offline + cached, so it's a one-time cost.

## Step 2 — build + smoke-test

- New config `configs/reasoner_rl_v4.yaml` (Option B); reference cache path;
  `λ_ref` (start ~0.3–0.5).
- Reuse `reasoner/train_rl.py`; add the reference-CE path (or reference-as-anchor).
- Smoke: ~100 steps from SFT-v2. **Pre-registered bar (carry over): beat the
  SFT-v2 answer-span baseline by ≥ 0.05 reward by step 100, AND don't regress
  parse-rate.** If it clears, run longer; if not, RL is done for v1 and SFT-v2 is
  final.
- Eval exactly as for v3: `slurm/eval_rl_v3_bench.sbatch` (point `CKPT` at the v4
  final), then `eval/prepare_rl_milestone_judge_batches.py` (sftv2 vs the v4
  outputs) + parallel Claude judges + `eval/aggregate_rl_milestone.py`.

## The fork to keep in view

If Option B also fails to beat SFT-v2 on held-out benches, the honest call is:
**SFT-v2 is the final v1 Reasoner**, and the RL-negative result + the
prompt-attention-deficit story (§13, §16, §19) becomes a clean paper finding.
Don't keep iterating RL recipes past two genuine attempts at this scale.

## Key files

| Artefact | Path |
|---|---|
| RL v3 results writeup | `docs/rl-v3-results-2026-05-22.md` |
| RL design (+ Option B sketch) | `docs/rl-design-2026-05-18.md` |
| GRPO trainer | `reasoner/train_rl.py` |
| Reward (gates + weighted) | `reasoner/rl_reward.py` |
| Judge client (Nemotron jury) | `reasoner/rl_judge.py` |
| Rollout buffer | `reasoner/rl_rollout.py` |
| RL prompt prep | `eval/prepare_rl_prompts.py` |
| Structured translator (for P4) | `translator/mr_structured_translator.py` |
| Bench eval pipeline | `slurm/eval_rl_v3_bench.sbatch`, `eval/prepare_rl_milestone_judge_batches.py`, `eval/aggregate_rl_milestone.py` |
| Best Reasoner | `checkpoints/reasoner_sft_v2/final.pt` (fortyfive) |

## Gotchas carried forward

- **Decode anti-rep is mandatory** for v2/RL generation: `--repetition-penalty 1.2
  --no-repeat-ngram-size 4`. Doom-loops are a decode-time issue.
- **RL training judge is MR Nemotron-3-Super-120b**, calibrated against Claude;
  bench-eval judge is Claude subagents. Don't run other MR generation while RL
  judging runs.
- **Heredoc/sbatch logs land in the submit dir** (`~/compression/`); the sbatch
  `mv`s them to `logs/` on clean exit only.
- **System python on fortyfive is 3.6; activate `~/venvs/compression` (3.11).**
- **Blinded judging needs opaque ids** (no system label in the id field).
