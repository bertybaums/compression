---
title: "Form-controlled retrain — the last lever (length-controlled, matched-pair)"
date: June 3, 2026
status: design (pre-build), for Bert's sign-off on scope before the GPU/MR spend
---

# Form-controlled retrain: the clean, length-controlled test

## Why this experiment, and why now

By elimination, the prompt-attention deficit is down to one suspect. It is not
corpus quality (§4.4: the model sits below its own training data), not a
post-training objective (§4.5: RL worse, DPO ×2 parity), not the restricted
vocabulary (`english-baseline-result-2026-06-02.md`: Δ stress engagement +0.00),
and not raw capacity (`scale-study-result-2026-06-03.md`: flat 0.07/0.00/0.10
across 52M→1B). What is left is the **form** of the training corpus, and the scale
study sharpened *why* it is plausible: the deficit is input-recognition under
distribution shift, and a corpus of short-prompt→long-essay pairs never teaches
the model to condition strongly on the specific prompt. A corpus whose **form
makes prompt-attention constitutive** might.

This is the project's most theoretically motivated lever (the corpus-form insight)
and the one clean lever left untried. It is also pre-registered as no-losing: if
form fixes it, that is the *fix*, the headline the whole project was hunting; if
form does not fix it either, the deficit is a deep property of essay distillation
itself, which is a strong (if sobering) finding in its own right.

## The confound we must kill

The cheap May-24 pilot (§4.5) trained on the existing form corpus and came out
*worse* than an essay control — but it was confounded: the form responses are
short turns (median ~49 words) where the essays run long, so it conflated
*form* with *response length*. The clean test must hold response length fixed and
vary only form.

## Design — a matched pair, varying only form (length-controlled)

Mirror the English-baseline / scale-study machinery exactly, swapping the variable
from vocabulary/size to **response form**:

- **Prompts:** reuse the matched set `corpus/processed/matched_prompts_400k.jsonl`
  (400K `(topic, content_type)` prompts, same teachers per prompt). Both arms see
  the same prompts.
- **Essay arm (control):** essay-form responses — i.e. the existing UGF responses
  for those prompts (`ugf_n_sft_400k.jsonl`), the generic short-prompt→long-essay
  shape v1 learned.
- **Form arm (treatment):** regenerate a response for each prompt in a
  **prompt-attentive form** — the teacher must restate the specific question/claim
  in its own terms, develop a response that turns on *those* specifics, and raise
  and answer the specific objection or consideration the prompt invites; explicitly
  *not* a generic essay on the topic. Form-diverse by content_type (objection-reply,
  dialogue turn, direct-engagement). **Length-matched** to the essay arm by
  instruction *and* verified post-hoc (the form arm's word-length distribution must
  track the essay arm's median ~317w; regenerate/trim outliers until it does).
- **Train both fresh, identical recipe** (the matched-pair recipe: ~400K, the v1
  two-stage schedule), only the response form differs.
- **Eval** with the enbase pipeline (blinded isolation judging), **stress
  engagement primary**, holdout/cx + substance reported alongside.

The single controlled difference is whether the training responses are generic
essays or prompt-attentive engagements of the *same length* on the *same prompts*.

## Pre-registered decision rule

- Form-arm stress engagement **≫** essay-arm (e.g. ≥ +1.0, crossing toward actually
  engaging) → **FORM IS THE FIX.** Prompt-attentive corpus form installs the
  input-recognition the essay corpus never taught. This is the project's payoff.
- Form ≈ essay (flat, within ~0.3) → **form is not the fix either.** With vocabulary,
  capacity, post-training, and now form all ruled out, the deficit looks like a deep
  property of short-prompt→long-essay distillation at this scale — a finding that
  reframes the paper's conclusion from "a deficit we expect to fix" to "a structural
  limit of this distillation regime."
- Between → form contributes; quantify its share.

**Honest expectation:** genuinely uncertain, more so than the last two experiments.
The form hypothesis is the best-motivated of the remaining options, but the deficit
has been unusually stubborn. Either outcome is decisive and publishable.

## Scope options (for sign-off)

- **(A) Matched-pair clean test [recommended].** Regenerate ~400K prompt-attentive,
  length-matched responses (MR campaign, ~2 days under the rate cap), train both
  arms fresh, eval. ~1 week. This is the rigorous, prior-shifting test §6 calls for.
- **(B) Cheaper re-pilot.** Regenerate only the existing ~2,766 form pairs at essay
  length and redo the SFT-only pilot vs an essay control. Days, not a week — but §6
  warns 2,766 pairs are too few to shift a 2M-essay prior, so a null here would be
  inconclusive. Useful only as a fast smoke before committing to (A).

## Compute / cost

| Stage | Estimate (option A) |
|---|---|
| Prompt-attentive generation (~400K, MR, rate-capped) | ~2 days |
| Length-match verification + top-up | ~0.5 day |
| Train 2 fresh 200M arms (matched-pair recipe) | ~1 day each, parallel |
| Eval (gen + blinded judging) | ~0.5 day |
| **Total** | **~1 week** |

## Open choices to confirm with Bert

1. Scope **(A)** vs **(B)** (recommend A).
2. The prompt-attentive generation instruction — draft above; worth one design pass
   on the exact wording + the per-content_type form mapping before the campaign.
3. Whether the essay control is the *existing* `ugf_n_sft_400k.jsonl` or a freshly
   regenerated essay set with the same teachers/run (slightly cleaner; small extra cost).
