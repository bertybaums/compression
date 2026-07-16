---
title: "Factorial A vs B result — response form is not the fix (at fixed prompt diversity)"
date: July 16, 2026
status: RESULT (A vs B closed). ARM C in progress — it tests the live variable.
---

# A vs B: response form, at fixed prompt diversity

## Result

Stress bench, 30 items per arm, blinded Claude-subagent judge, arms scored in
isolation (never mixed in a batch). Anchored 0–4 rubric.

| arm | corpus | unique prompts | engagement | coherence | substance |
|---|---|---|---|---|---|
| **A** | `ugf_n_sft_400k.jsonl` (essay) | 380 | **0.07** | 1.77 | 1.57 |
| **B** | `ugf_form_n.jsonl` (prompt-attentive form) | 380 | **0.03** | 1.33 | 1.27 |
| | | **Δ (B − A)** | **−0.03** | −0.43 | −0.30 |

**Δ stress engagement = −0.03. A null.**

Both arms sit at **essentially zero engagement out of 4**. This is not a small
effect that form failed to enlarge; it is a floor. Both models emit fluent,
well-formed UGF reasoning about something other than what was asked, on nearly
every item. Coherence ~1.3–1.8 against engagement ~0.05 is the deficit's exact
signature: the prose is fine, the topic is wrong.

## What this licenses — and what it does not

**Licensed:** *response form, at fixed prompt diversity, is not the fix.*

**NOT licensed:** the originally pre-registered reading, that form ≈ essay means
"the deficit is a deep property of short-prompt→long-essay distillation at this
scale." That inference is void here, and the reason is structural rather than
statistical: **both arms carry only 380 unique prompts across ~400K examples**
(76 topics × 5 content_types, ~1,053 distinct responses per prompt). In both
corpora `p(response | prompt)` is effectively unconditional within a topic bucket
— the prompt names a bucket, not a target — so attending to prompt detail earns
**nothing** in training loss in *either* arm. Neither model could have learned
prompt-attention. A contrast between two arms that both make the target
unlearnable cannot adjudicate whether the target is learnable.

See the THIRD AMENDMENT in `form-retrain-clean-design-2026-06-03.md`.

## Why B is slightly *worse* on coherence and substance

B trails A by −0.43 coherence and −0.30 substance. Tempting to read as "form
hurts" — which is also how the May-24 pilot was read. Do not lean on it:

1. B's responses run **−7.7% shorter** (word median 263 vs 285), so B saw ~7.7%
   fewer tokens per epoch at the identical 30K-step recipe.
2. 30 items, one judge per arm. Deltas of ~0.3–0.4 are within the noise this
   bench was always acknowledged to carry.
3. The May-24 "form is worse" result is separately confounded: that corpus varied
   form **and** prompt diversity (2,858 unique prompts / 2,873 examples — a ratio
   of 0.99 against these arms' 0.0009) **and** size (2,873 vs 400K) **and** length
   (median ~49w vs ~285w) simultaneously.

The honest summary of the form axis: at fixed prompt diversity, form does nothing
for engagement, and any coherence/substance cost is within noise and confounded
with length.

## Where this leaves the elimination chain

Every lever tried so far has come out flat:

| lever | result | prompt diversity during the test |
|---|---|---|
| capacity (52M / 197M / 1.03B) | flat (0.07 / 0.00 / 0.10) | **fixed at 380** |
| vocabulary (English baseline) | flat (Δ = +0.00) | **fixed at 380** |
| post-training (DPO ×2) | parity | **fixed at 380** |
| post-training (RL/GRPO) | worse | **fixed at 380** |
| **response form (this result)** | **flat (Δ = −0.03)** | **fixed at 380** |

Five levers, five nulls, one variable never varied. Note especially the
**English baseline**: `english_n_sft.jsonl` also carries 380 unique prompts /
400K examples. Swapping the *entire vocabulary* changed nothing — a startling
null on its own terms, and exactly what you would predict if the binding
constraint sits upstream of vocabulary in the corpus itself.

That is the case for ARM C. It is the first arm in which conditioning on the
prompt can pay off at all.

## Method notes

- **Judge drift controlled.** ARM A was *re-judged* from its existing June 2
  generation files rather than reusing its June scores: the judge is a Claude
  subagent, and June's instance is not today's. On a 30-item bench read to ~0.3
  resolution that confound is not affordable. A's generations were re-scored, not
  regenerated.
- **Isolation.** One arm + one bench per batch. The precursor showed cross-register
  contrast depresses the restricted arm ~1 substance point on *identical* text.
- **Blinding.** Opaque batch filenames, `{id, prompt, response}` only, batch order
  shuffled so batch number cannot leak arm identity.
- **ARM A cost nothing.** It was already trained *and* generated (June 2, as the
  enbase UGF arm), so the factorial needed one training job per new arm, not three.

## Artifacts

- Generations: `eval/results/factorial_form_n_stress_20260716_070441.jsonl`;
  ARM A `eval/results/enbase_ugf_n_stress_20260602_081559.jsonl`
- Blinded batches: `eval/judge_input_factorial/`, scores `eval/judge_output_factorial/`
- Mapping: `eval/factorial_judge_manifest.json` (the judge never sees this)
- Aggregation + narrowed rule: `eval/aggregate_factorial_judge.py`
- Training: `configs/reasoner_form_n_sft.yaml`, job 5184590 (30K steps, val loss
  0.9348, ppl 2.55)
