---
title: Stage-1 preference tuning (DPO / APO-zero) — design
date: May 22, 2026
audience: project + future paper
status: design (pre-build)
---

# Stage-1 preference tuning: DPO / APO-zero before GRPO

## Why this, why now

The v3 self-play GRPO run reward-hacked: the policy drifted into a fluent
off-topic "loss-aversion boilerplate" that the scalar Nemotron reward tolerated
(~0.25) while engagement and substance collapsed on held-out benches
(`docs/rl-v3-results-2026-05-22.md`). The `tlm-playbook` names this failure
directly — `6_rl.md`: *"RLHF at tLM scale runs into a particular trap: the
reward model is usually much larger than the policy model, and the gradient
signal becomes dominated by the reward model's biases."* Our judge is a 120B
model scoring a 200M policy (~600×).

The playbook's prescribed mitigation (Labonne 2026, the LFM2.5 pipeline) is a
**two-stage** recipe — *Stage 1 on-policy DPO + jury filtering, then Stage 2 RL
with an n-gram penalty*. We ran Stage 2 only and explicitly logged skipping
Stage 1 (`docs/rl-design-2026-05-18.md`). **This doc specs the skipped Stage 1.**
It runs *before* a re-attempt of GRPO (Stage 2), on a model already pulled off
the off-topic attractor by a hack-resistant contrastive objective.

Why a contrastive objective is the right tool for *this* failure:

- A **scalar** reward is satisfiable by any fluent text — that's how v3 drifted.
  A **contrastive** objective trains on explicit (chosen, rejected) pairs, and
  we put the v3 failure mode (off-topic boilerplate, doom-loops) on the
  *rejected* side. The signal is "be more like this good answer and less like
  *your own* bad one," not "go up on a number."
- **APO-zero** (D'Oosterlinck et al. 2024, arXiv:2408.06266) pushes the chosen
  probability *up* and the rejected probability *down independently*, where DPO
  only optimises their relative gap (and can push both down together). SmolLM3
  found APO-zero strongest for **out-of-domain** post-training (AlexWa2026) —
  and OOD prompt-attention is exactly our deficit.

## Algorithm

Implement both behind a config flag; **default APO-zero**, DPO as the
conservative comparison.

Let `Δ(y) = log π_θ(y|x) − log π_ref(y|x)` (sequence log-prob ratio vs the frozen
SFT-v2 reference), `y_w` = chosen, `y_l` = rejected, β a temperature.

```
DPO:       L = −log σ( β·(Δ(y_w) − Δ(y_l)) )
APO-zero:  L = −log σ( β·Δ(y_w) ) − log σ( −β·Δ(y_l) )
```

(APO-zero form to be verified against arXiv:2408.06266 §3 at implementation;
the intuition — decouple "push chosen up" from "push rejected down" — is the
locked design.)

**Length-bias guard.** DPO notoriously exploits length (longer ⇒ chosen). v3's
collapse went *short*; SFT-v2 and P4 refs run longer. To avoid the preference
signal degenerating into "be longer," (a) length-balance pairs where possible,
and (b) use **length-normalised** sequence log-probs (mean per-token, not sum).
Log mean chosen/rejected lengths per step; if Δlength correlates with the win
direction, tighten the balance.

## Preference-data construction

Two patterns, combined (`5_preference.md` §"Preference-data construction"):

1. **Pattern 2 — P4 (chosen) vs SFT-v2 rollout (rejected).** P4 = gold-standard
   English reasoning translated to UGF, the target-probe winner (substance 3.62,
   engagement 3.91). Reliably on-topic — which is the property the prompt-
   attention deficit makes SFT-v2's *own* rollouts unreliable at. Generate via
   the existing P4 path in `eval/run_target_probe.py`; compliance-filter; format
   as a v2 think-answer record. This is the highest-value pair type.
2. **Pattern 3 — on-policy top-K vs bottom-K.** Sample N rollouts from SFT-v2 at
   temp ≈ 0.9; score each by the existing gate+jury reward (`rl_reward.py`,
   `rl_judge.py`) plus the deterministic n-gram doom-loop rule. chosen = top, the
   off-topic / doom-looped ones = rejected. This is the Labonne recipe verbatim
   and targets the model's actual failure distribution.

**Logic track is verifiable — no judge needed there.** For logic prompts,
correctness (verdict matches) is the chosen/rejected label directly — a clean
RLVR-style signal immune to judge bias. Use the jury only for the philosophy
track.

**Pair hygiene:** dedup identical completions; drop pairs where chosen≈rejected
in score (no signal); cap pairs-per-prompt so a few prompts don't dominate; keep
a chosen/rejected length-balance log.

## Hyperparameters (initial)

From `5_preference.md` (Tiny-B ≈ our 200M):

| Param | Value | Note |
|---|---|---|
| LR | 1e-6 | 10–20× below SFT LR (AlexWa2026: 1e-6 preference anchor) |
| β | 0.3 | higher end — judge-labelled pairs are noisy (`5_preference.md`) |
| epochs | 1 | multiple epochs less helpful than for SFT |
| reference | frozen SFT-v2 | reuse the ref-clone pattern in `train_rl.py` |
| NLL-on-chosen anchor | optional, small | DPO+NLL stabiliser; the playbook always favours SFT-mixing |
| pairs | start ~1–3k | comfortable range is 10–50k; expand the prompt set if the smoke test clears |

## Reference + init

Policy initialised from `checkpoints/reasoner_sft_v2/final.pt`; reference is a
frozen clone of the same (DPO/APO both need a frozen ref). **Not** the v3 RL
checkpoint — that one reward-hacked; we start clean from SFT-v2.

## Pre-registered success criteria

Same head-to-head as v3, so it's directly comparable: DPO/APO-final vs SFT-v2 on
the three benches, blinded Claude judges.

- **Primary:** reverse the v3 regression — engagement and substance Δ (vs SFT-v2)
  both **≥ 0**, with engagement clearly up on stress + cx-patched (where v3 was
  −0.40 / −0.80). Preference tuning *amplifies* SFT (`5_preference.md`), so we
  expect modest gains, not a transformation.
- **Guard (DPO failure mode):** chosen and rejected reference-relative log-probs
  must not both collapse. Log Δ(y_w), Δ(y_l) per step; if both trend down under
  DPO, switch to APO-zero (which is designed to prevent this).
- **Stop:** if parse-rate drops below 95% or both log-probs collapse and APO-zero
  doesn't fix it, halt — preference data or β is wrong.

If Stage 1 clears the primary criterion, proceed to **Stage 2 (GRPO)** from the
Stage-1 checkpoint, with the n-gram penalty (as before) and the now-cleaner
starting distribution. If Stage 1 also fails to beat SFT-v2, the honest call is
that SFT-v2 is the final v1 Reasoner and the two RL-negative results
(self-play + preference) become the paper finding.

## Build plan

| Component | Path | Reuse |
|---|---|---|
| P4 reference generation | `reasoner/build_p4_refs.py` (or extend `eval/run_target_probe.py`) | P4 path already exists |
| Preference-pair mining | `reasoner/build_preference_pairs.py` | `rl_rollout.py`, `rl_judge.py`, `rl_reward.py` gates + n-gram rule |
| DPO/APO trainer | `reasoner/train_dpo.py` | `model.py`, ref-clone + per-token logprob fns from `train_rl.py` |
| Config | `configs/reasoner_dpo_v1.yaml` | — |
| SLURM | `slurm/train_reasoner_dpo.sbatch` | — |
| Eval | reuse `slurm/eval_rl_v3_bench.sbatch` → `eval/prepare_rl_milestone_judge_batches.py` (sftv2 vs dpo) → `eval/aggregate_rl_milestone.py` | built |

Order: P4 refs → SFT-v2 rollouts + scoring → pair mining → trainer → smoke (1
epoch) → bench eval. P4 refs + rollouts + judging all go through MR; respect the
`AsyncTokenBucket`; don't run concurrent MR generation.

## Open choices (flag before/at build)

1. **Pattern mix.** Start P4-chosen-heavy (Pattern 2) since the deficit makes
   on-policy "best" unreliable, or balance 50/50 with Pattern 3? Lean Pattern-2-
   heavy for the first smoke test.
2. **Prompt-set size.** Current RL prompt set is ~500. DPO's comfortable range is
   10–50k *pairs*; ~500 prompts × a few pairs ≈ 1–3k pairs is a defensible smoke
   floor, but expanding the prompt pool (more heldout CoT prompts) is the obvious
   first scale-up if the smoke clears.
3. **NLL-on-chosen anchor on or off** for the first run (off = cleaner DPO; on =
   more stable, closer to the playbook's SFT-mixing preference).
