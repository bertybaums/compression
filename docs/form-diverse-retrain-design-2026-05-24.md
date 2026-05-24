---
title: "Form-diverse retraining — scoping (option 2)"
date: May 24, 2026
audience: project
status: scoping (pre-build) — decision doc
---

# Form-diverse retraining: scoping

## The short version

The prompt-attention deficit survived purist SFT, self-play RL, and two DPO runs (`dpo_stage1_2026-05-22`, `rl_v3_outcome_2026-05-22`). Every post-training lever failed because they all operate on a model whose *prior* is already set: the v1 model learned the essay form from 2M traces and runs it on reflex. The one untried lever is the prior itself. This doc scopes how to change it, what it will cost, and the forks worth deciding before any compute.

The central fact that shapes everything below: **the form-diverse corpus is 2,766 pairs; the v1 corpus is 2.0M.** The experiment is not "add a little form-diverse data." It is "shift a deeply entrenched form-prior with a small, structurally-different corpus." That framing decides the design.

## The hypothesis (restated, with a sharpening)

Form, not topic or vocabulary, is the lever (`corpus_form_insight`). A Socratic dialogue is a prompt-attention training corpus by construction: the second speaker must engage the first speaker's specific move, or the dialogue breaks. The v1 corpus is uniformly short-topic-phrase prompts followed by long essays, and the model learned that mapping so well that the essay runs even when the prompt does not warrant it. Train on data whose *structure* enforces specific-engagement, and the model should inherit the property.

The sharpening from the post-training failures: the deficit is upstream and entrenched, so a light continuation will likely be too weak to move it. We should expect to either upsample the form data hard, rebalance the training mix toward form, or scale the form corpus, not merely sprinkle 2,766 pairs onto a 2M-trace prior.

## Ground truth (verified May 24)

| Asset | State |
|---|---|
| Form corpus | `corpus/processed/ugf_forms_corpus.jsonl`: 2,766 compliant / 2,873 total |
| Form mix | dialogue 1,170 (Plato ×7 + Hume 41), objection_reply 1,678 (Aquinas), skeptical 25 |
| Pair shape | prompt median 47 words, response median 49 — short turn→turn, prompt-attentive (good) |
| v1 corpus | `ugf_reasoning.jsonl`: 2.0M traces (the entrenched essay prior) |
| Checkpoints | `pretrain_v1`, `sft_v1` (plain prompt→response), `sft_v2` (think-answer marker), rl/dpo |
| Pipeline | forms.py, parse_{plato,hume,aquinas,sextus}.py, generate_forms.py, generate_forms_corpus.sbatch — all built, resumable |

## A nuance on "redoing pretraining"

The form signal is fundamentally a *supervised input→output property*: the response engages the specific prompt. That is an SFT signal, not a pretraining one. Continued-pretraining on raw dialogue text would teach the model dialogue *style* (next-token over dialogue prose) but not the prompt→response *attention mapping* as directly as SFT on (turn_A, turn_B) pairs. So the most direct test of the hypothesis is an SFT-stage intervention, not a pretraining-stage one.

That said, the "redo pretraining" instinct is right about *scale of intervention*, for a different reason: the essay prior is plausibly set partly in pretraining (the base model saw essay-shaped UGF before SFT ever ran), so a fresh SFT alone may not dislodge it. The honest reading: we likely need a *fresh SFT from the pretrain checkpoint on a form-rebalanced mix* (touching the SFT stage, from the base model, not continuing the essay-saturated SFT-v2), and possibly a pretraining-mix change only if that is not enough. We treat the pretraining-stage rewrite as the heavier fallback, not the first move.

## Format consideration (a real wrinkle)

The form pairs are plain `(prompt, response)` — a dialogue reply, an objection's answer. They are **not** in SFT-v2's think-answer format ("reasoning … So my answer is: answer"), and a dialogue turn does not naturally decompose into reasoning+marker+answer. So we cannot cleanly continue SFT-v2 on form data without a format clash. Two clean ways out:

- **Plain format (recommended for the pilot):** run the form SFT in the v1 plain `(prompt→response)` format, from `pretrain_v1` or `sft_v1`. Matches the form corpus natively; isolates the form effect; comparison baseline is v1.
- **Unified think-answer:** reformat form responses into think-answer (hard for dialogue; feasible for objection-reply where the reply *is* an answer). Defer unless the pilot motivates it.

## Proposed design — phased, cheap signal first

### Phase 0 — cheap pilot: is there *any* signal? (~2 days)

A controlled SFT comparison from the same `pretrain_v1` base, plain format, holding everything but corpus form constant:

- **Arm A (control):** SFT on a 2,766-trace random sample of the v1 essay corpus.
- **Arm B (treatment):** SFT on the 2,766 form pairs (optionally upsampled 3–5× to fight the prior).
- Same steps, same format, same base. Eval both on the established bench (stress / cx-patched / holdout), blinded vs each other and vs SFT-v2.

This is a true minimal test of the hypothesis: the *only* difference between A and B is corpus form. If B beats A on OOD engagement, form is the lever and we scale. If B ≈ A, a 2.8K-pair dose is too small or form is not the fix at this scale, and we learn that for ~2 days of compute before committing weeks.

**Caveat to pre-register:** a null Phase-0 result is *ambiguous* (dose too small vs form-not-the-fix). A positive result is decisive (scale it). So Phase 0 can greenlight but not kill the program.

### Phase 1 — scale the corpus, then a real retrain (~2–3 weeks, only if Phase 0 is positive or ambiguous-but-promising)

The pipeline is built; the gap is source coverage. Highest-value additions (all public-domain, parsers are the only work): rest of Plato, Berkeley *Three Dialogues*, Descartes *Meditations + Objections and Replies*, more of Aquinas (II, II-II, III), Hume's *Dialogues* in full. Target ~20–50K form pairs (10–20× the current corpus), enough to be a real fraction of an SFT mix. Then a fresh SFT-v3 from `pretrain_v1` on a form-heavy mix (e.g., 50% form / 50% v1+CoT), plain or unified format, eval on the bench.

### Pre-registered eval + success criterion

Identical to the v3/DPO head-to-heads, so it slots directly into the comparison table: blinded Claude judges, 4-dim rubric, stress + cx-patched + holdout, the form-trained model vs SFT-v2. **Success = OOD engagement and substance rise meaningfully above SFT-v2** (the dims every post-training method left flat or worse). The stress bench is the key target: v1 engagement there was 0.13, and that is the number form-diversity should move.

## Decision forks (for Bert)

1. **Vehicle:** SFT-stage intervention (recommended — directly tests the form→attention mapping) vs a literal pretraining rewrite (heavier; defer to fallback).
2. **Scope now:** cheap Phase-0 pilot on the existing 2.8K first (recommended), vs skip straight to scaling the corpus (Phase 1) on the bet that 2.8K is obviously too small.
3. **Format:** plain `(prompt→response)` (recommended for the pilot, matches the data) vs unified think-answer (defer).

## Risks and honest caveats

- **The corpus may be too small to move the prior** even upsampled; that is why Phase 0 is framed as greenlight-only.
- **Form mix is lopsided** (58% Aquinas objection-reply, 41% dialogue, ~1% skeptical); scaling should rebalance toward dialogue, the highest prompt-attention-value form.
- **The deficit might be capacity, not form.** If Phase 0 is null and a scaled Phase 1 also fails, the remaining explanation is model scale, which points to the scaling thread (`docs/followups/scaling.md`), not more corpus work. Form-diverse retraining and the scale study are the two live hypotheses; this experiment is the cheaper one to run first.
- **Forgetting / overfitting:** a fresh-from-pretrain SFT (not a continuation of SFT-v2) plus a v1+CoT mix in Arm B guards against collapsing onto 2.8K pairs.

## First concrete steps (Phase 0)

1. Verify the form corpus + parsers are current on fortyfive (done: 2,766 pairs).
2. Add an SFT data path that reads `ugf_forms_corpus.jsonl` in plain `(prompt→response)` format, with an upsample factor.
3. Sample 2,766 v1 essay traces for Arm A (control).
4. Two SFT runs from `pretrain_v1/final.pt`, identical hyperparameters, ~same step budget as SFT-v1.
5. Bench-gen both (`eval_ckpt_bench.sbatch`, TAG=sft_form_A / sft_form_B), blinded judge, aggregate — reusing the v3/DPO eval pipeline.
