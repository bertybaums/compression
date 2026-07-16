---
title: "Form-controlled retrain — the last lever (length-controlled, matched-pair)"
date: June 3, 2026
updated: July 16, 2026
status: ON HOLD (July 16, 2026) — the form arm is ALREADY GENERATED (June 9), but a corpus audit shows this design cannot deliver its treatment as stated. Read the third amendment FIRST.
---

> # THIRD AMENDMENT (July 16, 2026) — READ BEFORE RUNNING ANYTHING
>
> **Two discoveries, one of which voids the experiment as specified.**
>
> ## 1. The campaign is already done
> `corpus/processed/ugf_form_n.jsonl` — **399,984 examples, generated June 9, 2026**, 97.4% UGF-compliant, word median 263. The "~2 days of MR generation" this doc budgets was already spent five weeks ago. Both arms exist on disk; only training + eval remain (~1 day each, parallel). Do not regenerate.
>
> ## 2. The corpus makes prompt-attention unlearnable — in BOTH arms
> Audited July 16:
>
> | corpus | examples | unique prompts | repeats/prompt |
> |---|---|---|---|
> | `ugf_n_sft_400k.jsonl` (essay arm) | 400,000 | **380** | ~1,053 |
> | `ugf_form_n.jsonl` (form arm) | 399,984 | **380** | ~1,053 |
>
> 380 = 76 topics × 5 content_types. Responses are ~all distinct (399,999/400,000 in the essay arm), so **each prompt maps to ~1,053 different responses**. `p(response | prompt)` is effectively unconditional *within* a bucket: the prompt identifies a topic bucket, not a target. Attending to prompt detail beyond bucket-ID earns the model **nothing** in training loss — so it doesn't learn to.
>
> Meanwhile the stress bench is 30 items, **30 unique, specific, multi-part prompts** ("Walk me through what makes something necessarily true versus only sometimes true. Use a concrete example for each."). That is the distribution shift: 380 memorizable buckets at SFT → novel prompts that must actually be read at eval. (The 2M pretraining corpus `ugf_reasoning.jsonl` is raw `ugf_text` with no prompts at all, so SFT is the only stage where prompt-conditioning could be learned.)
>
> **Why this voids the design.** §"Why this experiment" argues: *"a corpus of short-prompt→long-essay pairs never teaches the model to condition strongly on the specific prompt. A corpus whose form makes prompt-attention constitutive might."* But the form arm reuses the **same 76 topics** through 5 pointed templates — still 380 prompts, still ~1,053 repeats. The pointed templates change the *response* style; they do not put any specifics **into the prompt**. Worse, the topics are general subjects ("what makes a good reason for believing something"), so the template "Someone makes this exact case: {topic}" is a category error — the teacher must **invent** the specific case and then engage its own invention. Prompt-attention is therefore *not* constitutive in the form arm either. It is not merely un-taught; it is **unlearnable from this corpus**.
>
> **The likely reason every prior lever came out flat.** Capacity (52M/197M/1.03B), vocabulary (English baseline), DPO, and RL were all varied *while holding prompt diversity fixed at 380*. If prompt-uninformativeness is the binding constraint, every one of those controls was downstream of it — and flat results are exactly what you'd expect. The elimination chain never touched the live variable.
>
> ## Consequence for the decision rule
> The pre-registered rule says form ≈ essay → *"the deficit looks like a deep property of short-prompt→long-essay distillation at this scale."* **Do not draw that conclusion from this pair.** A null here licenses only the narrower claim: *form-at-fixed-prompt-diversity (380 buckets) is not the fix.* Reading it as a structural limit of distillation would close the project's last lever on a confound.
>
> ## Revised path
> - **A vs B — free, run now.** Both corpora exist. Train the two arms (identical recipe) and eval. Zero generation cost, ~1 day. Answers "does response form help at fixed prompt diversity?" under the **narrowed** interpretation above.
> - **C — the untested lever: prompt informativeness.** Generate a corpus whose prompts *carry the specifics* (~400K distinct claims/cases/questions rather than 76 recycled topics), so conditioning on the prompt actually pays off in training loss. B vs C isolates diversity at fixed form. This is the hypothesis the audit promotes to first place.
> - **Length note.** The existing form arm's median is 263 vs the essay arm's 285 → **−7.7%**, which trips the −5% short-side gate in `check_length_match.py`. Not the May-24 catastrophe (6.5× short), but handle it: token-equalize, or train on a pairwise length-matched subset, and report it. A fresh 2K natural pilot (killed early, July 16) independently reproduced this at −6.0%, so the drift is real, not sampling noise.
> - **Re-examine May-24.** The old form corpus (`ugf_forms_corpus.jsonl`) has **2,858 unique prompts / 2,873 examples** — genuinely diverse. So the May-24 pilot varied form **and** prompt diversity **and** size **and** length simultaneously. Its "form is worse" reading is not safe either.
>
> ## Addendum (July 16, later) — UGF cannot name, only describe
>
> Building arm C's case pool surfaced a result worth the paper's attention in its own right. Asking teachers for *specific cases* under the UGF wordlist produced a **~92% vocabulary-violation rate** (2,819 rejected vs 249 kept). The rejections are not random — they are exactly the machinery of particularity:
>
> | rejected token | category |
> |---|---|
> | `Ali`, `Bo` | proper names |
> | `wallet`, `dollars` | particular objects, money |
> | `farmer`, `patients`, `doctor` | occupations, roles |
> | `charity` | institutions |
> | `noon` | specific times |
>
> **A ~1,000-word vocabulary cannot individuate by naming.** The cases that survive individuate the only way UGF permits — by *definite description*: "the man in the white shirt will give the small silver key to the woman in the black dress at the station"; "if a car must hit one person or five people, should the driver turn the wheel?" The wordlist enforces **Russell's theory of descriptions** as a matter of expressive necessity rather than philosophical preference. Particularity survives; naming does not; the cost is periphrasis.
>
> This is the Sheffer-stroke thesis landing in a second place, and it sharpens the Ch 6 argument: the earlier finding was that a restricted vocabulary dilates *expression*; this one is that it relocates *reference* from names to descriptions. Teaching the pattern up front (few-shot with real survivors + explicit anti-patterns and their periphrastic repairs) lifted the pass rate **8.1% → 26.8%**, which is the difference between a ~2-day and a ~5–10-hour case-pool campaign — but the underlying constraint is a property of the vocabulary, not of the prompt.

> **Sign-off (July 16, 2026).** The three open choices in §"Open choices to confirm with Bert" are settled:
>
> 1. **Scope: (A)** the matched-pair clean test (~400K prompt-attentive regeneration, both arms trained fresh, ~1 week).
> 2. **Generation instruction:** design pass done — see the amendment below. A **length-control defect was found and fixed** before any spend.
> 3. **Essay control: reuse the existing `ugf_n_sft_400k.jsonl`.** No fresh essay regeneration. It is the corpus v1 actually learned, and it costs no MR time; the teachers/run drift against a freshly-generated form arm is accepted as a small, noted confound.
>
> **Amendment — the length control was specified but not implemented.** §"Design" requires the form arm be length-matched "by instruction *and* verified post-hoc," and this is the confound that invalidated the May-24 pilot (form median ~49w vs essays ~317w). As built, `generate_form_attentive.py` did **neither**: the pointed templates asked only for "a full, developed answer" with no word target, and no word counts were recorded, so the post-hoc check was impossible. Running 400K generations that way risked re-confounding the experiment and rendering a null uninterpretable — the precise ambiguity this design exists to remove. Now fixed: an explicit word target in every pointed template (and in the UGF correction retry), `n_words` recorded per record, and the live length distribution (median / mean / % within 20% of target) written to the progress file and printed every 200 completions, so drift surfaces in minutes rather than after ~2 days of spend.
>
> ~~**Pre-flight, still required:** `--target-words` defaults to 317 from this doc's prose. **Measure the essay arm's true median** (`corpus/processed/ugf_n_sft_400k.jsonl`) and pass the measured value; do not trust the default. The post-hoc distribution comparison against the essay arm remains a gate before either arm is trained.~~ *(Superseded by the second amendment below — the word-target instruction was removed entirely.)*

> **Second amendment (July 16, 2026, later the same day) — length is measured, not clamped.** Bert's objection, sustained: in a ~1K-word vocabulary, saying something *specific* costs periphrasis, so response length is partly **constitutive of form** — the Sheffer-stroke point at discourse level. Whether prompt-attentive UGF needs more words than essay UGF is an empirical finding, not a nuisance to suppress. Three faults with the word-target instruction added in the first amendment:
>
> 1. **It conditions on a mediator.** If form → length → learning outcome, clamping length subtracts part of the treatment effect. Worst case: form is the fix only when given room, the clamp starves it, and the project's last lever returns a **false null**.
> 2. **It breaks arm symmetry.** The essay arm was generated with *no* length instruction (measured July 16: median 285, mean 303, σ=129, max 10,236 — not the ~317 this doc guessed). Instructing only the form arm makes the arms differ in two ways.
> 3. **It pollutes the training prompts.** The pointed prompt is stored as the training prompt, so the clause would be a systematic prompt-side artifact between arms, absent from the stress bench at eval.
>
> **Revised procedure:** the form arm generates **natural**. `n_words` is recorded per record; the live median (and drift vs `--reference-median 285`, monitoring only) prints during the run. `check_length_match.py` computes the **within-prompt dilation ratio** (form/essay on shared prompt ids) and gates *training*, direction-aware: form median >5% **short** of essay → FAIL (the May-24 mode); >50% **long** → FAIL (stop; the dilation may be the headline); in between → PASS, and if long by >5%, equalize **total training tokens** by shrinking the form arm's example count by the printed factor, with a pairwise length-matched subset as a robustness check. Dispersion mismatch warns but never fails (a tighter-but-centered form arm does not reproduce the May-24 confound). **Pilot first:** ~2K matched prompts, natural, before the full ~400K campaign — the dilation number decides the path.
>
> The reporting obligation moves accordingly: the paper claims "form differs; total training tokens equalized; natural dilation measured and reported" rather than "arms differ only in form at generation."

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
