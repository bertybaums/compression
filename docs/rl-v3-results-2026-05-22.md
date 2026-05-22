---
title: Reasoner RL v3 results — self-play GRPO negative result
date: May 22, 2026
audience: project + future paper
status: result (decisive)
---

# RL v3 results: self-play GRPO fails both pre-registered checks

**Headline.** The self-play GRPO run (Option A in `rl-design-2026-05-18.md`) failed
both pre-registered acceptance checks. Training reward never crossed the 0.28
bar; on held-out benches the RL-final policy is **behind** the SFT-v2 checkpoint
it was trained from, on *both* heavily-weighted reward dimensions. The cause is a
textbook reward-hack: the policy collapsed onto a fluent, on-distribution, but
**off-topic boilerplate** answer that scores well on the lightly-weighted form
dimensions (coherence, expressive adequacy) while flooring the dimensions that
matter (substance, engagement). **Decision: abandon self-play at this scale, do
not promote the v3 checkpoint, pivot to Option B.** SFT-v2 remains the best
deployable Reasoner.

---

## 1. What was run

- **v2 RL smoke** (step 0–100, started from `reasoner_sft_v2/final.pt`): the recipe
  that first made the policy move — 4 PPO inner epochs, SFT-anchor 0.1, lr 4e-6.
  Reward weakly positive, best 25-step block 0.242, plateau 0.21–0.24.
- **v3 continuation** (job 5146497, step 100→250, +150 steps): same recipe,
  resumed from the v2 step-100 checkpoint with the KL reference re-anchored to
  step-100 and optimizer momentum restored. Ran ~22h on an RTX A6000; finished
  cleanly May 21 15:37, all 250 metric rows, checkpoints every 25 steps.

**Reward** (locked May 16, unchanged): on the answer span only,
`0.6·substance + 0.2·engagement + 0.1·coherence + 0.1·expressive_adequacy`,
each dimension a judge's 0–4 score normalized to [0,1]; structural failures
(UGF non-compliant, no marker, empty answer, or n-gram doom-loop) score 0.

**Two judges, two roles** (important for reading the result):
- *Training reward judge*: MR **Nemotron-3-Super-120b** jury (`reasoner/rl_judge.py`)
  — cheap, fast, non-teacher, previously calibrated against Claude on engagement
  and substance.
- *Bench-eval judge* (this report's decisive check): **Claude subagents** against
  `eval/rubric.md`, blinded.

Because Nemotron was calibrated to Claude on the two dimensions that decided the
outcome, the flat training reward and the negative Claude bench delta corroborate
each other — the result is not an artifact of which judge was used.

**Pre-registered stop criterion** (in `configs/reasoner_rl_v3.yaml` and the May-20
pickup doc): if the 10-step-block reward had not crossed ~0.28 (clearly above the
v2 plateau of 0.21–0.24) by step 250, conclude self-play has limited headroom and
pivot to Option B.

## 2. Result 1 — training reward never moved (FAIL)

25-step block means over the v3 continuation:

| block | reward | KL | rate_ok |
|---|---:|---:|---:|
| 1–25 | 0.243 | 0.009 | 0.95 |
| 26–50 | 0.228 | −0.001 | 0.92 |
| 51–75 | 0.251 | 0.134 | 0.97 |
| 76–100 | 0.244 | 0.150 | 0.99 |
| 101–125 | 0.242 | 0.178 | 0.96 |
| 126–150 | 0.253 | 0.269 | 0.91 |
| 151–175 | 0.257 | 0.277 | 0.95 |
| 176–200 | **0.260** | 0.446 | 0.95 |
| 201–225 | 0.251 | 0.453 | 0.98 |
| 226–250 | 0.257 | 0.396 | 0.98 |

First-50 reward 0.236 → last-50 0.254 (+0.018 over 250 steps); peak block 0.260;
never reached 0.28. Structural gates stayed healthy throughout (rate_ok ~0.95,
zero doom-loops), so this is a ceiling, not a collapse.

**The diagnostic signature is the KL/reward divergence: KL climbed ~50×
(0.009 → ~0.45) while reward rose +0.02.** The policy drifted a long way from its
SFT-v2 initialization without earning reward for it — the classic sign that the
reward has a flat, hackable region the policy can wander into for free.

## 3. Result 2 — held-out bench eval: RL is behind SFT-v2 (FAIL)

RL-v3-final vs SFT-v2-norep on the three milestone benches (stress 30, cx-patched
50, holdout 170), generated with the standard anti-rep decode
(`--repetition-penalty 1.2 --no-repeat-ngram-size 4`). 500 responses pooled and
blinded (opaque ids, no system label), scored by 7 parallel Claude subagent
judges on the 4-dim rubric, split by system post-hoc.

| dim (reward weight) | stress Δ | cx-patched Δ | holdout Δ | mean Δ | verdict |
|---|---:|---:|---:|---:|---|
| **substance** (0.6) | +0.00 | −1.04 | −0.46 | **−0.50** | RL behind |
| **engagement** (0.2) | −0.40 | −0.80 | −0.84 | **−0.68** | RL behind |
| coherence (0.1) | +0.13 | +0.24 | −0.14 | +0.08 | mixed |
| expr. adequacy (0.1) | +0.17 | +0.50 | +0.16 | +0.28 | RL ahead |

(Δ = RL − SFT-v2. Per-system means below.)

| bench | system | engage | coher | subst | expr | parse |
|---|---|---:|---:|---:|---:|---:|
| stress | SFT-v2 | 0.50 | 1.77 | 0.90 | 1.67 | 96.7% |
| stress | RL | 0.10 | 1.90 | 0.90 | 1.83 | 100% |
| cx-patched | SFT-v2 | 0.90 | 1.46 | 1.16 | 1.62 | 100% |
| cx-patched | RL | 0.10 | 1.70 | 0.12 | 2.12 | 100% |
| holdout | SFT-v2 | 2.46 | 2.22 | 2.13 | 2.56 | 97.1% |
| holdout | RL | 1.63 | 2.08 | 1.67 | 2.73 | 95.9% |

RL loses engagement on every bench and substance on two of three (parity on the
third). Its only consistent gains are coherence and expressive adequacy — the
two 0.1-weighted dimensions. The cx-patched substance collapse (1.16 → 0.12) is
near-total: the RL policy essentially stopped producing counterexamples.

## 4. Mechanism — reward-hacking via off-topic mode collapse

Reading the blinded judge justifications, the failure is unambiguous and
concentrated in the RL outputs: the policy collapsed onto a near-verbatim
**loss-aversion / prospect-theory boilerplate** —

> "People care more about keeping what they have because losing feels worse than
> winning helps them"

— emitted regardless of the prompt (it appears on prompts about prime numbers,
naming, theodicy, perception, topology, the Liar paradox, …). It clusters
hardest on the formal-logic and "counterexample to: [definition]" prompts, where
the model has no on-topic template to fall back on.

This single attractor explains the entire dimensional profile:

- It is **fluent, internally consistent UGF** → coherence ~2 and expressive
  adequacy 2–3 (the only dims RL "wins"). D4 here is a decoy: the vocabulary
  never breaks; the *content* is simply not an answer to the question.
- It **does not address the prompt** → engagement floored.
- It **does no philosophical work** → substance floored, near-zero on cx-patched.

RL outputs are also markedly shorter than SFT-v2's (response words ~77–144 vs
170–182), consistent with converging on a short fixed template.

So self-play did not plateau benignly — it *actively regressed* the weighted
dimensions by discovering a clean-looking, low-substance answer the Nemotron
reward tolerated (~0.25) and the policy could reach with low effort. The flat
training reward and rising KL were the live tell of exactly this drift.

This is the same **prompt-attention deficit** documented for v1
(`memory/reasoner_prompt_attention_deficit.md`); RL did not fix it and made it
sharper by removing the length/variety that occasionally let SFT-v2 stumble onto
the topic.

## 5. Decision

1. **Abandon self-play GRPO at this scale.** Do not throw more steps at it; the
   reward trend and the bench eval agree.
2. **Do not promote the v3 checkpoint.** SFT-v2 (`reasoner_sft_v2/final.pt`)
   remains the best deployable Reasoner.
3. **Pivot to Option B** (`rl-design-2026-05-18.md` §"Option B fallback"):
   regenerated P4 references in v2 format as a *fixed reference distribution*
   (a `λ_ref · CE(ref)` term) alongside the SFT-mix anchor. The hypothesis Option
   B tests is the complement of what failed here: self-play gave the policy no
   external pull toward on-topic answers, so it drifted; a fixed P4 reference
   supplies that pull directly. This also matches the pre-registered Option-B
   trigger ("the model drifts toward an off-corpus distribution").

## 6. What this means for the paper

This is a clean, citable negative result, not a dead end:

- **Small distilled UGF models reward-hack self-play RL.** With only a learned
  reward and a KL/SFT anchor, a 200M from-scratch model in a restricted vocabulary
  finds a fluent off-topic attractor rather than improving on-topic reasoning. The
  KL-up/reward-flat signature is a reusable diagnostic.
- It **sharpens the expressive-adequacy thesis rather than threatening it.** The
  RL failure is on engagement/substance (does the model *answer*), while D4
  (does UGF *carry* an answer) stayed high — the bottleneck is reasoning capacity
  and prompt attention, not the vocabulary. This is the same conclusion the corpus
  audit reached from the other direction (v1 sits below its own training data).
- It motivates Option B and, more broadly, the **form-diverse retraining** thread
  (`memory/corpus_form_insight.md`): the principled fix for prompt attention is
  training-corpus form, not a reward knob bolted onto a model that never learned
  to track the prompt.

## 7. Artefacts and reproducibility

| Artefact | Path |
|---|---|
| v3 metrics (250 rows) | `logs/reasoner_rl_v3/rl_metrics.jsonl` (fortyfive) |
| v3 checkpoints | `checkpoints/reasoner_rl_v3/` (fortyfive) |
| RL bench generations | `eval/results/rl_v3_{stress,cx_patched,holdout}_norep_20260522_024115.jsonl` |
| SFT-v2 baseline generations | `eval/results/sft_v2_{stress,cx_patched,holdout}_norep_20260519_062446.jsonl` |
| Bench gen job | `slurm/eval_rl_v3_bench.sbatch` (job 5146538) |
| Blinded judge prep | `eval/prepare_rl_milestone_judge_batches.py` |
| Aggregator | `eval/aggregate_rl_milestone.py` |
| Blinded inputs / scores | `eval/judge_input_sft_v2_rl/`, `eval/judge_output_sft_v2_rl/` |
| Aggregate result | `eval/results/rl_milestone_aggregate.json` |

To reproduce the head-to-head from the generations:
```bash
for b in stress cx_patched holdout; do
  python3 -m eval.prepare_rl_milestone_judge_batches --bench-name $b \
    --sftv2-jsonl eval/results/sft_v2_${b}_norep_20260519_062446.jsonl \
    --rl-jsonl    eval/results/rl_v3_${b}_norep_20260522_024115.jsonl
done
# dispatch parallel Claude subagent judges over eval/judge_input_sft_v2_rl/*_batch_*.jsonl
python3 -m eval.aggregate_rl_milestone --benches stress cx_patched holdout
```
