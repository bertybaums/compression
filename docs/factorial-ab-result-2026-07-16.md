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

## The deficit is out-of-distribution, not a broken model

ARM A's June scores across benches locate the failure precisely:

| ARM A / bench | n | engagement | coherence | substance |
|---|---:|---:|---:|---:|
| stress (OOD prompt forms) | 30 | **0.07** | 1.93 | 0.40 |
| holdout (in-distribution) | 170 | **1.68** | 2.51 | 2.16 |
| cx_patched | 50 | 0.30 | 1.86 | 0.78 |

Engagement 1.68 in-distribution against 0.07 on stress. The model is not broken;
it works when the prompt resembles its 380 training buckets and collapses when the
prompt must actually be read. That is the deficit, localized — and it is precisely
the profile a corpus with 380 prompts and ~1,053 responses each would produce.

## Method notes

- **Judge drift controlled — and it mattered.** ARM A was *re-judged* from its
  existing June 2 generation files rather than reusing its June scores: the judge is
  a Claude subagent, and June's instance is not today's. On a 30-item bench read to
  ~0.3 resolution that confound is not affordable. A's generations were re-scored,
  not regenerated. The re-judge shows the drift is **dimension-specific**:

  | ARM A / stress | June | July re-judge | drift |
  |---|---:|---:|---:|
  | engagement | 0.07 | **0.07** | **0.00** |
  | coherence | 1.93 | 1.77 | 0.16 |
  | substance | **0.40** | **1.57** | **1.17** |

  Engagement replicated *exactly*; substance moved 1.17 — nearly 30% of the scale.
  So the headline (engagement) is judge-stable and safely comparable even across
  instances, while **substance is not**: any substance delta drawn against a
  differently-judged arm is unsafe, including the enbase §4.6 substance figures if
  re-used later. Report substance deltas only within a single judging pass. This
  also retroactively supports the decision to re-judge rather than reuse — had we
  reused June, the A→B substance delta would have been reported as roughly +1.2
  instead of −0.30, a sign error.
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
